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
	"bytes"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"

	"obylonc/internal/identity"
	"obylonc/internal/paths"
	"obylonc/internal/platform"
	"obylonc/internal/ui"
)

// agentExeName is the built Python agent's own exe name.
const agentExeName = "obylon.exe"

var doctorProcessNames = []string{"ObylonBroker.exe", "ObylonCore.exe", agentExeName}

func runDoctor(args []string) int {
	fs, _, _ := newFlagSet("doctor")
	profileFlag := fs.String("profile", "", "profile CPU usage for a duration (e.g. 60s, 5m)")
	fixFlag := fs.Bool("fix", false, "apply only safe repairs from the standard health check")
	deepFlag := fs.Bool("deep", false, "run the full boot/dependency forensic scan without making changes")
	deepFixFlag := fs.Bool("deepfix", false, "run the full forensic scan and apply only safe repairs")
	yesFlag := fs.Bool("yes", false, "skip the repair confirmation prompt (useful for automation)")
	if err := fs.Parse(args); err != nil {
		return usageErr("doctor", err.Error())
	}
	if *deepFlag && *deepFixFlag {
		return usageErr("doctor", "choose either --deep or --deepfix, not both")
	}
	if *profileFlag != "" && (*deepFlag || *deepFixFlag || *fixFlag) {
		return usageErr("doctor", "--profile cannot be combined with repair or deep-diagnostic modes")
	}
	if *yesFlag && !(*fixFlag || *deepFixFlag) {
		return usageErr("doctor", "--yes only applies to --fix or --deepfix")
	}
	if (JSONMode() || QuietMode()) && (*fixFlag || *deepFixFlag) && !*yesFlag {
		return usageErr("doctor", "--json/--quiet repair mode requires --yes so it never blocks on interactive confirmation")
	}

	if JSONMode() {
		ui.SetQuiet(true)
	}
	ui.PrintCompactHeader("OBYLON DOCTOR", "Health, evidence, repair, and verification")
	mode := "health check"
	if *deepFixFlag {
		mode = "deep diagnostics + safe repair"
	} else if *deepFlag {
		mode = "deep diagnostics"
	} else if *fixFlag {
		mode = "health check + safe repair"
	} else if *profileFlag != "" {
		mode = "CPU profile"
	}
	ui.Info("Mode: %s", mode)

	if *deepFlag || *deepFixFlag {
		findings := finalizeFindings(runDeepDiagnostics())
		if JSONMode() && !*deepFixFlag {
			return emitDoctorJSON("deep", findings, false)
		}
		printDoctorSummary(findings, true)
		if len(findings) == 0 {
			return 0
		}
		if *deepFixFlag {
			if hasFixable(findings) && (*yesFlag || ui.Confirm(fmt.Sprintf("Apply %d safe repair(s) now?", countFixable(findings)))) {
				applyDoctorFixes(findings)
				return doctorPostFixScan()
			}
			ui.Muted("No repairs applied. Evidence was not changed.")
		}
		return 1
	}

	if *profileFlag != "" {
		dur, err := time.ParseDuration(*profileFlag)
		if err != nil {
			return usageErr("doctor", fmt.Sprintf("%q is not a valid duration (try 60s, 5m, 20m): %v", *profileFlag, err))
		}
		return runDoctorProfile(dur)
	}

	findings := finalizeFindings(runDoctorHealthCheck())
	if JSONMode() && !*fixFlag {
		return emitDoctorJSON(mode, findings, false)
	}
	printDoctorSummary(findings, false)
	if *fixFlag {
		if hasFixable(findings) {
			if *yesFlag || ui.Confirm(fmt.Sprintf("Apply %d safe repair(s) now?", countFixable(findings))) {
				applyDoctorFixes(findings)
			} else {
				ui.Muted("No repairs applied.")
			}
		}
	} else if hasFixable(findings) {
		ui.Hint("Run `obylonc doctor --fix` to repair safe findings, or `obylonc doctor --deep` for forensic evidence.")
	}
	if JSONMode() {
		return emitDoctorJSON(mode, findings, *fixFlag)
	}
	if len(findings) > 0 {
		return 1
	}
	return 0
}

func doctorPostFixScan() int {
	ui.Section("VERIFICATION")
	ui.Muted("Rechecking the boot chain after repairs…")
	findings := runDeepDiagnostics()
	printDoctorSummary(findings, true)
	if len(findings) == 0 {
		ui.Success("Repairs verified. Obylon is healthy.")
		return 0
	}
	ui.Warn("Some findings remain after repair. Review the evidence above.")
	return 1
}

func countFixable(findings []finding) int {
	count := 0
	for _, f := range findings {
		if f.fixable {
			count++
		}
	}
	return count
}

func printDoctorSummary(findings []finding, deep bool) {
	fmt.Println()
	if len(findings) == 0 {
		ui.PrintBox("RESULT", []string{ui.StatusOK("No actionable issues detected"), "All completed checks have supporting evidence."}, ui.Green)
		return
	}
	errors, warnings, fixes := 0, 0, 0
	for _, f := range findings {
		switch f.severity {
		case sevError:
			errors++
		case sevWarn, sevInfo:
			warnings++
		}
		if f.fixable {
			fixes++
		}
	}
	label := "HEALTH RESULT"
	if deep {
		label = "DEEP RESULT"
	}
	lines := []string{
		fmt.Sprintf("%s %d", ui.Red(ui.IconErr), errors),
		fmt.Sprintf("%s %d", ui.Yellow(ui.IconWarn), warnings),
		fmt.Sprintf("%s %d safe repair(s)", ui.Cyan(ui.IconInfo), fixes),
	}
	ui.PrintBox(label, lines, ui.Yellow)

	for _, f := range findings {
		status := ui.Yellow(ui.IconWarn)
		if f.severity == sevError {
			status = ui.Red(ui.IconErr)
		}
		if f.severity == sevInfo {
			status = ui.Cyan(ui.IconInfo)
		}
		ui.StatusLine(status, f.ID, f.message, ui.White)
		if f.Evidence != "" {
			ui.Hint("%s evidence: %s", f.ID, f.Evidence)
		}
		if f.Recommendation != "" {
			ui.Hint("%s next: %s", f.ID, f.Recommendation)
		}
	}
}

type findingSeverity int

const (
	sevOK findingSeverity = iota
	sevInfo
	sevWarn
	sevError
)

type finding struct {
	ID             string          `json:"id"`
	Category       string          `json:"category"`
	Severity       findingSeverity `json:"-"`
	Message        string          `json:"message"`
	Evidence       string          `json:"evidence,omitempty"`
	Impact         string          `json:"impact,omitempty"`
	Recommendation string          `json:"recommendation,omitempty"`
	Fixable        bool            `json:"fixable"`
	severity       findingSeverity
	message        string
	fixable        bool
	fix            func() error
	fixLabel       string
}

// doctorFindingJSON is the stable public schema. The internal repair callback
// and duplicated severity fields never leak into automation output.
type doctorFindingJSON struct {
	ID             string `json:"id"`
	Category       string `json:"category"`
	Severity       string `json:"severity"`
	Message        string `json:"message"`
	Evidence       string `json:"evidence,omitempty"`
	Impact         string `json:"impact,omitempty"`
	Recommendation string `json:"recommendation,omitempty"`
	Fixable        bool   `json:"fixable"`
}

func severityName(s findingSeverity) string {
	switch s {
	case sevError:
		return "error"
	case sevWarn:
		return "warning"
	case sevInfo:
		return "info"
	default:
		return "ok"
	}
}

func finalizeFindings(in []finding) []finding {
	out := make([]finding, len(in))
	copy(out, in)
	for i := range out {
		if out[i].ID == "" {
			out[i].ID = fmt.Sprintf("OBY-%04d", i+1)
		}
		out[i].Severity = out[i].severity
		out[i].Message = out[i].message
		out[i].Fixable = out[i].fixable
		if out[i].Recommendation == "" && out[i].fixable {
			out[i].Recommendation = out[i].fixLabel
		}
	}
	return out
}

func emitDoctorJSON(mode string, findings []finding, repaired bool) int {
	type report struct {
		Tool     string              `json:"tool"`
		Version  string              `json:"version"`
		Mode     string              `json:"mode"`
		Status   string              `json:"status"`
		Healthy  bool                `json:"healthy"`
		Repaired bool                `json:"repaired"`
		Findings []doctorFindingJSON `json:"findings"`
	}
	r := report{Tool: "obylonc doctor", Version: Version, Mode: mode, Status: "healthy", Healthy: len(findings) == 0, Repaired: repaired, Findings: make([]doctorFindingJSON, 0, len(findings))}
	if len(findings) > 0 {
		r.Status = "issues"
	}
	for _, f := range findings {
		r.Findings = append(r.Findings, doctorFindingJSON{ID: f.ID, Category: f.Category, Severity: severityName(f.severity), Message: f.message, Evidence: f.Evidence, Impact: f.Impact, Recommendation: f.Recommendation, Fixable: f.fixable})
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	_ = enc.Encode(r)
	if len(findings) == 0 {
		return 0
	}
	return 1
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
		return false, describeBootTaskQueryFailure(out, err)
	}
	return validateBootTaskDefinition(out)
}

type scheduledTaskDefinition struct {
	Triggers struct {
		BootTriggers []scheduledTaskBootTrigger `xml:"BootTrigger"`
	} `xml:"Triggers"`
	Principals struct {
		Principal struct {
			UserID   string `xml:"UserId"`
			RunLevel string `xml:"RunLevel"`
		} `xml:"Principal"`
	} `xml:"Principals"`
	Settings struct {
		Enabled                 string `xml:"Enabled"`
		MultipleInstancesPolicy string `xml:"MultipleInstancesPolicy"`
		RestartOnFailure        struct {
			Interval string `xml:"Interval"`
			Count    string `xml:"Count"`
		} `xml:"RestartOnFailure"`
	} `xml:"Settings"`
	Actions struct {
		Context string                    `xml:"Context,attr"`
		Execs   []scheduledTaskExecAction `xml:"Exec"`
	} `xml:"Actions"`
}

type scheduledTaskBootTrigger struct {
	Enabled string `xml:"Enabled"`
}

type scheduledTaskExecAction struct {
	Command string `xml:"Command"`
}

func validateBootTaskDefinition(raw []byte) (ok bool, message string) {
	text, err := decodeTaskSchedulerText(raw)
	if err != nil {
		return false, fmt.Sprintf("boot task definition could not be decoded: %v", err)
	}

	var definition scheduledTaskDefinition
	decoder := xml.NewDecoder(strings.NewReader(text))
	decoder.CharsetReader = func(_ string, input io.Reader) (io.Reader, error) {
		return input, nil
	}
	if err := decoder.Decode(&definition); err != nil {
		return false, fmt.Sprintf("boot task definition is invalid XML: %v", err)
	}

	if strings.EqualFold(strings.TrimSpace(definition.Settings.Enabled), "false") {
		return false, "boot task exists but is DISABLED"
	}
	if !hasEnabledBootTrigger(definition.Triggers.BootTriggers) {
		return false, "boot task is missing an enabled boot trigger"
	}
	if !strings.EqualFold(strings.TrimSpace(definition.Principals.Principal.UserID), "S-1-5-18") || !strings.EqualFold(strings.TrimSpace(definition.Principals.Principal.RunLevel), "HighestAvailable") {
		return false, "boot task does not run ObylonBroker as Local System at the required privilege level"
	}
	if !strings.EqualFold(strings.TrimSpace(definition.Settings.MultipleInstancesPolicy), "IgnoreNew") {
		return false, "boot task is missing duplicate-spawn prevention (MultipleInstancesPolicy=IgnoreNew)"
	}
	if strings.TrimSpace(definition.Settings.RestartOnFailure.Interval) == "" {
		return false, "boot task is missing restart-recovery interval settings"
	}
	restartCount, err := strconv.Atoi(strings.TrimSpace(definition.Settings.RestartOnFailure.Count))
	if err != nil || restartCount < 1 {
		return false, "boot task is missing a valid restart-recovery count"
	}
	if !hasBrokerAction(definition.Actions.Execs) {
		return false, "boot task does not point at ObylonBroker.exe under the Local System action context"
	}
	return true, "boot task is registered, enabled, runs ObylonBroker.exe as Local System, and has duplicate-spawn and restart recovery controls"
}

func hasEnabledBootTrigger(triggers []scheduledTaskBootTrigger) bool {
	for _, trigger := range triggers {
		if !strings.EqualFold(strings.TrimSpace(trigger.Enabled), "false") {
			return true
		}
	}
	return false
}

func hasBrokerAction(actions []scheduledTaskExecAction) bool {
	for _, action := range actions {
		if strings.EqualFold(windowsBaseName(action.Command), "obylonbroker.exe") {
			return true
		}
	}
	return false
}

func windowsBaseName(path string) string {
	path = strings.Trim(strings.TrimSpace(path), `"`)
	if index := strings.LastIndexAny(path, `\\/`); index >= 0 {
		return path[index+1:]
	}
	return path
}

func describeBootTaskQueryFailure(out []byte, commandErr error) string {
	text, err := decodeTaskSchedulerText(out)
	if err != nil || strings.TrimSpace(text) == "" {
		text = commandErr.Error()
	}
	text = strings.TrimSpace(text)
	lowerText := strings.ToLower(text)
	switch {
	case strings.Contains(lowerText, "access is denied"):
		return "Task Scheduler denied access while inspecting the Local System boot task; run `obylonc boot status` from an elevated Administrator terminal"
	case strings.Contains(lowerText, "cannot find the path specified"), strings.Contains(lowerText, "cannot find the file specified"), strings.Contains(lowerText, "not registered"):
		return "boot task is missing or its definition is unavailable to Task Scheduler; run `obylonc boot enable` from an elevated Administrator terminal"
	default:
		return fmt.Sprintf("could not query boot task: %s", text)
	}
}

func decodeTaskSchedulerText(raw []byte) (string, error) {
	if len(raw) == 0 {
		return "", nil
	}
	if bytes.HasPrefix(raw, []byte{0xff, 0xfe}) {
		return decodeUTF16TaskSchedulerText(raw[2:], true)
	}
	if bytes.HasPrefix(raw, []byte{0xfe, 0xff}) {
		return decodeUTF16TaskSchedulerText(raw[2:], false)
	}
	if looksLikeUTF16LE(raw) {
		return decodeUTF16TaskSchedulerText(raw, true)
	}
	if looksLikeUTF16BE(raw) {
		return decodeUTF16TaskSchedulerText(raw, false)
	}
	return string(raw), nil
}

func decodeUTF16TaskSchedulerText(raw []byte, littleEndian bool) (string, error) {
	if len(raw)%2 != 0 {
		return "", fmt.Errorf("UTF-16 data has an odd byte length")
	}
	codeUnits := make([]uint16, len(raw)/2)
	for index := range codeUnits {
		first := raw[index*2]
		second := raw[index*2+1]
		if littleEndian {
			codeUnits[index] = uint16(first) | uint16(second)<<8
		} else {
			codeUnits[index] = uint16(second) | uint16(first)<<8
		}
	}
	return string(utf16.Decode(codeUnits)), nil
}

func looksLikeUTF16LE(raw []byte) bool {
	return looksLikeUTF16(raw, 1)
}

func looksLikeUTF16BE(raw []byte) bool {
	return looksLikeUTF16(raw, 0)
}

func looksLikeUTF16(raw []byte, zeroOffset int) bool {
	if len(raw) < 8 {
		return false
	}
	sampleLength := len(raw)
	if sampleLength > 128 {
		sampleLength = 128
	}
	sampleLength -= sampleLength % 2
	zeroCount := 0
	for index := zeroOffset; index < sampleLength; index += 2 {
		if raw[index] == 0 {
			zeroCount++
		}
	}
	return zeroCount*4 >= sampleLength/2*3
}

func fixBootTask() error {
	hwUUID, _ := identity.LoadOrCreateHardwareUUID()
	target := map[string]interface{}{"hardware_uuid": hwUUID, "type": "device"}
	if !requireCLIActionAuthorization("obylon.boot.enable", target) {
		return fmt.Errorf("authorization denied")
	}
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
