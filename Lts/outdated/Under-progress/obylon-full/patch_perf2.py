import sys
import re

with open('Obylon.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_score = False
indent = ''
for i, line in enumerate(lines):
    if 'def score(self, title: str, proc: str)' in line:
        in_score = True
        indent = ' ' * 4
        continue
    if in_score:
        if line.strip() == 'with _perf_section("scanner", "lexical"):':
            pass # Keep it
        elif 'full_haystack =' in line and 'title or' in line:
            pass # Already indented correctly by previous replace
        elif 'normalized =' in line and 'normalize_haystack' in line:
            pass # Already indented correctly by previous replace
        elif not line.strip():
            pass
        elif line.startswith('    def ') or line.startswith('class '):
            in_score = False
        else:
            if line.startswith(indent):
                lines[i] = '    ' + line

with open('Obylon.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Done fixing LexEngine.score')
