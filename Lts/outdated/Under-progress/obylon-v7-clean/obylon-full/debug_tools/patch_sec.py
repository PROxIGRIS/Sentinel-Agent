import sys

with open('Obylon.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = 'logger.warning(f"Identity beacon write failed (Core\\' + '\\'s direct fast-lane reporting degrades to queue-only): {e}", component="identity")'
replacement = target + '''

        try:
            _core_ipc_call({"cmd": "brain_security_ready"})
            logger.info("Signaled security-ready to Core.", component="boot")
        except Exception as e:
            logger.error(f"Failed to signal security-ready to Core: {e}", component="boot")'''

if target in code and "brain_security_ready" not in code:
    code = code.replace(target, replacement)
    with open('Obylon.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print("Patched successfully.")
else:
    print("Could not find target or already patched.")
