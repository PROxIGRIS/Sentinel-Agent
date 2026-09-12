//! ObylonCore.exe — spawned into the interactive session by ObylonBroker.exe.
//!
//! Owns everything that was previously a GIL-exposure risk in Python:
//! the low-level keyboard/mouse hook, the freeze/unfreeze state machine
//! with its own auto-expiry timer, and the classroom-focus overlay
//! (now a real Win32 layered window, not a per-cycle Tcl interpreter).
//! Also spawns the Python "brain" as its own child process and serves
//! its IPC requests over a named pipe.
//!
//! Design invariant worth restating: freeze auto-expiry lives entirely in
//! this process, independent of the IPC connection or Brain's own health.
//! If Brain crashes mid-freeze, Core still un-freezes on schedule — a
//! student's machine can never stay locked forever waiting on a dead
//! Python process.
#![windows_subsystem = "windows"]

use obylon_common::{FileLogger, IpcRequest, IpcResponse, OverlayKind};
use std::collections::VecDeque;
use std::env;
use std::io::BufWriter;
use std::path::PathBuf;

use std::sync::atomic::{AtomicU32, AtomicU64, AtomicU8, Ordering};
static HOOKS_ACCUM_US: AtomicU64 = AtomicU64::new(0);
static FAST_LANE_ACCUM_US: AtomicU64 = AtomicU64::new(0);

struct PerfTimer {
    accum: &'static AtomicU64,
    start: std::time::Instant,
}
impl PerfTimer {
    fn new(accum: &'static AtomicU64) -> Self {
        Self {
            accum,
            start: std::time::Instant::now(),
        }
    }
}
impl Drop for PerfTimer {
    fn drop(&mut self) {
        self.accum
            .fetch_add(self.start.elapsed().as_micros() as u64, Ordering::Relaxed);
    }
}

use std::sync::atomic::{AtomicBool, AtomicIsize};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use windows::core::{PCWSTR, PWSTR};
use windows::Win32::Foundation::{
    CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE, HWND, LPARAM, LRESULT, RECT, WPARAM,
};
use windows::Win32::Graphics::Gdi::{
    BeginPaint, BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, CreateFontW, CreateSolidBrush,
    DeleteDC, DeleteObject, DrawTextW, EndPaint, FillRect, GetDC, GetDIBits, ReleaseDC,
    SelectObject, SetBkMode, SetTextColor, BITMAPINFO, BITMAPINFOHEADER, BI_RGB,
    CLIP_DEFAULT_PRECIS, DEFAULT_CHARSET, DEFAULT_PITCH, DEFAULT_QUALITY, DIB_RGB_COLORS,
    DT_CENTER, DT_VCENTER, DT_WORDBREAK, FF_SWISS, FW_BOLD, OUT_DEFAULT_PRECIS, PAINTSTRUCT,
    SRCCOPY, TRANSPARENT,
};
use windows::Win32::Media::MediaFoundation::{
    IMFActivate, IMFMediaSource, IMFMediaType, IMFSample, IMFSourceReader, MFCreateAttributes,
    MFCreateMediaType, MFCreateSourceReaderFromMediaSource, MFEnumDeviceSources, MFMediaType_Video,
    MFShutdown, MFStartup, MFVideoFormat_RGB32, MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE,
    MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID, MF_MT_FRAME_SIZE, MF_MT_MAJOR_TYPE,
    MF_MT_SUBTYPE, MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, MF_SOURCE_READER_FIRST_VIDEO_STREAM,
    MF_VERSION,
};
use windows::Win32::NetworkManagement::IpHelper::{GetAdaptersAddresses, IP_ADAPTER_ADDRESSES_LH};
use windows::Win32::Networking::WinHttp::{
    WinHttpCloseHandle, WinHttpConnect, WinHttpOpen, WinHttpOpenRequest, WinHttpQueryHeaders,
    WinHttpReceiveResponse, WinHttpSendRequest, INTERNET_DEFAULT_HTTPS_PORT,
    WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_FLAG_SECURE, WINHTTP_QUERY_FLAG_NUMBER,
    WINHTTP_QUERY_STATUS_CODE,
};
use windows::Win32::Storage::FileSystem::{ReadFile, WriteFile};
use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
};
use windows::Win32::System::LibraryLoader::GetModuleHandleW;
use windows::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, GetNamedPipeClientProcessId,
    PIPE_READMODE_MESSAGE, PIPE_TYPE_MESSAGE, PIPE_WAIT,
};
use windows::Win32::System::Threading::{
    CreateMutexW, CreateProcessW, GetExitCodeProcess, SetThreadDescription, WaitForSingleObject,
    CREATE_NO_WINDOW, CREATE_UNICODE_ENVIRONMENT, INFINITE, PROCESS_CREATION_FLAGS,
    PROCESS_INFORMATION, STARTUPINFOW,
};
use windows::Win32::UI::Accessibility::{SetWinEventHook, HWINEVENTHOOK};
use windows::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::Input::KeyboardAndMouse::{
    GetKeyboardState, ToUnicode, VK_BACK, VK_RETURN, VK_SPACE,
};
use windows::Win32::UI::WindowsAndMessaging::{
    CallNextHookEx, CreateWindowExW, DefWindowProcW, DispatchMessageW, GetMessageW,
    GetSystemMetrics, GetWindowTextW, RegisterClassExW, SetLayeredWindowAttributes,
    SetWindowsHookExW, ShowWindow, TranslateMessage, UnhookWindowsHookEx, EVENT_SYSTEM_FOREGROUND,
    LWA_ALPHA, MSG, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN,
    SW_HIDE, SW_SHOW, WH_KEYBOARD_LL, WH_MOUSE_LL, WM_DESTROY, WM_KEYDOWN, WM_KEYUP,
    WM_LBUTTONDOWN, WM_MOUSEMOVE, WM_PAINT, WM_RBUTTONDOWN, WM_SYSKEYDOWN, WM_SYSKEYUP,
    WNDCLASSEXW, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_POPUP,
};

const PIPE_NAME: &str = r"\\.\pipe\ObylonCore";
const CLASS_NAME: &str = "ObylonClassroomOverlay";
const KEYLOG_MAX_TOKENS: usize = 1000;

static LOCKED: AtomicBool = AtomicBool::new(false);
static FREEZE_GENERATION: AtomicU64 = AtomicU64::new(0);
static HOOK_KBD: AtomicIsize = AtomicIsize::new(0);
static HOOK_MOUSE: AtomicIsize = AtomicIsize::new(0);
static OVERLAY_HWND: AtomicIsize = AtomicIsize::new(0);
static UI_THREAD_ID: AtomicU64 = AtomicU64::new(0);
static LOGGER: OnceLock<FileLogger> = OnceLock::new();
// PID of the Brain process this Core instance itself spawned — the pipe
// access-control check in handle_connection() requires an exact match
// against this, not just "any process owned by the same user." See the
// doc comment there for why a SID-based ACL alone isn't sufficient here.
static BRAIN_PID: AtomicU32 = AtomicU32::new(0);

// verified bug #2/#3: what the overlay currently looks like, and *why*
// the workstation is frozen (if it is). Kept separate from OVERLAY_HWND/
// LOCKED so a kind/reason change can never race against the hwnd or the
// lock flag itself. 0 = none/unset, 1 = ClassroomFocus, 2 = Violation.
static OVERLAY_KIND: AtomicU8 = AtomicU8::new(1);
static LOCK_REASON: AtomicU8 = AtomicU8::new(0);

// verified bug #7: desired vs. last-applied overlay visibility (plus the
// kind that was last actually painted). Only overlay_watcher_loop() ever
// calls ShowWindow — see show_overlay() and overlay_watcher_loop() below
// for why.
static OVERLAY_DESIRED: AtomicBool = AtomicBool::new(false);
static OVERLAY_APPLIED: AtomicBool = AtomicBool::new(false);
static OVERLAY_APPLIED_KIND: AtomicU8 = AtomicU8::new(0);

fn overlay_kind_to_u8(k: OverlayKind) -> u8 {
    match k {
        OverlayKind::ClassroomFocus => 1,
        OverlayKind::Violation => 2,
    }
}

fn u8_to_overlay_kind(v: u8) -> Option<OverlayKind> {
    match v {
        1 => Some(OverlayKind::ClassroomFocus),
        2 => Some(OverlayKind::Violation),
        _ => None,
    }
}

/// Changes what the overlay looks like the next time it's (re)painted.
/// A violation freeze must not keep showing the classroom-focus text/
/// color left over from an earlier show_overlay call (verified bug #2) —
/// overlay_watcher_loop() is what actually forces a repaint if the
/// overlay is already visible when the kind changes underneath it.
fn set_overlay_kind(kind: OverlayKind) {
    OVERLAY_KIND.store(overlay_kind_to_u8(kind), Ordering::SeqCst);
}

// Keylog ring buffer — fed directly by the same low-level keyboard hook
// that already exists for freeze enforcement. This replaces Python's
// separate pynput listener entirely, which was a second independent
// low-level keyboard hook running alongside this one; now there's just
// one hook doing both jobs.
static KEYLOG: OnceLock<Mutex<VecDeque<String>>> = OnceLock::new();
static CAPTURE_COUNTER: AtomicU64 = AtomicU64::new(0);

fn keylog() -> &'static Mutex<VecDeque<String>> {
    KEYLOG.get_or_init(|| Mutex::new(VecDeque::with_capacity(KEYLOG_MAX_TOKENS)))
}

fn logger() -> &'static FileLogger {
    LOGGER.get().expect("logger not initialized")
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// The full virtual desktop rectangle across every attached monitor, in
/// real physical pixels. Two bugs this fixes at once:
///   1. SM_CXSCREEN/SM_CYSCREEN only cover the PRIMARY monitor — a second
///      monitor is completely uncovered by both the freeze overlay and
///      screenshot capture.
///   2. Without declared DPI awareness, GetSystemMetrics returns
///      *virtualized* (scaled-down) values on any display running above
///      100% scaling — a 1920x1080 screen at 150% scaling reports as
///      1280x720, so BitBlt only ever captures a cropped corner. Fixed by
///      declaring Per-Monitor-V2 DPI awareness once at process start (see
///      main()) — SetProcessDpiAwarenessContext must be called before any
///      of these metrics are queried, which is why it happens first thing
///      in main(), before the UI thread (and therefore this function) is
///      even spawned.
/// SM_XVIRTUALSCREEN/SM_YVIRTUALSCREEN can be negative (a monitor
/// positioned above or left of the primary), so origin is not assumed
/// to be (0, 0) — both the overlay window position and BitBlt's source
/// origin need this real origin, not a hardcoded zero.
fn virtual_screen_rect() -> (i32, i32, i32, i32) {
    unsafe {
        let x = GetSystemMetrics(SM_XVIRTUALSCREEN);
        let y = GetSystemMetrics(SM_YVIRTUALSCREEN);
        let w = GetSystemMetrics(SM_CXVIRTUALSCREEN);
        let h = GetSystemMetrics(SM_CYVIRTUALSCREEN);
        (x, y, w, h)
    }
}

fn log_path() -> PathBuf {
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    PathBuf::from(base)
        .join("Obylon")
        .join("logs")
        .join("core.log")
}

// =====================================================
// LOW-LEVEL HOOKS
// =====================================================
// Same event set the Python WorkstationGuard blocked (WM_KEYDOWN/UP,
// WM_SYSKEYDOWN/UP for keyboard; WM_MOUSEMOVE, left/right button down for
// mouse) — inherited behavior, not a new decision. Both callbacks must
// run on the thread that installed the hook, hence the dedicated UI
// thread with its own message loop below.

unsafe extern "system" fn keyboard_hook_proc(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    if code >= 0 {
        let msg = wparam.0 as u32;

        if matches!(msg, WM_KEYDOWN | WM_SYSKEYDOWN) {
            #[repr(C)]
            struct KbdLlHookStruct {
                vk_code: u32,
                scan_code: u32,
                flags: u32,
                time: u32,
                dw_extra_info: usize,
            }
            let kbd = &*(lparam.0 as *const KbdLlHookStruct);
            record_keystroke(kbd.vk_code);
        }

        if LOCKED.load(Ordering::Relaxed) {
            return LRESULT(1); // swallow — do not call CallNextHookEx
        }
    }
    let hook =
        windows::Win32::UI::WindowsAndMessaging::HHOOK(HOOK_KBD.load(Ordering::Relaxed) as *mut _);
    windows::Win32::UI::WindowsAndMessaging::CallNextHookEx(Some(hook), code, wparam, lparam)
}

/// Translates a raw virtual-key code into the same token shapes the
/// Python KeylogBuffer used (single chars, " [ENTER] ", "[BS]", "[name]"
/// for other non-printable keys), using the real Win32 ToUnicode API so
/// Shift/CapsLock/keyboard-layout are respected the same way pynput's
/// internal translation was. Known simplification vs. pynput: dead-key
/// / IME composition sequences (ToUnicode returning a negative count)
/// are skipped rather than accumulated — same as "no visible character
/// yet" from the user's point of view, so low practical impact for the
/// threat-lexicon use case this buffer feeds.
fn vk_to_string(vk: u32) -> String {
    match vk {
        0x10 | 0xA0 | 0xA1 => "[shift]".to_string(),
        0x11 | 0xA2 | 0xA3 => "[ctrl]".to_string(),
        0x12 | 0xA4 | 0xA5 => "[alt]".to_string(),
        0x5B | 0x5C => "[cmd]".to_string(), // Windows key
        0x1B => "[esc]".to_string(),
        0x09 => "[tab]".to_string(),
        0x20 => " ".to_string(),
        0x0D => " [ENTER] ".to_string(),
        0x08 => "[BS]".to_string(),
        0x2E => "[del]".to_string(),
        0x25 => "[left]".to_string(),
        0x26 => "[up]".to_string(),
        0x27 => "[right]".to_string(),
        0x28 => "[down]".to_string(),
        0x14 => "[caps_lock]".to_string(),
        _ => format!("[vk{vk}]"),
    }
}

unsafe fn record_keystroke(vk_code: u32) {
    let token = match vk_code {
        x if x == VK_SPACE.0 as u32 => " ".to_string(),
        x if x == VK_RETURN.0 as u32 => " [ENTER] ".to_string(),
        x if x == VK_BACK.0 as u32 => "[BS]".to_string(),
        _ => {
            let mut state = [0u8; 256];
            if GetKeyboardState(&mut state).is_err() {
                return;
            }
            let mut buf = [0u16; 8];
            let scan_code = 0u32; // acceptable simplification for phase 1 — see note above
            let n = ToUnicode(vk_code, scan_code, Some(&state), &mut buf, 0);
            if n > 0 {
                String::from_utf16_lossy(&buf[..n as usize])
            } else if n < 0 {
                return; // dead key — no complete character yet, skip
            } else {
                vk_to_string(vk_code)
            }
        }
    };
    let mut buf = keylog().lock().unwrap();
    if buf.len() >= KEYLOG_MAX_TOKENS {
        buf.pop_front();
    }
    buf.push_back(token);
}

unsafe extern "system" fn mouse_hook_proc(code: i32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    if code >= 0 && LOCKED.load(Ordering::Relaxed) {
        return LRESULT(1);
    }
    let hook = windows::Win32::UI::WindowsAndMessaging::HHOOK(
        HOOK_MOUSE.load(Ordering::Relaxed) as *mut _
    );
    windows::Win32::UI::WindowsAndMessaging::CallNextHookEx(Some(hook), code, wparam, lparam)
}

// =====================================================
// OVERLAY WINDOW
// =====================================================

unsafe extern "system" fn wnd_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_PAINT => {
            let mut ps = PAINTSTRUCT::default();
            let hdc = BeginPaint(hwnd, &mut ps);

            let kind = u8_to_overlay_kind(OVERLAY_KIND.load(Ordering::SeqCst))
                .unwrap_or(OverlayKind::ClassroomFocus);
            let (color, label): (u32, &str) = match kind {
                OverlayKind::ClassroomFocus => (0x00_1C_1C_B9, "LOOK AT THE TEACHER"), // BGR: #B91C1C (Red)
                OverlayKind::Violation => (0x00_1C_1C_B9, "SECURITY VIOLATION — DEVICE LOCKED"), // BGR: #B91C1C (Red)
            };

            let brush = CreateSolidBrush(windows::Win32::Foundation::COLORREF(color));
            let mut rect = RECT::default();
            let _ = windows::Win32::UI::WindowsAndMessaging::GetClientRect(hwnd, &mut rect);
            FillRect(hdc, &rect, brush);
            let _ = windows::Win32::Graphics::Gdi::DeleteObject(brush.into());

            // Text was previously drawn with no font ever created — DrawTextW
            // just used whatever small default happened to already be
            // selected into the DC. Size relative to screen height (not a
            // fixed point size) so it stays proportionally large whether
            // this is a 1080p laptop panel or a 4K monitor — a fixed size
            // would look tiny on the latter. Negative height = character
            // height in logical units, the standard CreateFontW convention
            // for "give me exactly this tall, not this-plus-internal-leading."
            let client_height = (rect.bottom - rect.top).max(100);
            let font_height = -(client_height / 10); // Decreased from /6 to /10 to prevent overflow
            let font_name = wide("Segoe UI");
            let font = CreateFontW(
                font_height,
                0,
                0,
                0,
                FW_BOLD.0 as i32,
                0,
                0,
                0,
                DEFAULT_CHARSET,
                OUT_DEFAULT_PRECIS,
                CLIP_DEFAULT_PRECIS,
                DEFAULT_QUALITY,
                (DEFAULT_PITCH.0 as u32) | (FF_SWISS.0 as u32),
                PCWSTR(font_name.as_ptr()),
            );
            let old_font = SelectObject(hdc, font.into());

            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, windows::Win32::Foundation::COLORREF(0x00FFFFFF));
            let mut text: Vec<u16> = wide(label);

            // Calculate height with DT_CALCRECT
            let mut calc_rect = rect;
            let _ = windows::Win32::Graphics::Gdi::DrawTextW(
                hdc,
                &mut text,
                &mut calc_rect,
                DT_CENTER | DT_WORDBREAK | windows::Win32::Graphics::Gdi::DT_CALCRECT,
            );
            let text_height = calc_rect.bottom - calc_rect.top;
            let center_y = rect.top + (rect.bottom - rect.top) / 2;

            // Re-center vertically
            rect.top = center_y - (text_height / 2);
            rect.bottom = rect.top + text_height;

            let _ = windows::Win32::Graphics::Gdi::DrawTextW(
                hdc,
                &mut text,
                &mut rect,
                DT_CENTER | DT_WORDBREAK,
            );

            SelectObject(hdc, old_font);
            let _ = windows::Win32::Graphics::Gdi::DeleteObject(font.into());

            let _ = EndPaint(hwnd, &ps);
            LRESULT(0)
        }
        WM_DESTROY => LRESULT(0), // never actually torn down in phase 1 — hide/show only
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

/// Owns the hook installation, the overlay window, and the message pump
/// for both — Windows requires low-level hooks to be pumped on the
/// thread that installed them, and a window needs a pump too, so one
/// thread does both jobs for the whole process lifetime.
fn ui_thread_main() {
    unsafe {
        let _ = SetThreadDescription(
            windows::Win32::System::Threading::GetCurrentThread(),
            windows::core::w!("ui_thread"),
        );
    }

    unsafe {
        let hinstance = GetModuleHandleW(PCWSTR::null()).unwrap_or_default();

        let class_name = wide(CLASS_NAME);
        let wc = WNDCLASSEXW {
            cbSize: std::mem::size_of::<WNDCLASSEXW>() as u32,
            lpfnWndProc: Some(wnd_proc),
            hInstance: hinstance.into(),
            lpszClassName: PCWSTR(class_name.as_ptr()),
            ..Default::default()
        };
        RegisterClassExW(&wc);

        let (vx, vy, vw, vh) = virtual_screen_rect();

        let hwnd = CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
            PCWSTR(class_name.as_ptr()),
            PCWSTR(wide("Obylon Classroom Focus").as_ptr()),
            WS_POPUP,
            vx,
            vy,
            vw,
            vh,
            None,
            None,
            Some(hinstance.into()),
            None,
        )
        .unwrap_or_default();

        let _ = SetLayeredWindowAttributes(
            hwnd,
            windows::Win32::Foundation::COLORREF(0),
            (0.85 * 255.0) as u8,
            LWA_ALPHA,
        );

        OVERLAY_HWND.store(hwnd.0 as isize, Ordering::SeqCst);

        let kbd = SetWindowsHookExW(WH_KEYBOARD_LL, Some(keyboard_hook_proc), None, 0);
        let mouse = SetWindowsHookExW(WH_MOUSE_LL, Some(mouse_hook_proc), None, 0);
        match (&kbd, &mouse) {
            (Ok(k), Ok(m)) => {
                HOOK_KBD.store(k.0 as isize, Ordering::SeqCst);
                HOOK_MOUSE.store(m.0 as isize, Ordering::SeqCst);
                logger().info("enforcement", "hooks installed", &[]);
            }
            _ => {
                logger().error(
                    "enforcement",
                    "SetWindowsHookExW failed — freeze will not work",
                    &[("error", &format!("{:?}", GetLastError()))],
                );
            }
        }

        UI_THREAD_ID.store(
            windows::Win32::System::Threading::GetCurrentThreadId() as u64,
            Ordering::SeqCst,
        );

        // Fast lane: foreground-window changes are delivered as WinEvents
        // to this same thread's message pump, right alongside the
        // low-level hooks above — event-driven, no separate poll timer.
        let _win_event_hook = SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            None,
            Some(win_event_proc),
            0,
            0,
            0x0000,
        );
        if _win_event_hook.is_invalid() {
            logger().warn(
                "fastlane",
                "SetWinEventHook failed — foreground-window fast-lane checks disabled",
                &[],
            );
        }

        let mut msg = MSG::default();
        loop {
            let ret = GetMessageW(&mut msg, None, 0, 0).0;
            if ret <= 0 {
                // 0 = WM_QUIT, -1 = error. Either way, stop pumping —
                // treating -1 as "truthy" (a plain bool conversion would
                // do this) would spin forever on a real error instead of
                // exiting cleanly.
                break;
            }
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }

        if let Ok(k) = kbd {
            let _ = UnhookWindowsHookEx(k);
        }
        if let Ok(m) = mouse {
            let _ = UnhookWindowsHookEx(m);
        }
    }
}

/// Requests a new overlay visibility state — does NOT call ShowWindow
/// itself. See overlay_watcher_loop() for why (verified bug #7: calling
/// ShowWindow directly, from whichever thread happened to handle the IPC
/// request, flooded ui_thread_main's message queue under rapid show/hide
/// spam and starved the keyboard/mouse hooks that share that thread,
/// which the OS then silently unhooked as "unresponsive").
fn show_overlay(show: bool) {
    OVERLAY_DESIRED.store(show, Ordering::SeqCst);
}

/// The only code path allowed to call ShowWindow on the overlay. Runs on
/// its own dedicated thread (spawned once from main()) and polls rather
/// than reacting to every request, so any number of rapid show_overlay()/
/// hide_overlay() calls — from one caller or many concurrent IPC
/// connections — collapse into at most one real Win32 call every
/// OVERLAY_POLL_MS, fully decoupling caller flood rate from actual
/// window-message traffic on ui_thread_main (verified bug #7).
const OVERLAY_POLL_MS: u64 = 50;
fn overlay_watcher_loop() {
    unsafe {
        let _ = SetThreadDescription(
            windows::Win32::System::Threading::GetCurrentThread(),
            windows::core::w!("overlay_watcher"),
        );
    }
    loop {
        thread::sleep(Duration::from_millis(OVERLAY_POLL_MS));

        let desired_visible = OVERLAY_DESIRED.load(Ordering::SeqCst);
        let desired_kind = OVERLAY_KIND.load(Ordering::SeqCst);
        let was_visible = OVERLAY_APPLIED.load(Ordering::SeqCst);
        let was_kind = OVERLAY_APPLIED_KIND.load(Ordering::SeqCst);

        let visibility_changed = was_visible != desired_visible;
        // A kind change only needs a repaint if the overlay is actually
        // on screen right now — if it's hidden, wnd_proc will just pick
        // up the current OVERLAY_KIND next time something shows it.
        let kind_changed_while_visible = desired_visible && was_kind != desired_kind;

        if visibility_changed || kind_changed_while_visible {
            let raw = OVERLAY_HWND.load(Ordering::SeqCst);
            if raw != 0 {
                let hwnd = HWND(raw as *mut _);
                unsafe {
                    if kind_changed_while_visible && was_visible {
                        // Force a full repaint of the new kind's color/
                        // text by cycling visibility. This reuses the
                        // exact ShowWindow calls already proven to work
                        // in this file, rather than reaching for a GDI
                        // invalidate call whose exact binding signature
                        // in the pinned windows-rs version isn't worth
                        // guessing at here.
                        let _ = ShowWindow(hwnd, SW_HIDE);
                    }
                    let _ = ShowWindow(hwnd, if desired_visible { SW_SHOW } else { SW_HIDE });
                }
            }
            OVERLAY_APPLIED.store(desired_visible, Ordering::SeqCst);
            OVERLAY_APPLIED_KIND.store(desired_kind, Ordering::SeqCst);
        }
    }
}

// =====================================================
// FREEZE STATE MACHINE — fail-safe, independent of IPC/Brain health
// =====================================================

fn do_freeze(duration_secs: u64, reason: OverlayKind) {
    let gen = FREEZE_GENERATION.fetch_add(1, Ordering::SeqCst) + 1;
    LOCKED.store(true, Ordering::SeqCst);
    LOCK_REASON.store(overlay_kind_to_u8(reason), Ordering::SeqCst);
    logger().warn(
        "enforcement",
        "Tactical Monolith Deployed - Input Severed",
        &[
            ("duration", &duration_secs.to_string()),
            ("reason", &format!("{:?}", reason)),
        ],
    );

    // Freeze is silent by design — no overlay. The overlay is reserved
    // exclusively for an explicit classroom_focus session (ShowOverlay/
    // HideOverlay in the IPC dispatch below, sent by Python's
    // show_classroom_focus_overlay()/hide_classroom_focus_overlay()).
    // `reason` is still recorded via LOCK_REASON above — that's what lets
    // do_unfreeze() below refuse a classroom-focus toggle that would
    // otherwise clear an in-progress violation penalty early. It just no
    // longer implies anything about what's on screen.

    if duration_secs > 0 {
        thread::spawn(move || {
            thread::sleep(Duration::from_secs(duration_secs));
            // Only auto-unfreeze if nothing superseded this exact freeze
            // request (a newer freeze or an explicit unfreeze bumps the
            // generation). This is what makes expiry correct even if
            // Brain never sends "unfreeze" at all, or crashes outright.
            if FREEZE_GENERATION.load(Ordering::SeqCst) == gen {
                LOCKED.store(false, Ordering::SeqCst);
                LOCK_REASON.store(0, Ordering::SeqCst);
                logger().info("enforcement", "Workstation Unlocked (auto-expiry)", &[]);
            }
        });
    }
}

/// `requested_reason` is the caller's belief about *why* it's unfreezing
/// (Python sends ClassroomFocus when the dashboard toggles classroom
/// focus off, and None for an explicit admin/teacher-hotkey unfreeze —
/// see WorkstationGuard.disengage_freeze() in Obylon.py). If the
/// workstation is actually locked for a higher-priority reason than the
/// caller believes it's clearing — specifically, a security Violation
/// still in progress when a classroom-focus toggle asks to unfreeze —
/// the request is refused and the freeze stays in effect. This is what
/// stops a classroom-focus toggle from blindly clearing an in-progress
/// fast-lane penalty out from under a student (verified bug #3). Returns
/// true if the workstation ends up unlocked.
fn do_unfreeze(requested_reason: Option<OverlayKind>) -> bool {
    let current = u8_to_overlay_kind(LOCK_REASON.load(Ordering::SeqCst));
    if requested_reason == Some(OverlayKind::ClassroomFocus)
        && current == Some(OverlayKind::Violation)
    {
        logger().warn(
            "enforcement",
            "Unfreeze refused — classroom-focus toggle cannot clear an active violation freeze",
            &[],
        );
        return false;
    }
    FREEZE_GENERATION.fetch_add(1, Ordering::SeqCst);
    LOCKED.store(false, Ordering::SeqCst);
    LOCK_REASON.store(0, Ordering::SeqCst);
    logger().info("enforcement", "Workstation Unlocked", &[]);
    true
}

// =====================================================
// CAPTURE — screenshot + webcam
// =====================================================
// Both write a JPEG to disk and hand back the *path*, not the bytes —
// this is the data-plane vs. control-plane split from the architecture
// doc: a 1080p frame is megabytes, and shoving that through the same
// small pipe as freeze/overlay commands would make the control plane
// share fate with capture I/O. Python reads the file and deletes it.

fn capture_dir() -> PathBuf {
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    let dir = PathBuf::from(base).join("Obylon").join("capture");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

fn next_capture_path(prefix: &str) -> PathBuf {
    let n = CAPTURE_COUNTER.fetch_add(1, Ordering::SeqCst);
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    capture_dir().join(format!("{prefix}_{ts}_{n}.jpg"))
}

fn write_rgb_jpeg(width: u32, height: u32, rgb: Vec<u8>, prefix: &str) -> Result<PathBuf, String> {
    let img: image::RgbImage = image::ImageBuffer::from_raw(width, height, rgb)
        .ok_or_else(|| "pixel buffer size mismatch".to_string())?;
    let path = next_capture_path(prefix);
    let file = std::fs::File::create(&path).map_err(|e| e.to_string())?;
    let mut writer = BufWriter::new(file);
    let mut encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut writer, 75);
    encoder
        .encode(&img, width, height, image::ColorType::Rgb8)
        .map_err(|e| e.to_string())?;
    Ok(path)
}

/// Classic GDI BitBlt screen capture — the same approach every native
/// Windows screenshot tool uses. Captures the full virtual desktop across
/// every monitor, at true physical-pixel resolution (see
/// virtual_screen_rect() for why both of those require care).
///
/// GDI cleanup here is deliberate and complete (SelectObject back to the
/// old bitmap before deleting, DeleteObject, DeleteDC, ReleaseDC, in that
/// order) — this runs far more often than the freeze/overlay cycle that
/// caused the earlier GDI-leak problem, so being sloppy here would be
/// worse, not better.
fn capture_screenshot_to_file() -> Result<PathBuf, String> {
    unsafe {
        let screen_dc = GetDC(None);
        if screen_dc.is_invalid() {
            return Err("GetDC(NULL) returned an invalid DC".to_string());
        }

        let (vx, vy, width, height) = virtual_screen_rect();

        let mem_dc = CreateCompatibleDC(Some(screen_dc));
        let bitmap = CreateCompatibleBitmap(screen_dc, width, height);
        let old_obj = SelectObject(mem_dc, bitmap.into());

        // Source origin is the virtual screen's real origin (can be
        // negative if a monitor sits above/left of the primary) — NOT
        // always (0, 0) once a second monitor is in the picture.
        let blit_ok = BitBlt(
            mem_dc,
            0,
            0,
            width,
            height,
            Some(screen_dc),
            vx,
            vy,
            SRCCOPY,
        )
        .is_ok();

        let mut bmi = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: width,
                biHeight: -height, // negative = top-down DIB rows, so no manual row-flip needed
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB.0 as u32,
                ..Default::default()
            },
            ..Default::default()
        };

        let mut pixels = vec![0u8; (width as usize) * (height as usize) * 4];
        let lines = GetDIBits(
            mem_dc,
            bitmap,
            0,
            height as u32,
            Some(pixels.as_mut_ptr() as *mut _),
            &mut bmi,
            DIB_RGB_COLORS,
        );

        // Cleanup before anything else, success or not.
        SelectObject(mem_dc, old_obj);
        let _ = DeleteObject(bitmap.into());
        let _ = DeleteDC(mem_dc);
        ReleaseDC(None, screen_dc);

        if !blit_ok || lines == 0 {
            return Err("BitBlt/GetDIBits failed".to_string());
        }

        // Windows DIBs are BGRA; drop the alpha byte and swap to RGB for
        // the `image` crate.
        let mut rgb = Vec::with_capacity((width as usize) * (height as usize) * 3);
        for chunk in pixels.chunks_exact(4) {
            rgb.push(chunk[2]);
            rgb.push(chunk[1]);
            rgb.push(chunk[0]);
        }

        write_rgb_jpeg(width as u32, height as u32, rgb, "shot")
    }
}

/// Webcam capture via Media Foundation's synchronous IMFSourceReader —
/// the modern replacement for the DirectShow API that Python's
/// `cv2.VideoCapture(0, cv2.CAP_DSHOW)` was using.
///
/// HIGHEST-RISK BLOCK IN THIS FILE. COM lifetime, device enumeration,
/// and format negotiation are all real complexity. MF_SOURCE_READER_
/// ENABLE_VIDEO_PROCESSING is set below specifically because most
/// webcams don't output RGB32 natively (NV12/MJPEG is far more common) —
/// that flag tells the source reader to insert Media Foundation's own
/// color-conversion MFT automatically. If SetCurrentMediaType still fails
/// with this enabled, that points to a deeper device/driver issue, not
/// the plain format mismatch this flag already covers. Treat this
/// function as the thing to validate first and separately from
/// screenshot/keylog, which are far more likely to just work.
fn capture_webcam_to_file() -> Result<PathBuf, String> {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        MFStartup(MF_VERSION, 0).map_err(|e| format!("MFStartup failed: {e:?}"))?;

        let result = capture_webcam_inner();

        let _ = MFShutdown();
        result
    }
}

unsafe fn capture_webcam_inner() -> Result<PathBuf, String> {
    let mut attrs_ptr = None;
    MFCreateAttributes(&mut attrs_ptr, 1).map_err(|e| format!("MFCreateAttributes: {e:?}"))?;
    let attrs = attrs_ptr.unwrap();
    attrs
        .SetGUID(
            &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE,
            &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID,
        )
        .map_err(|e| format!("SetGUID(source type): {e:?}"))?;

    let mut devices_ptr: *mut Option<IMFActivate> = std::ptr::null_mut();
    let mut count = 0;
    MFEnumDeviceSources(&attrs, &mut devices_ptr, &mut count)
        .map_err(|e| format!("MFEnumDeviceSources: {e:?}"))?;
    if count == 0 || devices_ptr.is_null() {
        return Err("no webcam devices found".to_string());
    }
    let devices = std::slice::from_raw_parts(devices_ptr, count as usize);
    let activate: &IMFActivate = devices[0]
        .as_ref()
        .ok_or_else(|| "first device activate handle is null".to_string())?;

    let source: IMFMediaSource = activate
        .ActivateObject()
        .map_err(|e| format!("ActivateObject: {e:?}"))?;

    // MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING tells the source reader to
    // insert Media Foundation's built-in color-conversion MFT when the
    // camera's native output format doesn't match what SetCurrentMediaType
    // below asks for. Without this, requesting RGB32 directly only works
    // on cameras that happen to output RGB32 natively — most consumer
    // webcams deliver NV12, YUY2, or MJPEG instead, and SetCurrentMediaType
    // fails outright (MF_E_INVALIDMEDIATYPE) rather than converting.
    let mut reader_attrs_ptr = None;
    MFCreateAttributes(&mut reader_attrs_ptr, 1)
        .map_err(|e| format!("MFCreateAttributes(reader): {e:?}"))?;
    let reader_attrs = reader_attrs_ptr.unwrap();
    reader_attrs
        .SetUINT32(&MF_SOURCE_READER_ENABLE_VIDEO_PROCESSING, 1)
        .map_err(|e| format!("SetUINT32(video processing): {e:?}"))?;
    let reader: IMFSourceReader = MFCreateSourceReaderFromMediaSource(&source, Some(&reader_attrs))
        .map_err(|e| format!("MFCreateSourceReaderFromMediaSource: {e:?}"))?;

    let out_type: IMFMediaType =
        MFCreateMediaType().map_err(|e| format!("MFCreateMediaType: {e:?}"))?;
    out_type
        .SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Video)
        .map_err(|e| format!("SetGUID(major): {e:?}"))?;
    out_type
        .SetGUID(&MF_MT_SUBTYPE, &MFVideoFormat_RGB32)
        .map_err(|e| format!("SetGUID(subtype): {e:?}"))?;
    reader
        .SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32, None, &out_type)
        .map_err(|e| format!("SetCurrentMediaType: {e:?} — video processing was enabled above, so this now indicates a deeper device/driver problem, not a plain format mismatch"))?;

    let size_u64 = out_type
        .GetUINT64(&MF_MT_FRAME_SIZE)
        .map_err(|e| format!("GetUINT64(MF_MT_FRAME_SIZE): {e:?}"))?;
    let width = (size_u64 >> 32) as u32;
    let height = (size_u64 & 0xFFFFFFFF) as u32;

    // First couple of frames off a freshly-opened device are frequently
    // black/garbage while auto-exposure settles — read a few, keep the
    // last usable one.
    let mut last_frame: Option<PathBuf> = None;
    for _ in 0..3 {
        let mut stream_index = 0u32;
        let mut flags = 0u32;
        let mut timestamp: i64 = 0;
        let mut sample: Option<IMFSample> = None;
        let read_ok = reader.ReadSample(
            MF_SOURCE_READER_FIRST_VIDEO_STREAM.0 as u32,
            0,
            Some(&mut stream_index),
            Some(&mut flags),
            Some(&mut timestamp),
            Some(&mut sample),
        );
        if read_ok.is_err() {
            continue;
        }
        if let Some(sample) = sample {
            if let Ok(path) = sample_to_jpeg(&sample, width, height) {
                last_frame = Some(path);
            }
        }
    }

    last_frame.ok_or_else(|| "no usable frame captured after 3 reads".to_string())
}

unsafe fn sample_to_jpeg(sample: &IMFSample, width: u32, height: u32) -> Result<PathBuf, String> {
    let buffer = sample
        .ConvertToContiguousBuffer()
        .map_err(|e| format!("ConvertToContiguousBuffer: {e:?}"))?;

    let mut data_ptr: *mut u8 = std::ptr::null_mut();
    let mut cur_len: u32 = 0;
    buffer
        .Lock(&mut data_ptr, None, Some(&mut cur_len))
        .map_err(|e| format!("buffer.Lock: {e:?}"))?;

    let raw = std::slice::from_raw_parts(data_ptr, cur_len as usize);
    let stride = (width as usize) * 4;

    // RGB32 from Media Foundation is BGRA, bottom-up per scanline (same
    // orientation as a classic DIB) — flip rows and drop alpha same as
    // the screenshot path.
    let mut rgb = vec![0u8; (width as usize) * (height as usize) * 3];
    for y in 0..height as usize {
        let row_start = (height as usize - 1 - y) * stride;
        if row_start + stride > raw.len() {
            break; // defensive — a truncated buffer shouldn't panic the hook thread's caller
        }
        let src_row = &raw[row_start..row_start + stride];
        for x in 0..width as usize {
            let px = &src_row[x * 4..x * 4 + 4];
            let dst = (y * width as usize + x) * 3;
            rgb[dst] = px[2];
            rgb[dst + 1] = px[1];
            rgb[dst + 2] = px[0];
        }
    }

    let _ = buffer.Unlock();

    write_rgb_jpeg(width, height, rgb, "cam")
}

// =====================================================
// SHARED EVENTS QUEUE (Core -> Python, file-based, durable)
// =====================================================
// A plain append-only JSON-lines file, not a new IPC command. Python
// already has its own durable local queue (vault_enqueue, SQLite-backed)
// for offline-resilient reporting to Supabase — this file is just the
// handoff point between "Core detected or acted on something" and
// "Python's existing, already-proven sync pipeline picks it up." Core
// never holds this file open — every write is its own open-append-close,
// specifically so Python can safely rename-then-drain it (the standard
// safe log-rotation consumer pattern) without any locking coordination
// between the two processes.
fn events_path() -> PathBuf {
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    let dir = PathBuf::from(base).join("Obylon").join("events");
    let _ = std::fs::create_dir_all(&dir);
    dir.join("events.jsonl")
}

fn append_event(event: &serde_json::Value) {
    use std::io::Write as _;
    let line = format!("{event}\n");
    match std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(events_path())
    {
        Ok(mut f) => {
            let _ = f.write_all(line.as_bytes());
        }
        Err(e) => logger().error(
            "events",
            "failed to append event",
            &[("error", &e.to_string())],
        ),
    }
}

// =====================================================
// FAST LANE — local detection + immediate action, no Python required
// =====================================================
// The whole point: ObylonCore.exe is fully armed within ~100ms of being
// spawned. The Python brain (interpreter start + heavy imports + a
// network handshake) can take on the order of 10+ seconds to reach the
// same "armed" state. This closes that gap for a deliberately NARROW
// subset of signals cheap enough to check without the full NLP/threat-
// scoring pipeline: exact process names, exact window-title substrings,
// and tether-adapter hints. It is a reflex, not a replacement for that
// pipeline — Python's own scan_loop/action_loop keep running once they're
// up and remain the actual policy authority.
#[derive(serde::Deserialize, Default, Clone)]
struct FastLaneRules {
    #[serde(default)]
    banned_process_names: Vec<String>,
    #[serde(default)]
    banned_window_title_keywords: Vec<String>,
    #[serde(default)]
    tether_adapter_hints: Vec<String>,
}

fn fastlane_rules_path() -> PathBuf {
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    PathBuf::from(base)
        .join("Obylon")
        .join("fastlane_rules.json")
}

/// Built-in floor so a brand-new install — Python has never once
/// successfully synced remote config — still has *something* to check
/// against instead of an empty, always-silent fast lane. Python
/// overwrites this file with the real, policy-derived list as soon as it
/// has one (see write_fastlane_rules() in Obylon.py); this is only ever
/// the fallback for the gap before that first sync.
fn default_fastlane_rules() -> FastLaneRules {
    FastLaneRules {
        banned_process_names: vec![
            "cheatengine-x86_64.exe".to_string(),
            "cheatengine-x86_64-sse4-avx2.exe".to_string(),
        ],
        banned_window_title_keywords: vec!["cheat engine".to_string()],
        tether_adapter_hints: vec![
            "cellular".to_string(),
            "mobile".to_string(),
            "rndis".to_string(),
            "android".to_string(),
            "iphone".to_string(),
            "hotspot".to_string(),
            "tether".to_string(),
        ],
    }
}

fn load_fastlane_rules() -> FastLaneRules {
    match std::fs::read_to_string(fastlane_rules_path()) {
        Ok(s) => serde_json::from_str(&s).unwrap_or_else(|_| default_fastlane_rules()),
        Err(_) => default_fastlane_rules(),
    }
}

static FASTLANE_RULES: OnceLock<Mutex<FastLaneRules>> = OnceLock::new();

fn fastlane_rules() -> &'static Mutex<FastLaneRules> {
    FASTLANE_RULES.get_or_init(|| Mutex::new(load_fastlane_rules()))
}

fn refresh_fastlane_rules() {
    *fastlane_rules().lock().unwrap() = load_fastlane_rules();
}

/// The actual fast-lane response: freeze, grab a screenshot, durably
/// queue the violation, then best-effort report it immediately. No
/// overlay — freeze is a silent penalty now; the overlay is reserved
/// exclusively for an explicit classroom_focus command (see ShowOverlay/
/// HideOverlay in the IPC dispatch below). do_freeze() still records
/// OverlayKind::Violation as the freeze *reason* even though nothing
/// visual comes of it — that bookkeeping is what stops a classroom-focus
/// toggle from accidentally clearing this penalty early (see do_unfreeze).
fn trigger_fastlane_violation(kind: &str, detail: &str) {
    logger().warn(
        "fastlane",
        "fast-lane violation detected",
        &[("kind", kind), ("detail", detail)],
    );

    do_freeze(30, OverlayKind::Violation); // short, safe default — Python's own policy can extend/adjust once it's up

    let screenshot_path = capture_screenshot_to_file()
        .ok()
        .map(|p| p.to_string_lossy().to_string());
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);

    let event = serde_json::json!({
        "type": "fast_lane_violation",
        "kind": kind,
        "detail": detail,
        "timestamp": ts,
        "screenshot_path": screenshot_path,
        "action_taken": "freeze",
    });
    append_event(&event);

    // Best-effort only — the append above already made this durable
    // regardless of whether this succeeds. This exists purely to shave
    // reporting latency down from "whenever Python next drains the
    // events file" to "as close to immediate as the network allows."
    try_direct_report(&event);
}

// =====================================================
// IDENTITY BEACON + BEST-EFFORT DIRECT REPORTING
// =====================================================
// Plaintext JSON, written by Python once it has a confirmed Supabase
// identity — deliberately NOT the encrypted vault. Everything in it is
// already non-secret: the Supabase anon key is meant to be publicly
// embeddable (it's compiled directly into obylonc's source too), and a
// workstation UUID isn't sensitive on its own. Reading the real vault
// here instead would mean duplicating Python's DPAPI + activation-token
// parsing logic in Rust — exactly the kind of two-copies-drift the
// architecture doc warns about — for a component whose only job is a
// latency optimization on top of a path that's already durable without it.
#[derive(serde::Deserialize, Default, Clone)]
struct IdentityBeacon {
    workstation_id: Option<String>,
    supabase_url: Option<String>,
    supabase_anon_key: Option<String>,
}

fn identity_beacon_path() -> PathBuf {
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    PathBuf::from(base)
        .join("Obylon")
        .join("identity_beacon.json")
}

fn load_identity_beacon() -> Option<IdentityBeacon> {
    let s = std::fs::read_to_string(identity_beacon_path()).ok()?;
    serde_json::from_str(&s).ok()
}

fn try_direct_report(event: &serde_json::Value) {
    let beacon = match load_identity_beacon() {
        Some(b)
            if b.workstation_id.is_some()
                && b.supabase_url.is_some()
                && b.supabase_anon_key.is_some() =>
        {
            b
        }
        _ => {
            logger().warn(
                "fastlane",
                "no identity beacon yet — relying on the events queue instead",
                &[],
            );
            return;
        }
    };

    let mut body = event.clone();
    body["workstation_id"] = serde_json::Value::String(beacon.workstation_id.clone().unwrap());

    let url = format!(
        "{}/rest/v1/fastlane_events",
        beacon.supabase_url.unwrap().trim_end_matches('/')
    );
    let anon_key = beacon.supabase_anon_key.unwrap();

    match winhttp_post_json(&url, &anon_key, &body.to_string()) {
        Ok(status) if (200..300).contains(&status) => {
            logger().info(
                "fastlane",
                "direct report delivered",
                &[("status", &status.to_string())],
            );
        }
        Ok(status) => {
            logger().warn(
                "fastlane",
                "direct report rejected — will still reach the server via the events queue",
                &[("status", &status.to_string())],
            );
        }
        Err(e) => {
            logger().warn("fastlane", "direct report failed (offline?) — will still reach the server via the events queue", &[("error", &e)]);
        }
    }
}

/// Minimal synchronous WinHTTP POST. HIGHEST-RISK BLOCK ALONGSIDE MEDIA
/// FOUNDATION — WinHTTP's function signatures in windows-rs are the least
/// familiar surface in this file and were not compiler-verified. The
/// design choice itself is deliberate though: WinHTTP over a full HTTP+TLS
/// crate, because Schannel (Windows' own TLS stack) comes for free with
/// it — no new crate, no new dependency tree, for a single best-effort
/// POST a handful of times per session. If this needs fixing, the shape
/// of the fix is almost certainly argument-type corrections, not a
/// different approach.
fn winhttp_post_json(url: &str, anon_key: &str, body: &str) -> Result<u32, String> {
    let stripped = url
        .strip_prefix("https://")
        .ok_or("only https URLs are supported")?;
    let (host, path) = stripped.split_once('/').unwrap_or((stripped, ""));
    let path = format!("/{path}");

    unsafe {
        let session = WinHttpOpen(
            PCWSTR(wide("Obylon-FastLane/1.0").as_ptr()),
            WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
            PCWSTR::null(),
            PCWSTR::null(),
            0,
        );
        if session.is_null() {
            return Err("WinHttpOpen failed".to_string());
        }

        let host_w = wide(host);
        let connect = WinHttpConnect(
            session,
            PCWSTR(host_w.as_ptr()),
            INTERNET_DEFAULT_HTTPS_PORT as u16,
            0,
        );
        if connect.is_null() {
            let _ = WinHttpCloseHandle(session);
            return Err("WinHttpConnect failed".to_string());
        }

        let path_w = wide(&path);
        let verb_w = wide("POST");
        let accept_types: [*const u16; 2] = [std::ptr::null(), std::ptr::null()];
        let request = WinHttpOpenRequest(
            connect,
            PCWSTR(verb_w.as_ptr()),
            PCWSTR(path_w.as_ptr()),
            PCWSTR::null(),
            PCWSTR::null(),
            accept_types.as_ptr() as *const PCWSTR,
            WINHTTP_FLAG_SECURE,
        );
        if request.is_null() {
            let _ = WinHttpCloseHandle(connect);
            let _ = WinHttpCloseHandle(session);
            return Err("WinHttpOpenRequest failed".to_string());
        }

        let headers = format!(
            "Content-Type: application/json\r\napikey: {anon_key}\r\nAuthorization: Bearer {anon_key}\r\nPrefer: return=minimal\r\n"
        );
        let headers_w = wide(&headers);
        let body_bytes = body.as_bytes();

        let sent = WinHttpSendRequest(
            request,
            Some(std::slice::from_raw_parts(
                headers_w.as_ptr(),
                headers_w.len().saturating_sub(1),
            )),
            Some(body_bytes.as_ptr() as *const _),
            body_bytes.len() as u32,
            body_bytes.len() as u32,
            0,
        );

        let mut status_code: u32 = 0;
        if sent.is_ok() && WinHttpReceiveResponse(request, std::ptr::null_mut()).is_ok() {
            let mut buf = [0u8; 4];
            let mut buf_len = std::mem::size_of_val(&buf) as u32;
            let mut index = 0;
            let _ = WinHttpQueryHeaders(
                request,
                WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                PCWSTR::null(),
                Some(buf.as_mut_ptr() as *mut _),
                &mut buf_len,
                &mut index,
            );
            status_code = u32::from_ne_bytes(buf);
        }

        let _ = WinHttpCloseHandle(request);
        let _ = WinHttpCloseHandle(connect);
        let _ = WinHttpCloseHandle(session);

        if status_code == 0 {
            Err("no response (send/receive failed)".to_string())
        } else {
            Ok(status_code)
        }
    }
}

// =====================================================
// FOREGROUND WINDOW MONITORING — event-driven, not polled
// =====================================================
// SetWinEventHook, not a timer — the OS tells us the instant the
// foreground window changes, so this costs nothing between actual
// switches. Registered on the same UI thread as the low-level input
// hooks, since both need a Win32 message pump on the thread that
// registered them.
unsafe extern "system" fn win_event_proc(
    _hook: HWINEVENTHOOK,
    event: u32,
    hwnd: HWND,
    _id_object: i32,
    _id_child: i32,
    _thread_id: u32,
    _time: u32,
) {
    let _timer = PerfTimer::new(&FAST_LANE_ACCUM_US);
    if event != EVENT_SYSTEM_FOREGROUND || hwnd.is_invalid() {
        return;
    }
    check_foreground_window(hwnd);
}

unsafe fn check_foreground_window(hwnd: HWND) {
    let mut buf = [0u16; 512];
    let len = GetWindowTextW(hwnd, &mut buf);
    if len <= 0 {
        return;
    }
    let title = String::from_utf16_lossy(&buf[..len as usize]).to_lowercase();
    let rules = fastlane_rules().lock().unwrap().clone();
    for kw in &rules.banned_window_title_keywords {
        if !kw.is_empty() && title.contains(&kw.to_lowercase()) {
            trigger_fastlane_violation("window_title", &title);
            return;
        }
    }
}

// =====================================================
// PROCESS MONITORING — replaces the WMI-based process spy in Python
// =====================================================
// ToolHelp32 snapshot diffing at the same 1-second cadence Python's own
// polling fallback already used — except this no longer needs `import
// wmi` / `pythoncom` in Python at all. That import is real, measurable
// GIL-blocking cost paid during Python's boot window (COM type-library
// loading briefly monopolizes the GIL the same way the old Tk overlay
// did) for a background watcher that has nothing to do with Python's own
// startup. Python now gets a short list of already-identified new PIDs
// instead of enumerating every process itself every second.
fn process_monitor_loop() {
    unsafe {
        let _ = SetThreadDescription(
            windows::Win32::System::Threading::GetCurrentThread(),
            windows::core::w!("process_monitor"),
        );
    }

    let mut known: std::collections::HashSet<u32> = std::collections::HashSet::new();
    let mut first_pass = true;

    loop {
        if let Some(current) = snapshot_process_names() {
            let rules = fastlane_rules().lock().unwrap().clone();

            for (pid, name) in &current {
                if !known.contains(pid) {
                    if !first_pass {
                        append_event(&serde_json::json!({
                            "type": "new_process", "pid": pid, "name": name,
                            "timestamp": SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0),
                        }));
                    }
                    if rules
                        .banned_process_names
                        .iter()
                        .any(|b| b.eq_ignore_ascii_case(name))
                    {
                        trigger_fastlane_violation("process", name);
                    }
                }
            }
            known = current.keys().copied().collect();
            first_pass = false;
        }
        thread::sleep(Duration::from_secs(1));
    }
}

unsafe fn snapshot_process_names_inner() -> Option<std::collections::HashMap<u32, String>> {
    let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).ok()?;
    let mut entry = PROCESSENTRY32W {
        dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    let mut out = std::collections::HashMap::new();

    if Process32FirstW(snapshot, &mut entry).is_ok() {
        loop {
            let name_len = entry.szExeFile.iter().position(|&c| c == 0).unwrap_or(0);
            let name = String::from_utf16_lossy(&entry.szExeFile[..name_len]);
            out.insert(entry.th32ProcessID, name);
            if Process32NextW(snapshot, &mut entry).is_err() {
                break;
            }
        }
    }
    let _ = CloseHandle(snapshot);
    Some(out)
}

fn snapshot_process_names() -> Option<std::collections::HashMap<u32, String>> {
    unsafe { snapshot_process_names_inner() }
}

// =====================================================
// NETWORK ADAPTER MONITORING — replaces Python's psutil-based poller
// =====================================================
// A newly-appeared tethering adapter is exactly the kind of "obvious,
// explicit" signal the fast lane exists for — worth catching the instant
// it appears, not 15 seconds later once Python is finally up.
fn network_adapter_monitor_loop() {
    unsafe {
        let _ = SetThreadDescription(
            windows::Win32::System::Threading::GetCurrentThread(),
            windows::core::w!("network_monitor"),
        );
    }

    let mut known = match enumerate_adapter_names() {
        Some(set) => {
            logger().info(
                "net-adapter",
                "baseline captured",
                &[("count", &set.len().to_string())],
            );
            set
        }
        None => {
            logger().error(
                "net-adapter",
                "failed to capture baseline — monitor disabled",
                &[],
            );
            return;
        }
    };

    loop {
        // Write the perf snapshot. Deliberately raw CUMULATIVE seconds,
        // never reset — the previous version here reset these counters to
        // zero every cycle and tried to pre-compute a percentage assuming
        // the loop always takes exactly 5 seconds between writes. That
        // assumption breaks the moment this iteration's adapter
        // enumeration or fastlane-rules reload takes even slightly longer
        // than usual, and it's incompatible with how Python's own
        // perf_snapshot.json works (also raw cumulative seconds). `doctor
        // --profile` reads two snapshots at the actual start/end of its
        // observation window and diffs them over the REAL elapsed time —
        // exactly how Task Manager and every other real profiler computes
        // %CPU — which only works if the underlying counter never resets
        // out from under it.
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        let hooks_s = HOOKS_ACCUM_US.load(Ordering::Relaxed) as f64 / 1_000_000.0;
        let fastlane_s = FAST_LANE_ACCUM_US.load(Ordering::Relaxed) as f64 / 1_000_000.0;

        let snapshot = serde_json::json!({
            "timestamp": timestamp,
            "threads": {
                "ui": {
                    "hooks": hooks_s,
                    "fast_lane_window_check": fastlane_s
                }
            }
        });

        let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
        let snapshot_path = std::path::PathBuf::from(base)
            .join("Obylon")
            .join("logs")
            .join("core_perf_snapshot.json");
        let _ = std::fs::write(&snapshot_path, snapshot.to_string());

        thread::sleep(Duration::from_secs(5));
        refresh_fastlane_rules(); // piggyback the periodic rules reload here — no separate timer needed
        let Some(current) = enumerate_adapter_names() else {
            continue;
        };
        let rules = fastlane_rules().lock().unwrap().clone();

        for adapter in current.difference(&known) {
            let suspect = rules
                .tether_adapter_hints
                .iter()
                .any(|h| adapter.to_lowercase().contains(&h.to_lowercase()));
            append_event(&serde_json::json!({
                "type": "new_network_adapter", "adapter": adapter, "suspect_tethering": suspect,
                "timestamp": SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0),
            }));
            if suspect {
                trigger_fastlane_violation("network_adapter", adapter);
            }
        }
        known = current;
    }
}

unsafe fn enumerate_adapter_names_inner() -> Option<std::collections::HashSet<String>> {
    let mut buf_len: u32 = 15000; // MSDN-recommended starting size
    let mut buffer: Vec<u8> = vec![0; buf_len as usize];

    for _ in 0..3 {
        let ptr = buffer.as_mut_ptr() as *mut IP_ADAPTER_ADDRESSES_LH;
        let result = GetAdaptersAddresses(
            0,
            windows::Win32::NetworkManagement::IpHelper::GET_ADAPTERS_ADDRESSES_FLAGS(0),
            None,
            Some(ptr),
            &mut buf_len,
        );
        if result == 0 {
            let mut names = std::collections::HashSet::new();
            let mut cur = ptr;
            while !cur.is_null() {
                let adapter = &*cur;
                if !adapter.FriendlyName.is_null() {
                    if let Ok(name) = adapter.FriendlyName.to_string() {
                        if !name.is_empty() {
                            names.insert(name);
                        }
                    }
                }
                cur = adapter.Next;
            }
            return Some(names);
        } else if result == 111 {
            // ERROR_BUFFER_OVERFLOW — buf_len now holds the required size
            buffer = vec![0; buf_len as usize];
            continue;
        } else {
            return None;
        }
    }
    None
}

fn enumerate_adapter_names() -> Option<std::collections::HashSet<String>> {
    unsafe { enumerate_adapter_names_inner() }
}

// KNOWN GAP, phase 2: no pipe ACL restriction yet (default DACL — any
// local process in this session can connect). Acceptable for now because
// Core only ever has one legitimate client (the Brain process it spawned
// itself), but this should be locked down to SYSTEM + the session's user
// SID before this goes further than a pilot.
unsafe fn is_process_descendant_of(mut child: u32, ancestor: u32) -> bool {
    if child == ancestor { return true; }
    let snapshot = match windows::Win32::System::Diagnostics::ToolHelp::CreateToolhelp32Snapshot(
        windows::Win32::System::Diagnostics::ToolHelp::TH32CS_SNAPPROCESS, 0
    ) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let mut entry = windows::Win32::System::Diagnostics::ToolHelp::PROCESSENTRY32W {
        dwSize: std::mem::size_of::<windows::Win32::System::Diagnostics::ToolHelp::PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    let mut parent_map = std::collections::HashMap::new();
    if windows::Win32::System::Diagnostics::ToolHelp::Process32FirstW(snapshot, &mut entry).is_ok() {
        loop {
            parent_map.insert(entry.th32ProcessID, entry.th32ParentProcessID);
            if windows::Win32::System::Diagnostics::ToolHelp::Process32NextW(snapshot, &mut entry).is_err() {
                break;
            }
        }
    }
    let _ = windows::Win32::Foundation::CloseHandle(snapshot);
    for _ in 0..10 {
        if child == ancestor { return true; }
        if let Some(&p) = parent_map.get(&child) {
            if p == 0 { break; }
            child = p;
        } else {
            break;
        }
    }
    false
}

fn handle_connection(pipe: HANDLE) {
    unsafe {
        // Access control. The pipe's default DACL allows any process
        // owned by the same user to connect — and Core and Brain both
        // run as that same (non-SYSTEM) session user by design, so a
        // plain SID-based ACL can't tell "the Brain process I spawned"
        // apart from "any other script the student happens to run." This
        // checks the exact PID instead, which Core already knows
        // precisely because it spawned it (see BRAIN_PID in spawn_brain).
        // Anything else is refused before a single byte of its request is
        // even read — including Ping; nothing legitimate talks to this
        // pipe except Brain, so there's no reason to special-case it.
        let mut client_pid: u32 = 0;
        let expected_pid = BRAIN_PID.load(Ordering::SeqCst);
        let authorized = GetNamedPipeClientProcessId(pipe, &mut client_pid).is_ok()
            && expected_pid != 0
            && is_process_descendant_of(client_pid, expected_pid);
        if !authorized {
            logger().warn(
                "ipc",
                "rejected pipe connection from unauthorized process",
                &[
                    ("client_pid", &client_pid.to_string()),
                    ("expected_pid", &expected_pid.to_string()),
                ],
            );
            let _ = DisconnectNamedPipe(pipe);
            let _ = CloseHandle(pipe);
            return;
        }

        let mut buf = [0u8; 65536];
        let mut read: u32 = 0;
        if ReadFile(pipe, Some(&mut buf), Some(&mut read), None).is_err() {
            let _ = DisconnectNamedPipe(pipe);
            let _ = CloseHandle(pipe);
            return;
        }
        let line = String::from_utf8_lossy(&buf[..read as usize]).to_string();

        let response = match IpcRequest::parse_line(&line) {
            Ok(IpcRequest::Ping) => IpcResponse::ok(),
            Ok(IpcRequest::Freeze {
                duration_secs,
                reason,
            }) => {
                do_freeze(duration_secs, reason);
                IpcResponse::ok_with_locked(true)
            }
            Ok(IpcRequest::Unfreeze { reason }) => {
                let unfroze = do_unfreeze(reason);
                // "locked" reflects the actual post-operation state — if
                // do_unfreeze() refused the request (verified bug #3),
                // the caller needs to see locked=true, not a rubber-stamp
                // false, so Python can log the refusal instead of caching
                // a locked state it no longer believes is true.
                IpcResponse::ok_with_locked(!unfroze)
            }
            Ok(IpcRequest::ShowOverlay { kind }) => {
                set_overlay_kind(kind);
                show_overlay(true);
                IpcResponse::ok()
            }
            Ok(IpcRequest::HideOverlay) => {
                show_overlay(false);
                IpcResponse::ok()
            }
            Ok(IpcRequest::GetKeylogSnapshot) => {
                // Lock held only long enough to clone the buffer contents
                // out — join() (an extra allocation pass) happens after
                // releasing it. record_keystroke() on the hook thread
                // takes this same mutex on every keypress, and a hook
                // callback that's blocked too long risks Windows silently
                // unhooking it (LowLevelHooksTimeout) — keeping this
                // critical section as short as possible matters more here
                // than in most places in this file.
                let snapshot: Vec<String> = keylog().lock().unwrap().iter().cloned().collect();
                let text = snapshot.join("");
                IpcResponse::ok_with_text(text)
            }
            Ok(IpcRequest::ClearKeylog) => {
                keylog().lock().unwrap().clear();
                IpcResponse::ok()
            }
            Ok(IpcRequest::CaptureScreenshot) => match capture_screenshot_to_file() {
                Ok(path) => IpcResponse::ok_with_path(path.to_string_lossy().to_string()),
                Err(e) => {
                    logger().error("capture", "screenshot failed", &[("error", &e)]);
                    IpcResponse::err(e)
                }
            },
            Ok(IpcRequest::CaptureWebcam) => match capture_webcam_to_file() {
                Ok(path) => IpcResponse::ok_with_path(path.to_string_lossy().to_string()),
                Err(e) => {
                    logger().error("capture", "webcam failed", &[("error", &e)]);
                    IpcResponse::err(e)
                }
            },
            Err(e) => IpcResponse::err(format!("bad request: {e}")),
        };

        let out = response.to_line();
        let mut written: u32 = 0;
        let _ = WriteFile(pipe, Some(out.as_bytes()), Some(&mut written), None);
        unsafe { let _ = windows::Win32::Storage::FileSystem::FlushFileBuffers(pipe); }
        let _ = DisconnectNamedPipe(pipe);
        let _ = CloseHandle(pipe);
    }
}

fn ipc_server_loop() {
    unsafe {
        let _ = SetThreadDescription(
            windows::Win32::System::Threading::GetCurrentThread(),
            windows::core::w!("ipc_server"),
        );
    }

    let pipe_name = wide(PIPE_NAME);
    loop {
        unsafe {
            let pipe = CreateNamedPipeW(
                PCWSTR(pipe_name.as_ptr()),
                windows::Win32::Storage::FileSystem::FILE_FLAGS_AND_ATTRIBUTES(0x00000003), // PIPE_ACCESS_DUPLEX
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
                windows::Win32::System::Pipes::PIPE_UNLIMITED_INSTANCES,
                65536,
                65536,
                0,
                None,
            );
            if pipe == windows::Win32::Foundation::INVALID_HANDLE_VALUE {
                logger().error("ipc", "CreateNamedPipeW failed", &[]);
                thread::sleep(Duration::from_secs(1));
                continue;
            }

            if ConnectNamedPipe(pipe, None).is_err() {
                // ERROR_PIPE_CONNECTED is expected/benign if a client
                // raced us between create and connect — fall through and
                // service it anyway.
            }

            let pipe_ptr = pipe.0 as usize;
            thread::spawn(move || {
                let p = windows::Win32::Foundation::HANDLE(pipe_ptr as *mut _);
                handle_connection(p);
            });
        }
    }
}

// =====================================================
// BRAIN SUPERVISION
// =====================================================
// Plain CreateProcessW, not CreateProcessAsUser — Core already runs as
// the interactive user (Broker did the impersonation hop), so this is
// just an ordinary child-process spawn. Phase 1 scope: spawn once, log
// if it exits. Respawn-on-crash supervision is a phase 2 concern (see
// the architecture doc's Watchdog discussion).

const IDENTITY_VIOLATION_EXIT_CODE: u32 = 78;
const BRAIN_STABLE_RUNTIME: Duration = Duration::from_secs(60);
const BRAIN_REMEDIATION_RETRY: Duration = Duration::from_secs(300);

fn brain_exe_path() -> String {
    if let Ok(p) = env::var("OBYLON_BRAIN_PATH") {
        return p;
    }

    if let Ok(mut path) = env::current_exe() {
        path.set_file_name("obylon.exe");
        return path.to_string_lossy().to_string();
    }

    let programfiles = env::var("PROGRAMFILES").unwrap_or_else(|_| "C:\\Program Files".to_string());
    format!("{}\\Obylon\\Obylon.exe", programfiles)
}

fn brain_stdout_path() -> PathBuf {
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    let dir = PathBuf::from(base).join("Obylon").join("logs");
    let _ = std::fs::create_dir_all(&dir);
    dir.join("brain_stdout.log")
}

fn spawn_brain() -> Option<HANDLE> {
    let exe = brain_exe_path();
    let mut cmdline = wide(&format!("\"{}\"", exe));

    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::Security::SECURITY_ATTRIBUTES;
    use windows::Win32::Storage::FileSystem::{
        CreateFileW, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, FILE_GENERIC_WRITE, FILE_SHARE_READ,
        FILE_SHARE_WRITE,
    };
    use windows::Win32::System::Threading::STARTF_USESTDHANDLES;

    let stdout_path = brain_stdout_path();
    let log_path = wide(&stdout_path.to_string_lossy());
    let mut sa = SECURITY_ATTRIBUTES::default();
    sa.nLength = std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32;
    sa.bInheritHandle = windows::Win32::Foundation::TRUE;

    let h_log = unsafe {
        CreateFileW(
            windows::core::PCWSTR(log_path.as_ptr()),
            FILE_GENERIC_WRITE.0,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            Some(&sa),
            CREATE_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
    };

    let h_out = h_log.clone().unwrap_or_default();
    let inherit_log_handle = h_log.is_ok();
    let mut startup_info = STARTUPINFOW {
        cb: std::mem::size_of::<STARTUPINFOW>() as u32,
        ..Default::default()
    };
    if inherit_log_handle {
        startup_info.dwFlags = STARTF_USESTDHANDLES;
        startup_info.hStdOutput = h_out;
        startup_info.hStdError = h_out;
    } else {
        logger().warn(
            "brain",
            "could not open brain stdout log; spawning without redirected output",
            &[("path", &stdout_path.to_string_lossy())],
        );
    }
    let mut proc_info = PROCESS_INFORMATION::default();

    unsafe {
        let ok = CreateProcessW(
            PCWSTR::null(),
            Some(PWSTR(cmdline.as_mut_ptr())),
            None,
            None,
            inherit_log_handle,
            PROCESS_CREATION_FLAGS(CREATE_UNICODE_ENVIRONMENT.0 | CREATE_NO_WINDOW.0),
            None,
            PCWSTR::null(),
            &startup_info,
            &mut proc_info,
        );
        if ok.is_err() {
            logger().error(
                "brain",
                "failed to spawn Python brain",
                &[("exe", &exe), ("error", &format!("{:?}", GetLastError()))],
            );
            if let Ok(h) = h_log {
                let _ = CloseHandle(h);
            }
            return None;
        }
        logger().info(
            "brain",
            "brain process spawned",
            &[("pid", &proc_info.dwProcessId.to_string())],
        );
        BRAIN_PID.store(proc_info.dwProcessId, Ordering::SeqCst);
        if let Ok(h) = h_log {
            let _ = CloseHandle(h);
        }
        let _ = CloseHandle(proc_info.hThread);
        return Some(proc_info.hProcess);
    }
}

fn brain_restart_delay(crash_streak: u32) -> Duration {
    Duration::from_secs(2u64.saturating_pow(crash_streak.min(5)))
}

fn brain_supervisor_loop() {
    let mut crash_streak = 0u32;
    loop {
        let process = match spawn_brain() {
            Some(process) => process,
            None => {
                crash_streak = crash_streak.saturating_add(1);
                let delay = brain_restart_delay(crash_streak);
                logger().warn(
                    "brain",
                    "brain spawn failed; retrying",
                    &[("delay_seconds", &delay.as_secs().to_string())],
                );
                thread::sleep(delay);
                continue;
            }
        };

        let started = Instant::now();
        let wait_result = unsafe { WaitForSingleObject(process, INFINITE) };
        let mut exit_code = 1u32;
        if wait_result == windows::Win32::Foundation::WAIT_FAILED
            || unsafe { GetExitCodeProcess(process, &mut exit_code) }.is_err()
        {
            logger().error(
                "brain",
                "could not wait for brain process",
                &[("error", &format!("{:?}", unsafe { GetLastError() }))],
            );
        }
        let _ = unsafe { CloseHandle(process) };
        BRAIN_PID.store(0, Ordering::SeqCst);

        if exit_code == IDENTITY_VIOLATION_EXIT_CODE {
            logger().error(
                "brain",
                "brain confirmed an identity mismatch; waiting for remediation before retrying",
                &[(
                    "retry_seconds",
                    &BRAIN_REMEDIATION_RETRY.as_secs().to_string(),
                )],
            );
            crash_streak = 0;
            thread::sleep(BRAIN_REMEDIATION_RETRY);
            continue;
        }

        crash_streak = if started.elapsed() >= BRAIN_STABLE_RUNTIME {
            0
        } else {
            crash_streak.saturating_add(1)
        };
        let delay = brain_restart_delay(crash_streak);
        logger().warn(
            "brain",
            "brain exited; scheduling supervised restart",
            &[
                ("exit_code", &exit_code.to_string()),
                ("delay_seconds", &delay.as_secs().to_string()),
            ],
        );
        thread::sleep(delay);
    }
}

fn main() {
    // Must be the first thing this process does — before any window is
    // created, before any GetSystemMetrics/GetDC call, on this thread or
    // any other. Without it, Windows silently virtualizes this process's
    // view of the screen on any display above 100% scaling: a 1920x1080
    // monitor at 150% scaling reports as 1280x720, so both the freeze
    // overlay and BitBlt screenshot capture (both wired to
    // virtual_screen_rect(), see its doc comment) would silently operate
    // on a scaled-down, cropped region instead of the real screen.
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    }

    let log_instance = FileLogger::open(&log_path()).expect("cannot open core log path");
    LOGGER.set(log_instance).ok();
    logger().info("core", "ObylonCore starting", &[]);

    let _instance_mutex =
        match unsafe { CreateMutexW(None, false, windows::core::w!("Local\\ObylonCoreMutex")) } {
            Ok(handle) if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS => {
                logger().warn(
                    "core",
                    "another Core instance already owns this session",
                    &[],
                );
                let _ = unsafe { CloseHandle(handle) };
                return;
            }
            Ok(handle) => handle,
            Err(error) => {
                logger().error(
                    "core",
                    "could not create Core singleton mutex",
                    &[("error", &format!("{error:?}"))],
                );
                return;
            }
        };

    thread::spawn(ui_thread_main);
    // Dedicated thread for applying overlay show/hide requests — keeps
    // ShowWindow spam from ever reaching ui_thread_main's message queue
    // (verified bug #7). See overlay_watcher_loop() for the full story.
    thread::spawn(overlay_watcher_loop);

    // Give the UI thread a moment to install hooks/create the overlay
    // before Brain (and its first IPC calls) shows up — cheap and avoids
    // a startup-order race on the very first freeze/overlay request.
    for _ in 0..50 {
        if OVERLAY_HWND.load(Ordering::SeqCst) != 0 {
            break;
        }
        thread::sleep(Duration::from_millis(100));
    }

    // Fast lane: armed and watching from here, before Brain has even
    // been spawned. This is the entire point — by the time Python's
    // interpreter finishes starting and its imports finish loading,
    // Core has already been checking every foreground-window change and
    // every new process for ~10+ seconds.
    refresh_fastlane_rules();
    thread::spawn(process_monitor_loop);
    thread::spawn(network_adapter_monitor_loop);
    logger().info("fastlane", "fast lane armed", &[]);

    thread::spawn(brain_supervisor_loop);

    ipc_server_loop(); // blocks forever
}
