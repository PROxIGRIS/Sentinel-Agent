// NOTE (2026-09): this file is a standalone dev scratch/patch snippet,
// not part of any crate build (it isn't under rust/broker/src/ and
// nothing mod-declares it) — kept here only as a record of what was
// most recently applied to rust/broker/src/main.rs's ensure_acls().
// Updated to match that fix (see FIXES_7.0.6_SECURITY_AUDIT.md #3) so
// it doesn't sit here as a stale, vulnerable copy someone might
// copy-paste from later.

fn ensure_acls(logger: &FileLogger) {
    use std::process::Command;
    use std::path::PathBuf;
    use std::env;
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    let vault_dir = PathBuf::from(&base).join("Obylon");

    let dirs = ["logs", "capture", "events"];
    for d in dirs {
        let path = vault_dir.join(d);
        if !path.exists() {
            let _ = std::fs::create_dir_all(&path);
        }
        match Command::new("icacls")
            .arg(&path)
            .arg("/grant")
            .arg("Authenticated Users:(OI)(CI)M")
            .arg("/C")
            .output()
        {
            Ok(o) if !o.status.success() => {
                let stderr = String::from_utf8_lossy(&o.stderr).to_string();
                logger.warn(
                    "acl",
                    "icacls grant on directory failed",
                    &[("dir", d), ("stderr", stderr.as_str())],
                );
            }
            Err(e) => {
                let err = e.to_string();
                logger.warn(
                    "acl",
                    "icacls could not be launched for directory",
                    &[("dir", d), ("error", err.as_str())],
                );
            }
            _ => {}
        }
    }

    let files = [
        "obylon.enc",
        "identity_beacon.json",
        "fastlane_rules.json",
        "node_binding.json",
        "node_name",
        ".machine_id",
        "recovery_journal.json",
    ];
    for f in files {
        let path = vault_dir.join(f);
        if !path.exists() {
            let _ = std::fs::File::create(&path);
        }
        match Command::new("icacls")
            .arg(&path)
            .arg("/grant")
            .arg("Authenticated Users:(M)")
            .arg("/C")
            .output()
        {
            Ok(o) if !o.status.success() => {
                let stderr = String::from_utf8_lossy(&o.stderr).to_string();
                logger.warn(
                    "acl",
                    "icacls grant on file failed",
                    &[("file", f), ("stderr", stderr.as_str())],
                );
            }
            Err(e) => {
                let err = e.to_string();
                logger.warn(
                    "acl",
                    "icacls could not be launched for file",
                    &[("file", f), ("error", err.as_str())],
                );
            }
            _ => {}
        }
    }
}
