// Package paths centralizes every on-disk location obylonc reads or writes.
// These paths are deliberately kept identical to the ones the Python agent
// (Obylon.py) uses, so the CLI and the agent share the same vault, identity
// file, and log file without any IPC between them.
package paths

import (
	"os"
	"path/filepath"
	"runtime"
)

// ProgramDataDir returns the machine-wide data directory. On Windows this is
// %PROGRAMDATA% (falling back to C:\ProgramData, matching the agent's own
// os.environ.get('PROGRAMDATA', 'C:\\ProgramData') fallback). OBYLON_PROGRAMDATA
// overrides it, primarily for local development/testing off Windows.
func ProgramDataDir() string {
	if v := os.Getenv("OBYLON_PROGRAMDATA"); v != "" {
		return v
	}
	if v := os.Getenv("PROGRAMDATA"); v != "" {
		return v
	}
	if runtime.GOOS == "windows" {
		return `C:\ProgramData`
	}
	// Non-Windows dev fallback: a local, git-ignorable data dir so the CLI
	// is runnable end-to-end (minus the Windows-only vault crypto) without
	// touching real system paths.
	home, err := os.UserHomeDir()
	if err != nil {
		home = "."
	}
	return filepath.Join(home, ".obylon-dev", "programdata")
}

// ObylonDir is ProgramDataDir()/Obylon — where the vault, machine identity,
// and logs all live.
func ObylonDir() string {
	return filepath.Join(ProgramDataDir(), "Obylon")
}

// VaultFile is the DPAPI-encrypted config vault shared with the agent.
func VaultFile() string {
	return filepath.Join(ObylonDir(), "obylon.enc")
}

// VaultFallbackFile is where the vault is written if ObylonDir() isn't
// writable by the current user (e.g. a non-admin session) — mirrors the
// agent's own degraded-write fallback.
func VaultFallbackFile() string {
	return filepath.Join(HomeDir(), ".obylon_vault_fallback.enc")
}

// IdentityFile holds the machine-level hardware UUID (a random identifier
// minted once per machine, not a real hardware serial).
func IdentityFile() string {
	return filepath.Join(ObylonDir(), ".machine_id")
}

// LogDir is where the agent's structured log file lives.
func LogDir() string {
	return filepath.Join(ObylonDir(), "logs")
}

// LogFile is the agent's live log file (obylon.log).
func LogFile() string {
	return filepath.Join(LogDir(), "obylon.log")
}

// LegacyLogFile is the path the old Python CLI's support-bundle command
// looked for (C:\ProgramData\Obylon\agent.log). It never actually matched
// LogFile() above, so support bundles from the old CLI always reported "log
// file not found" — obylonc checks both, see cmd/ops.go.
func LegacyLogFile() string {
	return filepath.Join(ObylonDir(), "agent.log")
}

// HomeDir resolves the interactive user's home directory. OBYLON_USER_PROFILE
// (also honored by the agent, exported by its Session Broker) takes
// precedence so the CLI can be pointed at a specific student profile while
// troubleshooting; otherwise this is just the current process's home dir.
func HomeDir() string {
	if v := os.Getenv("OBYLON_USER_PROFILE"); v != "" {
		if info, err := os.Stat(v); err == nil && info.IsDir() {
			return v
		}
	}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		return home
	}
	return "."
}

// AliasFile stores an optional display-name override for this workstation.
func AliasFile() string {
	return filepath.Join(HomeDir(), ".obylon_alias")
}

// VaultDBFile is the local SQLite evidence queue used by the agent (not
// touched by any obylonc read command, but deactivate/reset-identity clean
// it up, matching the Python CLI).
func VaultDBFile() string {
	return filepath.Join(HomeDir(), ".obylon_vault.db")
}

// AIRateLimitFile tracks the local hourly message quota for `obylonc ai`.
func AIRateLimitFile() string {
	return filepath.Join(HomeDir(), ".obylon_ai_limit.json")
}

// ProgramFilesDir returns %ProgramFiles%, defaulting to the standard path.
func ProgramFilesDir() string {
	if v := os.Getenv("ProgramFiles"); v != "" {
		return v
	}
	return `C:\Program Files`
}

// DefaultBrokerExePath is where `obylonc boot enable` points the scheduled
// task by default. As of the Rust phase-1 split, the Session 0 supervisor
// is ObylonBroker.exe, a standalone binary — not the Python agent invoked
// with a "host" subcommand (that CLI surface was removed from Obylon.py
// entirely). Override with --exe or the OBYLON_BROKER_PATH env var if
// it's installed somewhere other than the default location.
func DefaultBrokerExePath() string {
	if v := os.Getenv("OBYLON_BROKER_PATH"); v != "" {
		return v
	}
	return filepath.Join(ProgramFilesDir(), "Obylon", "ObylonBroker.exe")
}

// DefaultCoreExePath / DefaultAgentExePath — the other two binaries
// `doctor` looks for by name (Toolhelp32 matches on exe basename, not
// full path).
func DefaultCoreExePath() string {
	return filepath.Join(ProgramFilesDir(), "Obylon", "ObylonCore.exe")
}

func DefaultAgentExePath() string {
	if v := os.Getenv("OBYLON_AGENT_PATH"); v != "" {
		return v
	}
	return filepath.Join(ProgramFilesDir(), "Obylon", "obylon.exe")
}

// PerfSnapshotFile / CorePerfSnapshotFile: both live under logs\, matching
// where ObylonCore.exe's own core_perf_snapshot.json already writes in
// this codebase (rust/core/src/main.rs) — Obylon.py's perf_snapshot.json
// was placed alongside it for the same reason, not some other default.
func PerfSnapshotFile() string {
	return filepath.Join(LogDir(), "perf_snapshot.json")
}

func CorePerfSnapshotFile() string {
	return filepath.Join(LogDir(), "core_perf_snapshot.json")
}

// CaptureDir is where ObylonCore.exe writes screenshot/webcam JPEGs for
// Obylon.py to read-then-delete. `doctor --fix` sweeps anything left
// behind past a safety threshold (the crash-before-read case — normal
// operation never leaves files here).
func CaptureDir() string {
	return filepath.Join(ObylonDir(), "capture")
}
