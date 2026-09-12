import sys

with open('Obylon.py', 'r', encoding='utf-8') as f:
    code = f.read()

target1 = '''def _build_alert_payload(workstation_id: str, title: str | None, proc: str | None,
                         severity: str, is_backlogged: bool,
                         created_at: str | None = None,
                         reason: str | None = None) -> dict:
    # DB ENUM mapping for Supabase constraints'''

replacement1 = '''def _build_alert_payload(workstation_id: str, title: str | None, proc: str | None,
                         severity: str, is_backlogged: bool,
                         created_at: str | None = None,
                         reason: str | None = None) -> dict:
    if is_backlogged:
        title = f"[OFFLINE/DELAYED] {title}" if title else "[OFFLINE/DELAYED]"

    # DB ENUM mapping for Supabase constraints'''

if target1 in code:
    code = code.replace(target1, replacement1)

target2 = '''def _build_activity_payload(workstation_id: str, title: str | None, proc: str | None,
                            severity: str, is_anomaly: bool,
                            is_backlogged: bool,
                            created_at: str | None = None) -> dict:
    payload = {'''

replacement2 = '''def _build_activity_payload(workstation_id: str, title: str | None, proc: str | None,
                            severity: str, is_anomaly: bool,
                            is_backlogged: bool,
                            created_at: str | None = None) -> dict:
    if is_backlogged:
        title = f"[OFFLINE/DELAYED] {title}" if title else "[OFFLINE/DELAYED]"

    payload = {'''

if target2 in code:
    code = code.replace(target2, replacement2)

with open('Obylon.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("Done")
