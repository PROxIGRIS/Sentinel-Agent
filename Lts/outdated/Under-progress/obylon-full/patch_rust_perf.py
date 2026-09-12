import re

with open('rust/core/src/main.rs', 'r', encoding='utf-8') as f:
    code = f.read()

# Add atomics and Timer struct
atomics = '''
use std::sync::atomic::{AtomicU64, Ordering};
static HOOKS_ACCUM_US: AtomicU64 = AtomicU64::new(0);
static FAST_LANE_ACCUM_US: AtomicU64 = AtomicU64::new(0);

struct PerfTimer {
    accum: &'static AtomicU64,
    start: std::time::Instant,
}
impl PerfTimer {
    fn new(accum: &'static AtomicU64) -> Self {
        Self { accum, start: std::time::Instant::now() }
    }
}
impl Drop for PerfTimer {
    fn drop(&mut self) {
        self.accum.fetch_add(self.start.elapsed().as_micros() as u64, Ordering::Relaxed);
    }
}
'''
if 'struct PerfTimer' not in code:
    code = code.replace('use std::sync::atomic::', atomics + '\nuse std::sync::atomic::', 1)
    if 'struct PerfTimer' not in code:
        code = code.replace('use std::thread;', atomics + '\nuse std::thread;', 1)

# Inject into keyboard hook
code = re.sub(
    r'(unsafe extern "system" fn keyboard_hook_proc[^{]*\{)',
    r'\1\n    let _timer = PerfTimer::new(&HOOKS_ACCUM_US);',
    code
)

# Inject into mouse hook
code = re.sub(
    r'(unsafe extern "system" fn mouse_hook_proc[^{]*\{)',
    r'\1\n    let _timer = PerfTimer::new(&HOOKS_ACCUM_US);',
    code
)

# Inject into win_event_proc
code = re.sub(
    r'(unsafe extern "system" fn win_event_proc[^{]*\{)',
    r'\1\n    let _timer = PerfTimer::new(&FAST_LANE_ACCUM_US);',
    code
)

# Modify network_adapter_monitor_loop to write snapshot
snapshot_logic = r'''
        // Write perf snapshot
        let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
        let hooks_s = HOOKS_ACCUM_US.swap(0, Ordering::Relaxed) as f64 / 1_000_000.0;
        let fastlane_s = FAST_LANE_ACCUM_US.swap(0, Ordering::Relaxed) as f64 / 1_000_000.0;
        
        let snapshot = serde_json::json!({
            "timestamp": timestamp,
            "threads": {
                "ui": {
                    "hooks": hooks_s * 100.0, // doctor expects %, so this isn't exactly right but we follow schema. Wait, if it's over 5s, we'd divide by 5 to get %.
                    // Actually, if we just report the raw seconds, or calculate %. Let's output what doctor expects: numbers representing cpu % used by that section.
                    // over 5s window, (hooks_s / 5.0) * 100.0 = hooks_s * 20.0
                    "hooks": hooks_s * 20.0,
                    "fast_lane_window_check": fastlane_s * 20.0
                }
            }
        });
        
        let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
        let snapshot_path = std::path::PathBuf::from(base).join("Obylon").join("logs").join("core_perf_snapshot.json");
        let _ = std::fs::write(&snapshot_path, snapshot.to_string());
'''

code = code.replace('        thread::sleep(Duration::from_secs(5));', snapshot_logic + '\n        thread::sleep(Duration::from_secs(5));')

with open('rust/core/src/main.rs', 'w', encoding='utf-8') as f:
    f.write(code)
print('Done injecting perf into Rust Core')
