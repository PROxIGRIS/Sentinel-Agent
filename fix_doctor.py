import os

fp = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\obylonc\cmd\doctor.go'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

old_check = 'if !strings.EqualFold(strings.TrimSpace(definition.Actions.Context), "System") || !hasBrokerAction(definition.Actions.Execs) {'
new_check = 'if !hasBrokerAction(definition.Actions.Execs) {'
content = content.replace(old_check, new_check)

with open(fp, 'w', encoding='utf-8') as f:
    f.write(content)
