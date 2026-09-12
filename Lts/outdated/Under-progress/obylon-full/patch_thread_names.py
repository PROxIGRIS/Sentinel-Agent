import re

with open('Obylon.py', 'r', encoding='utf-8') as f:
    code = f.read()

def inject_thread_name(func_name, thread_name):
    global code
    # We want to match the function definition and insert the call on the first line inside
    pattern = re.compile(r'(def ' + func_name + r'\([^)]*\)(?: -> [^:]+)?:[\r\n]+(?:[ \t]+""\"[\s\S]*?"""[\r\n]+)?)([ \t]+)(?=\S)', re.MULTILINE)
    
    def repl(m):
        header = m.group(1)
        indent = m.group(2)
        return header + indent + f'_name_current_thread("{thread_name}")\n' + indent
        
    code = pattern.sub(repl, code, count=1)

inject_thread_name('heartbeat_loop', 'heartbeat')
inject_thread_name('scan_loop', 'scan')
inject_thread_name('action_loop', 'action')
inject_thread_name('hardware_panic_listener', 'hardware_panic')
inject_thread_name('sync_daemon', 'sync_daemon')
inject_thread_name('boot_optics_server', 'optics')
inject_thread_name('_clipboard_watcher', 'clipboard')
inject_thread_name('remote_config_loop', 'remote_config')
inject_thread_name('realtime_c2_listener', 'realtime_c2')
inject_thread_name('consume_core_events_loop', 'core_events')
inject_thread_name('tesseract_worker', 'ocr')
inject_thread_name('_compute_hardware_fingerprint_async', 'hw_fingerprint')

with open('Obylon.py', 'w', encoding='utf-8') as f:
    f.write(code)
