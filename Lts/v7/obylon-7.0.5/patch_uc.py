import sys
with open(r"src\brain\Obylon.py", "r", encoding="utf-8") as f:
    code = f.read()

OLD = """                if wid:
                    try:
                        response = client.table("workstations").update(payload).eq("id", wid).execute()
                    except Exception as update_error:
                        # Schema-compatible retry if the optional fingerprint column
                        # was expected but is absent/denied by the current backend.
                        if "hardware_fingerprint" in payload:
                            payload.pop("hardware_fingerprint", None)
                            response = client.table("workstations").update(payload).eq("id", wid).execute()
                        else:
                            raise update_error"""

NEW = """                if wid:
                    try:
                        response = client.table("workstations").update(payload).eq("id", wid).execute()
                    except Exception as update_error:
                        err_str = str(update_error)
                        if "23505" in err_str or "unique constraint" in err_str.lower():
                            # Reclaim hardware_uuid from old orphaned row to fix duplicate constraint
                            client.table("workstations").update({"hardware_uuid": None}).eq("hardware_uuid", HARDWARE_UUID).neq("id", wid).execute()
                            response = client.table("workstations").update(payload).eq("id", wid).execute()
                        elif "hardware_fingerprint" in payload:
                            payload.pop("hardware_fingerprint", None)
                            response = client.table("workstations").update(payload).eq("id", wid).execute()
                        else:
                            raise update_error"""

if OLD in code:
    code = code.replace(OLD, NEW)
    with open(r"src\brain\Obylon.py", "w", encoding="utf-8") as f:
        f.write(code)
    print("Patched!")
else:
    print("Could not find OLD block")

