import re

with open('rust/core/src/main.rs', 'r', encoding='utf-8') as f:
    code = f.read()

# Add SetThreadDescription import
code = re.sub(
    r'(use windows::Win32::System::Threading::\{[^\}]+)(\})',
    r'\1, SetThreadDescription\2',
    code,
    count=1
)

# Helper to inject SetThreadDescription at start of block
def inject_thread_name(func_body_start_regex, thread_name):
    global code
    pattern = re.compile(func_body_start_regex, re.MULTILINE)
    
    def repl(m):
        full_match = m.group(0)
        return full_match + f'\n    unsafe {{ let _ = SetThreadDescription(windows::Win32::System::Threading::GetCurrentThread(), windows::core::PCWSTR::from_raw(obylon_common::wide("{thread_name}").as_ptr())); }}\n'

    code = pattern.sub(repl, code, count=1)

inject_thread_name(r'fn ui_thread_main\(\) \{', 'ui_thread')
inject_thread_name(r'fn process_monitor_loop\(\) \{', 'process_monitor')
inject_thread_name(r'fn network_adapter_monitor_loop\(\) \{', 'network_monitor')
inject_thread_name(r'fn ipc_server_loop\(\) \{', 'ipc_server')

with open('rust/core/src/main.rs', 'w', encoding='utf-8') as f:
    f.write(code)
