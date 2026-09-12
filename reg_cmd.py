import os
import re

root_go = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\obylonc\cmd\root.go'
with open(root_go, 'r', encoding='utf-8') as f:
    content = f.read()

# Register the troubleshoot command
reg_str = '"diagnose":             {run: runDiagnose, brief: "Run connectivity, token, and signature diagnostics", scope: "diagnose", action: "obylon.diagnose", admin: false},'
new_reg = reg_str + '\n\t"troubleshoot":         {run: runTroubleshoot, brief: "Deep dive smart diagnostic engine for boot/spawn failures", scope: "diagnose", action: "obylon.diagnose", admin: true},'
content = content.replace(reg_str, new_reg)

reg_admin = '"diagnose":       {run: runDiagnose, brief: "Run endpoint diagnostics", scope: "diagnose", action: "obylon.diagnose", admin: true},'
new_admin = reg_admin + '\n\t"troubleshoot":   {run: runTroubleshoot, brief: "Deep dive smart diagnostic engine", scope: "diagnose", action: "obylon.diagnose", admin: true},'
content = content.replace(reg_admin, new_admin)

admin_order = 'adminOrder := []string{"activate", "status", "diagnose", "doctor", "logs", "broker-logs", "core-logs", "ai", "support-bundle", "boot", "reset-identity", "deactivate"}'
new_admin_order = admin_order.replace('"diagnose",', '"diagnose", "troubleshoot",')
content = content.replace(admin_order, new_admin_order)

help_str = '"  diagnose       Run connectivity and signature diagnostics",'
new_help = help_str + '\n\t\t"  troubleshoot   Deep dive smart diagnostic engine for boot/spawn failures",'
content = content.replace(help_str, new_help)

with open(root_go, 'w', encoding='utf-8') as f:
    f.write(content)

print("troubleshoot command registered.")
