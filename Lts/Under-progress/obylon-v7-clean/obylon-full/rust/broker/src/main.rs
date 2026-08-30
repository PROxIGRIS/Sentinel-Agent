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
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use windows::core::{PCWSTR, PWSTR};
use windows::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE, HWND, LUID,
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
use windows::Win32::System::RemoteDesktop::{
    ProcessIdToSessionId, WTSGetActiveConsoleSessionId, WTSQueryUserToken,
};
use windows::Win32::System::Threading::{
    CreateMutexW, CreateProcessAsUserW, GetCurrentProcess, OpenProcess, OpenProcessToken,
    CREATE_NO_WINDOW, CREATE_UNICODE_ENVIRONMENT, PROCESS_INFORMATION,
    PROCESS_QUERY_LIMITED_INFORMATION, STARTF_USESHOWWINDOW, STARTUPINFOW,
};
use windows::Win32::UI::WindowsAndMessaging::SW_HIDE;

const LOG_PATH_ENV_FALLBACK: &str = r"C:\ProgramData\Obylon\logs\broker.log";
const CANDIDATE_SHELLS: &[&str] = &["explorer.exe", "sihost.exe", "ctfmon.exe", "userinit.exe"];

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

unsafe fn spawn_core_in_session(
    session_id: u32,
    core_exe: &str,
    logger: &FileLogger,
) -> Option<u32> {
    let (src_token, token_kind) = get_session_token(session_id, logger)?;

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
        return None;
    }

    let pid = proc_info.dwProcessId;
    let _ = CloseHandle(proc_info.hProcess);
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
    Some(pid)
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
    let mut spawned_for_session: Option<u32> = None;
    let mut last_pid: Option<u32> = None;

    loop {
        let session_id = unsafe { WTSGetActiveConsoleSessionId() };
        let no_session = session_id == 0xFFFFFFFF;

        let needs_spawn = !no_session
            && (spawned_for_session != Some(session_id)
                || last_pid.map_or(true, |pid| !process_is_alive(pid)));

        if needs_spawn {
            match unsafe { spawn_core_in_session(session_id, &core_exe, &logger) } {
                Some(pid) => {
                    spawned_for_session = Some(session_id);
                    last_pid = Some(pid);
                }
                None => {
                    // Expected during the boot race — WTSQueryUserToken can
                    // fail for the first several polls before winlogon has
                    // fully established the session. Retry, don't escalate.
                }
            }
        }

        thread::sleep(Duration::from_secs(3));
    }
}

fn process_is_alive(pid: u32) -> bool {
    unsafe {
        match OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
            Ok(h) => {
                let _ = CloseHandle(h);
                true
            }
            Err(_) => false,
        }
    }
}
