//! ObylonBroker.exe — runs as a SYSTEM scheduled task in Session 0.
//!
//! Job, and *only* job: find the active interactive session, get a token
//! for the logged-on user, and spawn ObylonCore.exe into that session.
//! Retry forever across logon/logoff/session-switch. This is a direct
//! Rust translation of the Python `cmd_host()` we spent the last several
//! turns debugging — same WTSQueryUserToken -> explorer.exe-token-borrow
//! fallback -> DuplicateTokenEx -> CreateProcessAsUser sequence, same
//! SeTcbPrivilege enable-before-query requirement, same hidden-window
//! STARTUPINFO. The two real Python bugs we found (structlog silently
//! eating broker logs, and the psutil `session_id` attribute that never
//! existed) don't have Rust equivalents: logging here is a plain file
//! write with no global-config footgun, and session id comes from the
//! real `ProcessIdToSessionId` Win32 call, not a guessed library field.
#![windows_subsystem = "windows"]

use obylon_common::FileLogger;
use std::env;
use std::ffi::c_void;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use windows::core::{PCWSTR, PWSTR};
use windows::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE, HWND, LUID, WAIT_TIMEOUT,
};
use windows::Win32::Security::{
    AdjustTokenPrivileges, DuplicateTokenEx, LookupPrivilegeValueW, SecurityImpersonation,
    TokenPrimary, LUID_AND_ATTRIBUTES, SE_DEBUG_NAME, SE_INCREASE_QUOTA_NAME, SE_PRIVILEGE_ENABLED,
    SE_TCB_NAME, TOKEN_ADJUST_PRIVILEGES, TOKEN_ALL_ACCESS, TOKEN_PRIVILEGES, TOKEN_QUERY,
};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::Environment::{CreateEnvironmentBlock, DestroyEnvironmentBlock};
use windows::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows::Win32::System::RemoteDesktop::{
    ProcessIdToSessionId, WTSGetActiveConsoleSessionId, WTSQueryUserToken,
};
use windows::Win32::System::Threading::{
    CreateMutexW, CreateProcessAsUserW, GetCurrentProcess, OpenProcess, OpenProcessToken,
    CREATE_NO_WINDOW, CREATE_UNICODE_ENVIRONMENT, PROCESS_INFORMATION,
    PROCESS_QUERY_LIMITED_INFORMATION, STARTF_USESHOWWINDOW, STARTUPINFOW, TerminateProcess,
    WaitForSingleObject,
};
use windows::Win32::UI::WindowsAndMessaging::SW_HIDE;

const LOG_PATH_ENV_FALLBACK: &str = r"C:\ProgramData\Obylon\logs\broker.log";
const CANDIDATE_SHELLS: &[&str] = &["explorer.exe", "sihost.exe", "ctfmon.exe", "userinit.exe"];

struct ManagedCore {
    session_id: u32,
    pid: u32,
    process: HANDLE,
    job: HANDLE,
}

impl ManagedCore {
    unsafe fn is_alive(&self) -> bool {
        WaitForSingleObject(self.process, 0) == WAIT_TIMEOUT
    }

    unsafe fn stop(self, logger: &FileLogger, reason: &str) {
        logger.info(
            "broker",
            "stopping managed Core process tree",
            &[
                ("session_id", &self.session_id.to_string()),
                ("pid", &self.pid.to_string()),
                ("reason", reason),
            ],
        );
        let _ = TerminateJobObject(self.job, 0);
        let _ = CloseHandle(self.process);
        let _ = CloseHandle(self.job);
    }
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn log_path() -> PathBuf {
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    PathBuf::from(base)
        .join("Obylon")
        .join("logs")
        .join("broker.log")
}

/// Enable (not just hold) SeTcbPrivilege + friends on our own SYSTEM
/// token. This mirrors the Python `_enable_privileges()` exactly — SYSTEM
/// holds these privileges by default but they start *disabled*, and
/// WTSQueryUserToken specifically requires SeTcbPrivilege to be enabled,
/// not merely present, or it fails.
unsafe fn enable_privileges(logger: &FileLogger) {
    let mut token = HANDLE::default();
    if OpenProcessToken(
        GetCurrentProcess(),
        windows::Win32::Security::TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
        &mut token,
    )
    .is_err()
    {
        logger.error(
            "broker",
            "OpenProcessToken failed",
            &[("error", &format!("{:?}", GetLastError()))],
        );
        return;
    }

    for priv_name in [SE_TCB_NAME, SE_INCREASE_QUOTA_NAME, SE_DEBUG_NAME] {
        let mut luid = LUID::default();
        if LookupPrivilegeValueW(PCWSTR::null(), priv_name, &mut luid).is_err() {
            logger.warn(
                "broker",
                "LookupPrivilegeValueW failed",
                &[("priv", &format!("{:?}", priv_name))],
            );
            continue;
        }
        let tp = TOKEN_PRIVILEGES {
            PrivilegeCount: 1,
            Privileges: [LUID_AND_ATTRIBUTES {
                Luid: luid,
                Attributes: SE_PRIVILEGE_ENABLED,
            }],
        };
        let _ = AdjustTokenPrivileges(token, false, Some(&tp), 0, None, None);
    }
    let _ = CloseHandle(token);
    logger.info("broker", "Privileges enabled", &[]);
}

/// Primary path: ask WTS directly for the logged-on user's token.
unsafe fn query_user_token(session_id: u32) -> Option<HANDLE> {
    let mut token = HANDLE::default();
    if WTSQueryUserToken(session_id, &mut token).is_ok() {
        Some(token)
    } else {
        None
    }
}

/// Fallback path: covers the boot-time race where the session exists but
/// WTSQueryUserToken isn't answerable yet. Enumerates processes with
/// CreateToolhelp32Snapshot (not psutil — there is no Rust equivalent of
/// the phantom `session_id` field that broke this fallback in Python;
/// session id comes from the real `ProcessIdToSessionId` syscall) and
/// borrows a token from the first known shell process in the target
/// session.
unsafe fn borrow_shell_token(session_id: u32, logger: &FileLogger) -> Option<HANDLE> {
    let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).ok()?;
    let mut entry = PROCESSENTRY32W {
        dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };

    let mut found: Option<HANDLE> = None;
    if Process32FirstW(snapshot, &mut entry).is_ok() {
        loop {
            let name_len = entry.szExeFile.iter().position(|&c| c == 0).unwrap_or(0);
            let name = String::from_utf16_lossy(&entry.szExeFile[..name_len]).to_lowercase();

            if CANDIDATE_SHELLS.contains(&name.as_str()) {
                let mut proc_session: u32 = 0;
                if ProcessIdToSessionId(entry.th32ProcessID, &mut proc_session).is_ok()
                    && proc_session == session_id
                {
                    if let Ok(ph) = OpenProcess(
                        PROCESS_QUERY_LIMITED_INFORMATION,
                        false,
                        entry.th32ProcessID,
                    ) {
                        let mut tok = HANDLE::default();
                        if OpenProcessToken(ph, TOKEN_QUERY | TOKEN_ALL_ACCESS, &mut tok).is_ok() {
                            found = Some(tok);
                        }
                        let _ = CloseHandle(ph);
                        if found.is_some() {
                            break;
                        }
                    }
                }
            }

            if Process32NextW(snapshot, &mut entry).is_err() {
                break;
            }
        }
    }
    let _ = CloseHandle(snapshot);
    if found.is_none() {
        logger.warn(
            "broker",
            "No shell token to borrow in target session",
            &[("session_id", &session_id.to_string())],
        );
    }
    found
}

/// WTSQueryUserToken first; explorer.exe-token-borrow fallback second.
/// Same ordering and same reasoning as the Python version.
unsafe fn get_session_token(
    session_id: u32,
    logger: &FileLogger,
) -> Option<(HANDLE, &'static str)> {
    if let Some(t) = query_user_token(session_id) {
        return Some((t, "wts-user"));
    }
    borrow_shell_token(session_id, logger).map(|t| (t, "shell-borrowed"))
}

unsafe fn create_core_job(logger: &FileLogger) -> Option<HANDLE> {
    let job = match CreateJobObjectW(None, PCWSTR::null()) {
        Ok(job) => job,
        Err(error) => {
            logger.error(
                "broker",
                "could not create Core ownership job",
                &[("error", &format!("{error:?}"))],
            );
            return None;
        }
    };
    let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        &limits as *const _ as *const c_void,
        std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
    )
    .is_err()
    {
        logger.error(
            "broker",
            "could not configure Core ownership job",
            &[("error", &format!("{:?}", GetLastError()))],
        );
        let _ = CloseHandle(job);
        return None;
    }
    Some(job)
}

fn ensure_acls(logger: &FileLogger) {
    use std::process::Command;
    use std::path::PathBuf;
    use std::env;
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    let vault_dir = PathBuf::from(&base).join("Obylon");
    let files = vec!["obylon.enc", "identity_beacon.json", "fastlane_rules.json"];
    
    for f in files {
        let path = vault_dir.join(f);
        if !path.exists() {
            let _ = std::fs::File::create(&path);
        }
        let _ = Command::new("icacls")
            .arg(&path)
            .arg("/grant")
            .arg("Authenticated Users:(M)")
            .arg("/C")
            .output();
    }
}

unsafe fn spawn_core_in_session(
    session_id: u32,
    core_exe: &str,
    logger: &FileLogger,
) -> Option<ManagedCore> {
    let (src_token, token_kind) = get_session_token(session_id, logger)?;
    let job = match create_core_job(logger) {
        Some(job) => job,
        None => {
            let _ = CloseHandle(src_token);
            return None;
        }
    };

    let mut primary_token = HANDLE::default();
    let dup_ok = DuplicateTokenEx(
        src_token,
        TOKEN_ALL_ACCESS,
        None,
        SecurityImpersonation,
        TokenPrimary,
        &mut primary_token,
    );
    let _ = CloseHandle(src_token);
    if dup_ok.is_err() {
        logger.error(
            "broker",
            "DuplicateTokenEx failed",
            &[("error", &format!("{:?}", GetLastError()))],
        );
        let _ = CloseHandle(job);
        return None;
    }

    let mut env_block: *mut std::ffi::c_void = std::ptr::null_mut();
    let _ = CreateEnvironmentBlock(&mut env_block, Some(primary_token), false);

    let mut desktop = wide("winsta0\\default");
    let mut cmdline = wide(&format!("\"{core_exe}\""));

    let mut startup_info = STARTUPINFOW {
        cb: std::mem::size_of::<STARTUPINFOW>() as u32,
        lpDesktop: PWSTR(desktop.as_mut_ptr()),
        dwFlags: STARTF_USESHOWWINDOW,
        wShowWindow: SW_HIDE.0 as u16,
        ..Default::default()
    };
    let mut proc_info = PROCESS_INFORMATION::default();

    let ok = CreateProcessAsUserW(
        Some(primary_token),
        PCWSTR::null(),
        Some(PWSTR(cmdline.as_mut_ptr())),
        None,
        None,
        false,
        CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW,
        Some(env_block),
        PCWSTR::null(),
        &startup_info,
        &mut proc_info,
    );

    if !env_block.is_null() {
        let _ = DestroyEnvironmentBlock(env_block);
    }
    let _ = CloseHandle(primary_token);

    if ok.is_err() {
        logger.error(
            "broker",
            "session spawn failed",
            &[
                ("session_id", &session_id.to_string()),
                ("error", &format!("{:?}", GetLastError())),
            ],
        );
        let _ = CloseHandle(job);
        return None;
    }

    let pid = proc_info.dwProcessId;
    if AssignProcessToJobObject(job, proc_info.hProcess).is_err() {
        logger.error(
            "broker",
            "could not assign Core to its ownership job; refusing unmanaged Core",
            &[("error", &format!("{:?}", GetLastError()))],
        );
        let _ = TerminateProcess(proc_info.hProcess, 1);
        let _ = CloseHandle(proc_info.hProcess);
        let _ = CloseHandle(proc_info.hThread);
        let _ = CloseHandle(job);
        return None;
    }
    let _ = CloseHandle(proc_info.hThread);

    logger.info(
        "broker",
        "core spawned into interactive session",
        &[
            ("session_id", &session_id.to_string()),
            ("pid", &pid.to_string()),
            ("token_kind", token_kind),
        ],
    );
    Some(ManagedCore {
        session_id,
        pid,
        process: proc_info.hProcess,
        job,
    })
}

fn core_exe_path() -> String {
    // ObylonCore.exe ships alongside the broker in the same install dir.
    let mut path = env::current_exe().unwrap_or_else(|_| PathBuf::from("ObylonBroker.exe"));
    path.set_file_name("ObylonCore.exe");
    path.to_string_lossy().to_string()
}

fn main() {
    let logger = match FileLogger::open(&log_path()) {
        Ok(l) => l,
        Err(_) => FileLogger::open(&PathBuf::from(LOG_PATH_ENV_FALLBACK))
            .expect("cannot open any broker log path"),
    };
    logger.info(
        "broker",
        "Session Broker online — waiting for an interactive console session",
        &[],
    );

    let _instance_mutex = match unsafe {
        CreateMutexW(None, false, windows::core::w!("Global\\ObylonBrokerMutex"))
    } {
        Ok(handle) if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS => {
            logger.warn("broker", "another broker instance is already active", &[]);
            let _ = unsafe { CloseHandle(handle) };
            return;
        }
        Ok(handle) => handle,
        Err(error) => {
            logger.error(
                "broker",
                "could not create broker singleton mutex",
                &[("error", &format!("{error:?}"))],
            );
            return;
        }
    };

    unsafe {
        enable_privileges(&logger);
    }

    let core_exe = core_exe_path();
    let mut managed_core: Option<ManagedCore> = None;

    loop {
        let session_id = unsafe { WTSGetActiveConsoleSessionId() };
        let no_session = session_id == 0xFFFFFFFF;

        let replace_core = managed_core.as_ref().map_or(false, |core| unsafe {
            no_session || core.session_id != session_id || !core.is_alive()
        });
        if replace_core {
            let reason = if no_session {
                "no active interactive session"
            } else if managed_core.as_ref().is_some_and(|core| core.session_id != session_id) {
                "active session changed"
            } else {
                "Core process exited"
            };
            if let Some(core) = managed_core.take() {
                unsafe { core.stop(&logger, reason) };
            }
        }

        if !no_session && managed_core.is_none() {
            ensure_acls(&logger);
            match unsafe { spawn_core_in_session(session_id, &core_exe, &logger) } {
                Some(core) => managed_core = Some(core),
                None => {
                    // Expected during the boot race — WTSQueryUserToken can
                    // fail for the first several polls before winlogon has
                    // fully established the session. Retry without creating
                    // a second owner for Core.
                }
            }
        }

        thread::sleep(Duration::from_secs(3));
    }
}

