import sys

with open('Obylon.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_score = False
for i, line in enumerate(lines):
    if line.startswith('    def score(self, title: str, proc: str)'):
        in_score = True
        continue
    if in_score:
        if line.startswith('        with _perf_section'):
            break # We are here
        elif line.startswith('            """'):
            lines[i] = line.replace('            """', '        """')
        elif line.startswith('            Returns:'):
            lines[i] = line.replace('            Returns:', '        Returns:')

with open('Obylon.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
