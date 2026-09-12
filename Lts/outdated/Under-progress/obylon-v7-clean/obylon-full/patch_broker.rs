fn ensure_acls(logger: &FileLogger) {
    use std::process::Command;
    use std::path::PathBuf;
    use std::env;
    let base = env::var("PROGRAMDATA").unwrap_or_else(|_| "C:\\ProgramData".to_string());
    let vault_dir = PathBuf::from(&base).join("Obylon");
    let files = vec!["obylon.enc", "identity_beacon.json", "fastlane_rules.json"];
    
    for f in files {
        let path = vault_dir.join(f);
        if !path.exists() {
            let _ = std::fs::File::create(&path);
        }
        let _ = Command::new("icacls")
            .arg(&path)
            .arg("/grant")
            .arg("Authenticated Users:(M)")
            .arg("/C")
            .output();
    }
}
