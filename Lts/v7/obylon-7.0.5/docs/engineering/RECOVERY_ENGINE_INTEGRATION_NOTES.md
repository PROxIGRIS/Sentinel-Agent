# Recovery Engine Integration Notes

The integration in `Obylon.py` is intentionally limited to places where the new engine has enough evidence to act safely.

## Wired now

- SessionManager client reconstruction / auth recovery
- sync daemon missing-client recovery
- Realtime connection health + fresh-token source
- identity readiness gate before Core `brain_security_ready`
- fail-closed signature verifier dependency check
- bounded watchdog thread recovery

## Deliberately not faked

- License recovery: the existing heartbeat is a loop, so it needs a one-shot operation with a real `VALID` post-condition before the engine should invoke it.
- Configuration reload: no arbitrary configuration action is registered.
- Identity reset: only the guarded relink plan exists in the engine; its facts must come from a trusted caller after same-machine + prior-license verification.

## Integration principle

The engine never receives a string such as `"run this command"`. It receives Python callables that already represent approved internal operations.
