import sys
with open(r"src\brain\Obylon.py", "r", encoding="utf-8") as f:
    code = f.read()
code = code.replace("logger.error(f\"Signature verify failed: {e}\", component=\"license\")", "logger.error(f\"Signature verify failed: {e}. Payload: {sign_payload.decode()}, Sig: {server_sig}\", component=\"license\")")
with open(r"src\brain\Obylon.py", "w", encoding="utf-8") as f:
    f.write(code)

