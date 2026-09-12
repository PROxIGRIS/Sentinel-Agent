//! obylon-common: shared logging + IPC message schema for the broker and
//! core binaries. Deliberately has zero Windows-specific dependencies so
//! it's easy to unit-test and compile-check on any host.

use serde::{Deserialize, Serialize};
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

// =====================================================
// LOGGER
// =====================================================
// Deliberately hand-rolled instead of pulling in `tracing` — phase 1 is
// meant to be minimal, and the Python side already has a working log
// format (timestamp, level, component, message, key=value) that whoever
// is grepping `obylon.log` today already knows how to read. Match it
// rather than introduce a second log style.

pub struct FileLogger {
    file: Mutex<std::fs::File>,
}

impl FileLogger {
    /// Opens (creating if needed) the log file in append mode. Call once
    /// per process and keep the handle for the process lifetime — every
    /// write() call flushes, so there's no buffering window where a crash
    /// loses the last lines right before it (the exact failure mode that
    /// made the original Python broker undiagnosable).
    ///
    /// SECURITY/RELIABILITY FIX (2026-09): `path` is normally under
    /// ProgramData\Obylon\logs, which the installer locks to SYSTEM and
    /// Administrators only (installer/obylon-setup.iss). The process
    /// calling this — ObylonCore.exe — runs as whichever user is
    /// interactively logged in, which for the target deployment (school
    /// lab machines) is a non-admin student. `ensure_acls()` in the
    /// broker is supposed to widen that folder before Core is ever
    /// spawned, but this used to have no fallback at all: if the widen
    /// hadn't happened yet (or failed for any environmental reason —
    /// group policy, AV interference, a fresh install race), opening
    /// the primary path failed and the caller's `.expect(...)` took
    /// Core down before it ever reached the fast lane, hooks, or the
    /// Brain supervisor. Obylon.py's own setup_structlog() already
    /// anticipates exactly this ("fallback to file dir if ProgramData
    /// is locked") — this mirrors that instead of reintroducing the gap
    /// the Python side already closed.
    pub fn open(path: &Path) -> std::io::Result<Self> {
        match Self::try_open(path) {
            Ok(logger) => Ok(logger),
            Err(primary_err) => {
                if let Some(fallback) = fallback_log_path(path) {
                    if let Ok(logger) = Self::try_open(&fallback) {
                        return Ok(logger);
                    }
                }
                Err(primary_err)
            }
        }
    }

    fn try_open(path: &Path) -> std::io::Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new().create(true).append(true).open(path)?;
        Ok(Self {
            file: Mutex::new(file),
        })
    }

    pub fn log(&self, level: &str, component: &str, msg: &str, fields: &[(&str, &str)]) {
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let mut line = format!("[{ts}] {level:5} [{component}] {msg}");
        for (k, v) in fields {
            line.push_str(&format!(" {k}={v}"));
        }
        line.push('\n');

        if let Ok(mut f) = self.file.lock() {
            let _ = f.write_all(line.as_bytes());
            let _ = f.flush();
        }
    }

    pub fn info(&self, component: &str, msg: &str, fields: &[(&str, &str)]) {
        self.log("INFO", component, msg, fields);
    }
    pub fn warn(&self, component: &str, msg: &str, fields: &[(&str, &str)]) {
        self.log("WARN", component, msg, fields);
    }
    pub fn error(&self, component: &str, msg: &str, fields: &[(&str, &str)]) {
        self.log("ERROR", component, msg, fields);
    }
}

/// Builds a per-user fallback for a ProgramData log path, e.g.
/// `C:\ProgramData\Obylon\logs\core.log` becomes
/// `%LOCALAPPDATA%\Obylon\logs\core.log`. Uses manual string splitting
/// rather than `Path::file_name()`/`Path::join()`: this crate is built
/// and unit-tested on non-Windows hosts too (see module doc), but
/// `original` is always a Windows-style path regardless of build host,
/// and `std::path::Path`'s separator handling follows the *compile
/// target*, not the content — `file_name()`/`join()` would silently do
/// the wrong thing for a `\`-separated path when this crate happens to
/// be built for a non-Windows target. Plain string splitting/joining
/// sidesteps that entirely. Returns None if the file has no name
/// component or LOCALAPPDATA isn't set (e.g. running as a service
/// account with no profile), in which case the caller just surfaces the
/// original error.
fn fallback_log_path(original: &Path) -> Option<std::path::PathBuf> {
    let original_str = original.to_string_lossy();
    let file_name = original_str
        .rsplit(['\\', '/'])
        .next()
        .filter(|s| !s.is_empty())?;
    let base = std::env::var_os("LOCALAPPDATA")?;
    let base_str = base.to_string_lossy();
    let base_trimmed = base_str.trim_end_matches(['\\', '/']);
    Some(std::path::PathBuf::from(format!(
        "{base_trimmed}\\Obylon\\logs\\{file_name}"
    )))
}

// =====================================================
// IPC MESSAGE SCHEMA
// =====================================================
// Newline-delimited JSON over a named pipe (\\.\pipe\ObylonCore). One
// request, one response, connection closed after — simplest thing that
// works for phase 1. No protobuf/msgpack yet; that's a later-phase
// upgrade once the schema has proven itself (see the architecture doc).

/// What an overlay/freeze is *for* — lets Core render a security
/// violation differently from a purely educational classroom-focus
/// session, and lets it refuse a classroom-focus toggle that would
/// otherwise blindly clear an in-progress violation freeze. See
/// do_freeze()/do_unfreeze() in core/src/main.rs (verified bugs #2, #3).
#[derive(Debug, Serialize, Deserialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OverlayKind {
    ClassroomFocus,
    Violation,
    Watermark,
}

impl Default for OverlayKind {
    fn default() -> Self {
        OverlayKind::ClassroomFocus
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "cmd", rename_all = "snake_case")]
pub enum IpcRequest {
    Ping,
    BrainSecurityReady,
    Freeze {
        duration_secs: u64,
        // Defaults to ClassroomFocus so an older client that never sends
        // this field still round-trips instead of failing to parse.
        #[serde(default)]
        reason: OverlayKind,
    },
    // `None` means "unconditional" (e.g. an explicit admin/teacher-hotkey
    // unfreeze) — always clears the freeze regardless of why it was set.
    // `Some(reason)` is refused by Core if the workstation is actually
    // locked for a higher-priority reason than the caller believes it's
    // clearing (verified bug #3).
    Unfreeze {
        #[serde(default)]
        reason: Option<OverlayKind>,
    },
    ShowOverlay {
        #[serde(default)]
        kind: OverlayKind,
    },
    HideOverlay,
    /// Request an immediate local Windows shutdown. Core executes this in the
    /// interactive session so the control-plane acknowledgement is not held
    /// behind a Python shell subprocess or an artificial evidence grace wait.
    Shutdown,
    // Keylog, screenshot, and webcam all moved out of Python — Core
    // already owns the low-level keyboard hook (freeze enforcement), so
    // the ring buffer is just one more thing that same hook callback
    // feeds. Screenshot/webcam write a JPEG to ProgramData\Obylon\capture
    // and hand back the path rather than pushing image bytes through the
    // same small control-plane pipe as freeze/overlay commands.
    GetKeylogSnapshot,
    ClearKeylog,
    CaptureScreenshot,
    CaptureWebcam,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct IpcResponse {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub locked: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
}

impl IpcResponse {
    pub fn ok() -> Self {
        Self {
            ok: true,
            error: None,
            locked: None,
            text: None,
            path: None,
        }
    }
    pub fn ok_with_locked(locked: bool) -> Self {
        Self {
            ok: true,
            error: None,
            locked: Some(locked),
            text: None,
            path: None,
        }
    }
    pub fn ok_with_text(text: impl Into<String>) -> Self {
        Self {
            ok: true,
            error: None,
            locked: None,
            text: Some(text.into()),
            path: None,
        }
    }
    pub fn ok_with_path(path: impl Into<String>) -> Self {
        Self {
            ok: true,
            error: None,
            locked: None,
            text: None,
            path: Some(path.into()),
        }
    }
    pub fn err(msg: impl Into<String>) -> Self {
        Self {
            ok: false,
            error: Some(msg.into()),
            locked: None,
            text: None,
            path: None,
        }
    }

    /// Serialize as a single newline-terminated JSON line, matching what
    /// the Python `_core_ipc_call()` client reads.
    pub fn to_line(&self) -> String {
        let mut s = serde_json::to_string(self).unwrap_or_else(|_| "{\"ok\":false}".to_string());
        s.push('\n');
        s
    }
}

impl IpcRequest {
    pub fn parse_line(line: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(line.trim())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn freeze_request_round_trips() {
        let json = r#"{"cmd":"freeze","duration_secs":300}"#;
        let req = IpcRequest::parse_line(json).unwrap();
        match req {
            IpcRequest::Freeze { duration_secs, .. } => assert_eq!(duration_secs, 300),
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn freeze_reason_defaults_to_violation_when_omitted() {
        let json = r#"{"cmd":"freeze","duration_secs":30}"#;
        let req = IpcRequest::parse_line(json).unwrap();
        match req {
            IpcRequest::Freeze { reason, .. } => assert_eq!(reason, OverlayKind::Violation),
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn freeze_violation_reason_round_trips() {
        let json = r#"{"cmd":"freeze","duration_secs":30,"reason":"violation"}"#;
        let req = IpcRequest::parse_line(json).unwrap();
        match req {
            IpcRequest::Freeze { reason, .. } => assert_eq!(reason, OverlayKind::Violation),
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn unfreeze_without_reason_is_unconditional() {
        let json = r#"{"cmd":"unfreeze"}"#;
        let req = IpcRequest::parse_line(json).unwrap();
        match req {
            IpcRequest::Unfreeze { reason } => assert_eq!(reason, None),
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn unfreeze_with_classroom_focus_reason_round_trips() {
        let json = r#"{"cmd":"unfreeze","reason":"classroom_focus"}"#;
        let req = IpcRequest::parse_line(json).unwrap();
        match req {
            IpcRequest::Unfreeze { reason } => {
                assert_eq!(reason, Some(OverlayKind::ClassroomFocus))
            }
            _ => panic!("wrong variant"),
        }
    }

    #[test]
    fn ping_request_round_trips() {
        let json = r#"{"cmd":"ping"}"#;
        let req = IpcRequest::parse_line(json).unwrap();
        matches!(req, IpcRequest::Ping);
    }

    #[test]
    fn brain_security_ready_request_round_trips() {
        let json = r#"{"cmd":"brain_security_ready"}"#;
        let req = IpcRequest::parse_line(json).unwrap();
        assert!(matches!(req, IpcRequest::BrainSecurityReady));
    }

    #[test]
    fn python_style_matches() {
        // The Python client sends exactly this shape for freeze — this
        // test exists specifically to catch schema drift between the two
        // languages, which is the failure class the architecture doc
        // calls out (hardcoded service-role key, WS/HTTP race) as the
        // recurring bug pattern to guard against.
        let py_shape = r#"{"cmd": "freeze", "duration_secs": 3600}"#;
        assert!(IpcRequest::parse_line(py_shape).is_ok());

        let resp = IpcResponse::ok_with_locked(true);
        let line = resp.to_line();
        assert!(line.contains("\"ok\":true"));
        assert!(line.ends_with('\n'));
    }

    #[test]
    fn shutdown_request_round_trips() {
        let req = IpcRequest::parse_line(r#"{"cmd":"shutdown"}"#).unwrap();
        assert!(matches!(req, IpcRequest::Shutdown));
    }

    #[test]
    fn keylog_and_capture_requests_round_trip() {
        for shape in [
            r#"{"cmd":"get_keylog_snapshot"}"#,
            r#"{"cmd":"clear_keylog"}"#,
            r#"{"cmd":"capture_screenshot"}"#,
            r#"{"cmd":"capture_webcam"}"#,
        ] {
            assert!(
                IpcRequest::parse_line(shape).is_ok(),
                "failed to parse: {shape}"
            );
        }
    }

    #[test]
    fn text_and_path_responses_serialize_and_omit_unused_fields() {
        let text_resp = IpcResponse::ok_with_text("hello world");
        let line = text_resp.to_line();
        assert!(line.contains("\"text\":\"hello world\""));
        assert!(!line.contains("\"path\""));
        assert!(!line.contains("\"locked\""));

        let path_resp = IpcResponse::ok_with_path(r"C:\ProgramData\Obylon\capture\shot_1.jpg");
        let line = path_resp.to_line();
        assert!(line.contains("\"path\""));
        assert!(!line.contains("\"text\""));
    }

    #[test]
    fn fallback_log_path_uses_localappdata_and_keeps_file_name() {
        // Regression test for the fix where FileLogger::open() had no
        // fallback at all when ProgramData\Obylon\logs wasn't writable
        // by the interactive (non-admin) user Core actually runs as.
        // Both scenarios live in one test (rather than two `#[test]`
        // functions) because LOCALAPPDATA is process-global state and
        // Rust runs tests in parallel by default — two tests toggling
        // the same env var would be racy.
        let original = Path::new(r"C:\ProgramData\Obylon\logs\core.log");

        std::env::set_var("LOCALAPPDATA", r"C:\Users\student\AppData\Local");
        let fallback = fallback_log_path(original).expect("fallback path should resolve");
        assert_eq!(
            fallback,
            Path::new(r"C:\Users\student\AppData\Local\Obylon\logs\core.log")
        );

        std::env::remove_var("LOCALAPPDATA");
        assert!(fallback_log_path(original).is_none());
    }
}
