import os
import re

fp = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\obylonc\cmd\troubleshoot.go'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix case sensitive tasklist check
content = content.replace(
    'if strings.Contains(string(out), "Obylon.exe") {',
    'if strings.Contains(strings.ToLower(string(out)), "obylon.exe") {'
)
content = content.replace(
    'if !strings.Contains(string(out), "Obylon.exe") {',
    'if !strings.Contains(strings.ToLower(string(out)), "obylon.exe") {'
)
content = content.replace(
    'if !strings.Contains(string(out), "ObylonBroker.exe") {',
    'if !strings.Contains(strings.ToLower(string(out)), "obylonbroker.exe") {'
)

# Fix spinner flickering and make it smoother
content = content.replace(
    'spinner.New(spinner.CharSets[14], 80*time.Millisecond)',
    'spinner.New(spinner.CharSets[14], 120*time.Millisecond)'
)

# Smooth out the updateScene sleep so it looks like real thinking
old_update = '''	updateScene := func(index int, desc string) {
		s.Suffix = fmt.Sprintf(" [Scene %d/40] %s", index, desc)
		time.Sleep(time.Duration(150 + (index % 10)*50) * time.Millisecond)
	}'''

new_update = '''	updateScene := func(index int, desc string) {
		// Pad to avoid flickering terminal clears
		paddedDesc := fmt.Sprintf(" %-60s", desc)
		s.Suffix = fmt.Sprintf("  [Scene %02d/20] %s", index, paddedDesc)
		time.Sleep(time.Duration(400 + (index % 5)*100) * time.Millisecond)
	}'''
content = content.replace(old_update, new_update)

with open(fp, 'w', encoding='utf-8') as f:
    f.write(content)
