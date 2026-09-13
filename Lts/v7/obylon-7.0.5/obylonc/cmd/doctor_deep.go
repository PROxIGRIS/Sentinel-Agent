package cmd

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"obylonc/internal/paths"
	"obylonc/internal/ui"
)

// runDeepDiagnostics performs a controlled forensic probe of the complete
// Windows boot chain. It never kills unrelated processes, and every claim is
// backed by an observed process, file, event, or exit code.
// Deep diagnostics deliberately reuse the doctor's finding model so the
// same evidence can be repaired by `doctor --deepfix` without maintaining two
// separate repair systems.
func runDeepDiagnostics() []finding {
	var findings []finding

	ui.Step("PLATFORM & PRIVILEGES")
	if strings.EqualFold(os.Getenv("OS"), "Windows_NT") {
		ui.Success("Windows environment detected")
	} else {
		findings = append(findings, finding{severity: sevError, message: "Obylon Windows diagnostics are running outside Windows", fixable: false})
	}
	if _, err := exec.LookPath("schtasks"); err != nil {
		findings = append(findings, finding{severity: sevError, message: "schtasks.exe is unavailable; Task Scheduler diagnostics cannot run", fixable: false})
	} else {
		ui.Success("Task Scheduler tooling available")
	}

	ui.Step("INSTALLATION PAYLOAD")
	required := []string{
		paths.DefaultBrokerExePath(),
		paths.DefaultCoreExePath(),
		paths.DefaultAgentExePath(),
	}
	for _, p := range required {
		if info, err := os.Stat(p); err != nil || info.IsDir() {
			missingPath := p
			findings = append(findings, finding{severity: sevError, message: fmt.Sprintf("Required executable missing or invalid: %s", missingPath), fixable: true, fixLabel: "reinstall Obylon payload", fix: func() error { return fmt.Errorf("reinstall required: %s", missingPath) }})
		} else {
			ui.Success("Found %s", p)
		}
	}

	ui.Step("DEPENDENCIES & LOADER")
	runtimeFindings := checkNativeDependencies()
	findings = append(findings, runtimeFindings...)
	if len(runtimeFindings) == 0 {
		ui.Success("Native runtime prerequisites are present")
	}

	ui.Step("BOOT TASK")
	if ok, msg := checkBootTask(); ok {
		ui.Success("%s", msg)
	} else {
		findings = append(findings, finding{severity: sevError, message: msg, fixable: true, fixLabel: "repair the ObylonAgent scheduled task", fix: func() error { return fixBootTask() }})
	}

	ui.Step("BROKER LOAD TEST")
	var brokerExit int
	var brokerErr error
	var brokerDetail string
	if processExists("ObylonBroker.exe") {
		ui.Success("ObylonBroker.exe is already running; skipping an intrusive second launch")
	} else {
		brokerExit, brokerErr, brokerDetail = launchAndObserve(paths.DefaultBrokerExePath(), 5*time.Second)
	}
	if brokerErr == nil {
		ui.Success("ObylonBroker.exe remained alive for the probe window (%s)", brokerDetail)
	} else {
		msg := fmt.Sprintf("ObylonBroker.exe failed before the runtime probe completed: %s", brokerDetail)
		if brokerExit >= 0 {
			msg += fmt.Sprintf(" [exit=%d / 0x%08X]", brokerExit, uint32(brokerExit))
		}
		findings = append(findings, finding{ID: "OBY-BROKER-START", Category: "boot.broker", severity: sevError, message: msg, Evidence: brokerDetail, Impact: "The broker cannot initialize the Obylon boot chain.", Recommendation: "Run `obylonc doctor --deep --verbose` and install any reported prerequisites.", fixable: false})
		if brokerExit == -1073741515 || uint32(brokerExit) == 0xC0000135 {
			findings = append(findings, finding{ID: "OBY-DEP-DLL", Category: "dependency.native", severity: sevError, message: "Windows loader returned 0xC0000135 (STATUS_DLL_NOT_FOUND). A required DLL/runtime is missing before ObylonBroker application logging can start.", Evidence: "ObylonBroker.exe exited before application initialization", Impact: "Core and Brain cannot start.", Recommendation: "Install/repair the required Microsoft Visual C++ Runtime or other missing native dependency.", fixable: false})
		}
		appendWindowsEventFindings(&findings, "ObylonBroker")
	}

	ui.Step("CORE / BRAIN BOOT CHAIN")
	if processExists("ObylonCore.exe") {
		ui.Success("ObylonCore.exe is running")
	} else if processExists("ObylonBroker.exe") {
		findings = append(findings, finding{severity: sevError, message: "ObylonBroker.exe is running but ObylonCore.exe is not; broker-to-core boot handoff failed or core exited", fixable: false})
	} else {
		ui.Muted("ObylonCore.exe is not running; broker is not confirmed alive")
	}
	if processExists(paths.DefaultAgentExePath()) || processExists("obylon.exe") {
		ui.Success("Python Brain (obylon.exe) is running")
	} else if processExists("ObylonCore.exe") {
		findings = append(findings, finding{severity: sevError, message: "ObylonCore.exe is running but obylon.exe is not; core-to-brain launch failed or Brain exited", fixable: false})
	} else {
		ui.Muted("Python Brain is not running; upstream boot stages are not confirmed healthy")
	}

	checkProducerLog(&findings, "core.log", []string{"ObylonCore.exe"})
	checkProducerLog(&findings, "broker.log", []string{"ObylonBroker.exe"})
	checkProducerLog(&findings, "obylon.log", []string{"obylon.exe"})

	ui.Step("PERF / HEARTBEAT EVIDENCE")
	checkProducerSnapshot(&findings, "Rust Core", paths.CorePerfSnapshotFile(), paths.DefaultCoreExePath())
	checkProducerSnapshot(&findings, "Python Brain", paths.PerfSnapshotFile(), paths.DefaultAgentExePath())

	ui.Step("WINDOWS LOADER / TASK HISTORY")
	appendTaskHistoryFindings(&findings)

	if len(findings) > 0 {
		ui.Section("EVIDENCE")
		for _, f := range findings {
			switch f.severity {
			case sevError:
				ui.Error("%s", f.message)
			case sevWarn:
				ui.Warn("%s", f.message)
			default:
				ui.Info("%s", f.message)
			}
		}
	}

	return findings
}

func checkNativeDependencies() []finding {
	var findings []finding
	checks := []struct {
		id, file, label, fix string
	}{
		{"OBY-VC-RUNTIME", `C:\Windows\System32\VCRUNTIME140.dll`, "Microsoft Visual C++ Runtime 2015–2022 (x64)", "Install Microsoft Visual C++ Redistributable 2015–2022 (x64)."},
		{"OBY-VC-RUNTIME-UCRT", `C:\Windows\System32\VCRUNTIME140_1.dll`, "Microsoft Visual C++ Runtime support (x64)", "Repair/install the Microsoft Visual C++ Redistributable 2015–2022 (x64)."},
	}
	for _, c := range checks {
		if info, err := os.Stat(c.file); err == nil && !info.IsDir() {
			ui.Success("%s present", c.label)
		} else {
			findings = append(findings, finding{ID: c.id, Category: "dependency.native", severity: sevError, message: fmt.Sprintf("%s is missing: %s", c.label, c.file), Evidence: "Required before native Obylon executables can load.", Impact: "ObylonBroker may fail at the Windows loader before any Obylon log is created.", Recommendation: c.fix, fixable: false, fixLabel: c.fix})
		}
	}
	if ok, detail := vcRuntimeInstalled(); ok {
		ui.Success("VC++ runtime registry registration detected")
		_ = detail
	} else {
		findings = append(findings, finding{ID: "OBY-VC-REG", Category: "dependency.native", severity: sevError, message: "Microsoft Visual C++ Redistributable x64 is not registered as installed.", Evidence: "VisualStudio\\14.0\\VC\\Runtimes\\x64 registry check failed.", Impact: "Native Obylon components may not load on a clean Windows installation.", Recommendation: "Install Microsoft Visual C++ Redistributable 2015–2022 (x64).", fixable: false, fixLabel: "install Microsoft Visual C++ Redistributable 2015–2022 (x64)"})
	}
	return dedupeFindings(findings)
}

func dedupeFindings(in []finding) []finding {
	seen := map[string]bool{}
	out := make([]finding, 0, len(in))
	for _, f := range in {
		key := f.Category + "|" + f.message
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, f)
	}
	return out
}

func vcRuntimeInstalled() (bool, string) {
	commands := [][]string{
		{"reg", "query", `HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64`, "/v", "Bld"},
		{"reg", "query", `HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64`, "/v", "Bld"},
	}
	for _, c := range commands {
		out, err := exec.Command(c[0], c[1:]...).CombinedOutput()
		if err == nil {
			line := strings.TrimSpace(string(out))
			if _, err := os.Stat(`C:\Windows\System32\VCRUNTIME140.dll`); err != nil {
				continue
			}
			return true, line
		}
	}
	return false, "not found in registry"
}

// launchAndObserve distinguishes "could not start" from "started and stayed
// alive". It intentionally does not capture stdout because GUI/subsystem
// binaries often have none; exit status is the evidence.
func launchAndObserve(exe string, wait time.Duration) (int, error, string) {
	cmd := exec.Command(exe)
	if err := cmd.Start(); err != nil {
		return -1, err, fmt.Sprintf("CreateProcess failed: %v", err)
	}
	pid := cmd.Process.Pid
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()

	t := time.NewTimer(wait)
	defer t.Stop()
	select {
	case err := <-done:
		if exitErr, ok := err.(*exec.ExitError); ok {
			return exitErr.ExitCode(), err, fmt.Sprintf("process %d exited immediately: %v", pid, err)
		}
		if err != nil {
			return -1, err, fmt.Sprintf("process %d exited: %v", pid, err)
		}
		return 0, fmt.Errorf("process exited early"), fmt.Sprintf("process %d exited with code 0 before the %s stability window", pid, wait)
	case <-t.C:
		// Leave a successfully started broker running. The diagnostic has now
		// proven the Windows loader can create it, and killing it would make a
		// healthy diagnostic command itself disrupt the endpoint.
		return 0, nil, fmt.Sprintf("process %d launched successfully and remained alive for %s", pid, wait)
	}
}

func checkProducerLog(findings *[]finding, name string, producers []string) {
	p := filepath.Join(paths.LogDir(), name)
	info, err := os.Stat(p)
	if err == nil {
		age := time.Since(info.ModTime())
		if age < 2*time.Minute {
			ui.Success("%s present and fresh (%s old)", name, age.Round(time.Second))
		} else {
			ui.Warn("%s exists but is stale (%s old)", name, age.Round(time.Second))
		}
		return
	}
	for _, producer := range producers {
		if processExists(producer) {
			*findings = append(*findings, finding{severity: sevWarn, message: fmt.Sprintf("%s is missing even though %s is running; logging path/initialization may be broken", name, producer), fixable: false})
			return
		}
	}
	ui.Muted("%s not present; its producer is not confirmed running", name)
}

func checkProducerSnapshot(findings *[]finding, label, snapshot, producer string) {
	info, err := os.Stat(snapshot)
	if err == nil {
		age := time.Since(info.ModTime())
		if age < 15*time.Second {
			ui.Success("%s snapshot is fresh (%s old)", label, age.Round(time.Second))
		} else {
			ui.Warn("%s snapshot is stale (%s old)", label, age.Round(time.Second))
		}
		return
	}
	if processExists(producer) {
		*findings = append(*findings, finding{severity: sevWarn, message: fmt.Sprintf("%s snapshot is missing while %s is running", label, filepath.Base(producer)), fixable: false})
	} else {
		ui.Muted("%s snapshot not present; producer is not running", label)
	}
}

func processExists(name string) bool {
	out, err := exec.Command("tasklist", "/FI", "IMAGENAME eq "+name, "/NH").CombinedOutput()
	return err == nil && strings.Contains(strings.ToLower(string(out)), strings.ToLower(name))
}

func appendWindowsEventFindings(findings *[]finding, needle string) {
	out, err := exec.Command("wevtutil", "qe", "Application", "/q:*[System[(TimeCreated[timediff(@SystemTime) <= 900000])]]", "/f:text", "/c:20").CombinedOutput()
	if err != nil {
		return
	}
	text := strings.ToLower(string(out))
	if strings.Contains(text, strings.ToLower(needle)) || strings.Contains(text, "sidebyside") || strings.Contains(text, "dll") || strings.Contains(text, "0xc0000135") {
		reader := bufio.NewScanner(strings.NewReader(string(out)))
		for reader.Scan() {
			line := strings.TrimSpace(reader.Text())
			lower := strings.ToLower(line)
			if strings.Contains(lower, strings.ToLower(needle)) || strings.Contains(lower, "0xc0000135") || strings.Contains(lower, "dll") || strings.Contains(lower, "sidebyside") {
				*findings = append(*findings, finding{severity: sevInfo, message: "Windows Application event evidence: " + line, fixable: false})
			}
		}
	}
}

func appendTaskHistoryFindings(findings *[]finding) {
	out, err := exec.Command("schtasks", "/query", "/tn", bootTaskName, "/v", "/fo", "list").CombinedOutput()
	if err != nil {
		return
	}
	text := string(out)
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(strings.ToLower(trimmed), "last result:") {
			parts := strings.SplitN(trimmed, ":", 2)
			if len(parts) == 2 {
				value := strings.TrimSpace(parts[1])
				if code, err := strconv.ParseInt(value, 10, 32); err == nil && code != 0 {
					*findings = append(*findings, finding{severity: sevError, message: fmt.Sprintf("Task Scheduler reports a non-zero last result: %s", value), fixable: false})
					if uint32(code) == 0xC0000135 {
						*findings = append(*findings, finding{severity: sevError, message: "Task result decodes to 0xC0000135 (STATUS_DLL_NOT_FOUND): Windows could not load a required DLL.", fixable: false})
					}
				}
			}
		}
	}
}
