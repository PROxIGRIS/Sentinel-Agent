# Obylon Sentinel 7.0.4-LTS

## Installer-integrated licensing

The installer now collects the license key and stable node name, then invokes the installed `obylonc activate` provisioning path before setup can report the endpoint as ready. The license key is handed through a temporary file rather than a process command-line argument. Boot-task registration occurs only after successful activation.

## Node identity

Activation accepts an explicit `--node-name` override and sends the same stable name through the enrollment payload. The Go CLI now persists both `NODE_NAME` and `WORKSTATION_NAME`, and the Python Brain falls back to `NODE_NAME` when older vaults have no `WORKSTATION_NAME`.

## CLI/admin scope

Every operational command is represented in the explicit admin registry with scope/action metadata. The `auth` namespace mirrors that registry, so commands such as `obylonc auth deactivate` resolve through the same admin path instead of a separately maintained shortcut list.

## Validation

- Python functional tests: 20/20 PASS
- Python source compilation: PASS
- Go tests: PASS
- Windows AMD64 Go build: PASS
- Installer contract static checks: PASS
- Actual Inno Setup compilation: not available in this Linux environment
- Real Windows installer/activation test: still required for final ship certification
