package cmd

// doctor.go: `obylonc doctor` — a fast health check by default, a CPU
// profile with --profile, and safe auto-repair with --fix.
//
// The CPU profile is deliberately built so doctor's own resource use
// during a long observation window is close to zero: it takes exactly two
// point-in-time samples (once at the start, once at the end) and diffs
// them, the same way Task Manager and every other real profiler measures
// CPU% — it does not poll continuously. See profileSleep() in
// doctor_profile.go for the one place this needs a little care (a long
// sleep still needs to notice Ctrl+C reasonably quickly).
//
// Two data sources feed the profile:
//   - Toolhelp32 + GetThreadTimes/GetThreadDescription (internal/platform)
//     costs ZERO added overhead in Python/Rust — pure external OS
//     introspection.
//   - perf_snapshot.json / core_perf_snapshot.json (both under
//     C:\ProgramData\Obylon\logs\) — written periodically by Obylon.py
//     and ObylonCore.exe themselves, because Toolhelp32 can't see inside
//     a single OS thread. Python's lexical/context/fsm/arbitration steps
//     all run on scan_loop's one thread; Rust's hook callback and
//     fast-lane window-check both run on Core's one UI thread. Where a
//     JSON breakdown exists for a given OS thread name, it REPLACES that
//     thread's single row with its sub-sections — see
//     mergeThreadBreakdown() in doctor_profile.go for exactly how that
//     avoids double counting.

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"obylonc/internal/paths"
	"obylonc/internal/platform"
	"obylonc/internal/ui"
)

// agentExeName is the built Python agent's own exe name.
const agentExeName = "obylon.exe"

var doctorProcessNames = []string{"ObylonBroker.exe", "ObylonCore.exe", agentExeName}

func runDoctor(args []string) int {
	fs, _, _ := newFlagSet("doctor")
	profileFlag := fs.String("profile", "", "run a CPU profile over the given duration (e.g. 60s, 20m) instead of the quick health check")
	fixFlag := fs.Bool("fix", false, "apply safe automatic repairs for anything the health check finds wrong")
	if err := fs.Parse(args); err != nil {
		return usageErr("doctor", err.Error())
	}

	ui.PrintBanner("S Y S T E M   D O C T O R")

	if *profileFlag != "" {
		dur, err := time.ParseDuration(*profileFlag)
		if err != nil {
			return usageErr("doctor", fmt.Sprintf("--profile duration %q is not valid (try 60s, 5m, 20m): %v", *profileFlag, err))
		}
		return runDoctorProfile(dur)
	}

	findings := runDoctorHealthCheck()

	if *fixFlag {
		applyDoctorFixes(findings)
	} else if hasFixable(findings) {
		fmt.Println()
		ui.Muted("Run `obylonc doctor --fix` to apply the safe repairs above automatically.")
	}

	return 0
}

type findingSeverity int

const (
	sevOK findingSeverity = iota
	sevInfo
	sevWarn
	sevError
)

type finding struct {
	severity findingSeverity
	message  string
	fixable  bool
	fix      func() error
	fixLabel string
}

func hasFixable(findings []finding) bool {
	for _, f := range findings {
		if f.fixable {
			return true
		}
	}
	return false
}

func runDoctorHealthCheck() []finding {
	var findings []finding

	ui.Step("PROCESSES")
	samples, _ := platform.SnapshotProcesses(doctorProcessNames)
	for _, s := range samples {
		if s.Found {
			ui.Success("%s running (pid %d, %d threads)", s.Name, s.PID, len(s.Threads))
		} else {
			ui.Error("%s is not running", s.Name)
			findings = append(findings, finding{
				severity: sevError,
				message:  fmt.Sprintf("%s is not running", s.Name),
				fixable:  false, // forcibly restarting enforcement on a live machine is a real action, not a safe auto-fix
			})
		}
	}

	ui.Step("BOOT TASK")
	bootOK, bootMsg := checkBootTask()
	if bootOK {
		ui.Success("%s", bootMsg)
	} else {
		ui.Warn("%s", bootMsg)
		findings = append(findings, finding{
			severity: sevWarn,
			message:  bootMsg,
			fixable:  true,
			fixLabel: "re-register the boot task against ObylonBroker.exe",
			fix:      func() error { return fixBootTask() },
		})
	}

	ui.Step("VAULT")
	if vaultOK, vaultMsg := checkVault(); vaultOK {
		ui.Success("%s", vaultMsg)
	} else {
		ui.Warn("%s", vaultMsg)
		findings = append(findings, finding{
			severity: sevWarn,
			message:  vaultMsg,
			fixable:  true,
			fixLabel: "repair vault directory permissions",
			fix:      func() error { return fixVaultACL() },
		})
	}

	ui.Step("EVIDENCE CAPTURE")
	orphans, orphanErr := countOrphanedCaptures()
	if orphanErr != nil {
		ui.Muted("could not check capture directory: %v", orphanErr)
	} else if orphans == 0 {
		ui.Success("no orphaned capture files")
	} else {
		msg := fmt.Sprintf("%d orphaned capture file(s) older than 1 hour (normal operation always deletes these — leftovers usually mean a crash before Python could read one)", orphans)
		ui.Warn("%s", msg)
		findings = append(findings, finding{
			severity: sevInfo,
			message:  msg,
			fixable:  true,
			fixLabel: "delete orphaned capture files",
			fix:      func() error { return fixOrphanedCaptures() },
		})
	}

	ui.Step("RECENT LOG ACTIVITY")
	checkLogFreshness("core.log")
	checkLogFreshness("broker.log")
	checkLogFreshness("obylon.log")

	ui.Step("PERF INSTRUMENTATION")
	checkPerfSnapshotFreshness("Python Brain", paths.PerfSnapshotFile())
	checkPerfSnapshotFreshness("Rust Core", paths.CorePerfSnapshotFile())

	fmt.Println()
	if len(findings) == 0 {
		ui.Success("No issues found.")
	} else {
		errCount, warnCount := 0, 0
		for _, f := range findings {
			switch f.severity {
			case sevError:
				errCount++
			case sevWarn, sevInfo:
				warnCount++
			}
		}
		ui.Warn("%d issue(s) found (%d need attention, %d fixable).", len(findings), errCount, warnCount)
	}
	return findings
}

func checkBootTask() (ok bool, message string) {
	out, err := exec.Command("schtasks", "/query", "/tn", bootTaskName, "/xml").CombinedOutput()
	if err != nil {
		return false, "boot task \"ObylonAgent\" is not registered"
	}
	text := strings.ToLower(string(out))
	if strings.Contains(text, "<enabled>false</enabled>") {
		return false, "boot task exists but is DISABLED"
	}
	if !strings.Contains(text, "obylonbroker.exe") {
		return false, "boot task exists but does not point at ObylonBroker.exe (stale target from before the Rust broker split?)"
	}
	if !strings.Contains(text, "<boottrigger>") || !strings.Contains(text, "<restartonfailure>") {
		return false, "boot task is missing boot-trigger or restart-recovery settings"
	}
	return true, "boot task is registered, enabled, targets ObylonBroker.exe, and has restart recovery"
}

func fixBootTask() error {
	return installBootTask(paths.DefaultBrokerExePath())
}

func checkVault() (ok bool, message string) {
	info, err := os.Stat(paths.VaultFile())
	if err != nil {
		if fallbackInfo, ferr := os.Stat(paths.VaultFallbackFile()); ferr == nil {
			return false, fmt.Sprintf("vault is in the degraded fallback location (%s, %d bytes) — primary path isn't writable", paths.VaultFallbackFile(), fallbackInfo.Size())
		}
		return false, fmt.Sprintf("no vault found at %s", paths.VaultFile())
	}
	return true, fmt.Sprintf("vault present at %s (%d bytes)", paths.VaultFile(), info.Size())
}

func fixVaultACL() error {
	dir := paths.ObylonDir()
	out, err := exec.Command("icacls", dir, "/grant", "Authenticated Users:(OI)(CI)M", "/T", "/C").CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s", strings.TrimSpace(string(out)))
	}
	return nil
}

func countOrphanedCaptures() (int, error) {
	entries, err := os.ReadDir(paths.CaptureDir())
	if err != nil {
		if os.IsNotExist(err) {
			return 0, nil
		}
		return 0, err
	}
	cutoff := time.Now().Add(-1 * time.Hour)
	count := 0
	for _, e := range entries {
		info, err := e.Info()
		if err != nil {
			continue
		}
		if info.ModTime().Before(cutoff) {
			count++
		}
	}
	return count, nil
}

func fixOrphanedCaptures() error {
	entries, err := os.ReadDir(paths.CaptureDir())
	if err != nil {
		return err
	}
	cutoff := time.Now().Add(-1 * time.Hour)
	var lastErr error
	removed := 0
	for _, e := range entries {
		info, err := e.Info()
		if err != nil {
			continue
		}
		if info.ModTime().Before(cutoff) {
			p := filepath.Join(paths.CaptureDir(), e.Name())
			if err := os.Remove(p); err != nil {
				lastErr = err
			} else {
				removed++
			}
		}
	}
	if lastErr != nil {
		return fmt.Errorf("removed %d, then hit an error: %w", removed, lastErr)
	}
	return nil
}

func checkLogFreshness(name string) {
	p := filepath.Join(paths.LogDir(), name)
	info, err := os.Stat(p)
	if err != nil {
		ui.Muted("%s: not found", name)
		return
	}
	age := time.Since(info.ModTime())
	switch {
	case age < 2*time.Minute:
		ui.Success("%s: last write %s ago", name, age.Round(time.Second))
	case age < 30*time.Minute:
		ui.Muted("%s: last write %s ago", name, age.Round(time.Minute))
	default:
		ui.Warn("%s: last write %s ago — stale, if the process is supposed to be running", name, age.Round(time.Minute))
	}
}

func checkPerfSnapshotFreshness(label, path string) {
	info, err := os.Stat(path)
	if err != nil {
		ui.Muted("%s perf snapshot: not found yet (writes every ~5s once the process is up)", label)
		return
	}
	age := time.Since(info.ModTime())
	if age < 15*time.Second {
		ui.Success("%s perf snapshot: updating normally (%s ago)", label, age.Round(time.Second))
	} else {
		ui.Warn("%s perf snapshot: stale (%s ago) — the writer thread may have stopped", label, age.Round(time.Second))
	}
}

func applyDoctorFixes(findings []finding) {
	fmt.Println()
	ui.Step("APPLYING FIXES")
	applied := 0
	for _, f := range findings {
		if !f.fixable {
			continue
		}
		spinner := ui.NewSpinner(f.fixLabel + "...")
		spinner.Start()
		if err := f.fix(); err != nil {
			spinner.Fail(fmt.Sprintf("%s: %v", f.fixLabel, err))
		} else {
			spinner.Success(f.fixLabel)
			applied++
		}
	}
	if applied == 0 {
		ui.Muted("Nothing fixable found.")
	}

	var needsAttention []string
	for _, f := range findings {
		if !f.fixable {
			needsAttention = append(needsAttention, f.message)
		}
	}
	if len(needsAttention) > 0 {
		fmt.Println()
		ui.Step("NEEDS ATTENTION (not auto-fixed)")
		for _, m := range needsAttention {
			ui.Warn("%s", m)
		}
		ui.Muted("These require a judgment call (e.g. restarting enforcement on a live machine) rather than a safe automatic repair.")
	}
}
