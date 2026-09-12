import sys
import re

with open('Obylon.py', 'r', encoding='utf-8') as f:
    code = f.read()

def inject_perf_section(func_name, section_group, section_name):
    global code
    pattern = re.compile(r'(def ' + func_name + r'\([^)]*\)(?: -> [^:]+)?:[\r\n]+(?:[ \t]+""\"[\s\S]*?"""[\r\n]+)?)(.*?)(?=^\s*def |^\s*class |^\w|# ----------)', re.MULTILINE | re.DOTALL)
    
    def repl(m):
        header = m.group(1)
        body = m.group(2)
        # Find the indentation of the first line of the body
        first_line_match = re.search(r'^([ \t]+)', body, re.MULTILINE)
        if not first_line_match: return m.group(0)
        indent = first_line_match.group(1)
        
        # Inject the context manager
        new_header = header + indent + f'with _perf_section("{section_group}", "{section_name}"):\n'
        
        # Indent the body
        new_body = ''
        for line in body.splitlines(True):
            if line.strip():
                new_body += '    ' + line
            else:
                new_body += line
        
        return new_header + new_body

    code = pattern.sub(repl, code, count=1)

inject_perf_section('get_foreground_window', 'scanner', 'context')
inject_perf_section('process_telemetry', 'scanner', 'fsm')
inject_perf_section('threat_score', 'scanner', 'arbitration')

with open('Obylon.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('Done injecting perf sections')
