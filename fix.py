import os

fp = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\obylonc\cmd\troubleshoot.go'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(r'logPath := C:\ProgramData\Obylon\logs\agent.log', r'logPath := "C:\\ProgramData\\Obylon\\logs\\agent.log"')

with open(fp, 'w', encoding='utf-8') as f:
    f.write(content)
