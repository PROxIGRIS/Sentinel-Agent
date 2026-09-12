import os

fp = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\obylonc\cmd\troubleshoot.go'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('"Obylon\\\\Brain"', '"ObylonAgent"')
content = content.replace("'Obylon\\\\Brain'", "'ObylonAgent'")

with open(fp, 'w', encoding='utf-8') as f:
    f.write(content)
