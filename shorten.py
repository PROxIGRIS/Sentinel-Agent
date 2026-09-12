import os

root_go = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\obylonc\cmd\root.go'
with open(root_go, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'Commit      = "session-broker+provenance+multilingual+recovery-intelligence+vault-integrity+ad-network-reputation+adaptive-scan-pressure+installer-activation+cli-admin-scope"',
    'Commit      = "f12411e"'
)

with open(root_go, 'w', encoding='utf-8') as f:
    f.write(content)

print("Commit hash shortened.")
