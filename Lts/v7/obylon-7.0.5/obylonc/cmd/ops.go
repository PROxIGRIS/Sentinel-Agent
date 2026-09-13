package cmd

import (
	"bufio"
	"bytes"
	"fmt"
	"html"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"

	"obylonc/internal/identity"
	"obylonc/internal/paths"
	"obylonc/internal/ui"
	"obylonc/internal/vault"
)

// ---------------------------------------------------------------------
// logs
// ---------------------------------------------------------------------

func runLogs(args []string) int {
	fs, _, _ := newFlagSet("logs")
	lines := fs.Int("lines", 50, "number of trailing lines to print initially")
	fs.IntVar(lines, "n", 50, "alias for --lines")
	follow := fs.Bool("follow", false, "keep streaming new lines as they're written") // SSOT/Google-tier fix: Default to TRUE as expected by users
	fs.BoolVar(follow, "f", false, "alias for --follow")
	level := fs.String("level", "", "filter by level: info, warning, or error")
	grep := fs.String("grep", "", "only show lines containing this text")
	noColor := fs.Bool("no-color", false, "strip ANSI color codes from output")
	deep := fs.Bool("deep", false, "translate broker + core + brain logs into a human-readable boot story")
	fs.BoolVar(deep, "d", false, "alias for --deep")
	file := fs.String("file", "", "path to a specific log file (default: the agent's live log)")
	if err := fs.Parse(args); err != nil {
		return usageErr("logs", err.Error())
	}

	path := *file
	if path == "" {
		path = resolveLogPath()
	}
	if path == "" {
		ui.Error("no log file found. Checked:")
		fmt.Println("  " + paths.LogFile())
		fmt.Println("  " + paths.LegacyLogFile())
		ui.Muted("Pass --file <path> to point at a specific log file.")
		return 1
	}

	if *noColor {
		ui.DisableColor()
	}

	if *deep {
		return runDeepLogs(*lines, *grep)
	}

	fmt.Println(ui.Dim(ui.IconArrow + " streaming " + path))
	if *follow {
		fmt.Println(ui.Dim("  press Ctrl+C to stop"))
	}
	fmt.Println()

	stop := make(chan struct{})
	if *follow {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, os.Interrupt)
		go func() {
			<-sigCh
			close(stop)
		}()
	}

	if err := tailLogFile(tailOptions{
		Path:    path,
		Lines:   *lines,
		Follow:  *follow,
		NoColor: *noColor,
		Level:   *level,
		Grep:    *grep,
	}, os.Stdout, stop); err != nil {
		ui.Error("could not read log file: %v", err)
		return 1
	}
	return 0
}

// ---------------------------------------------------------------------
// Human-readable forensic log translation
// ---------------------------------------------------------------------
// Raw broker/core logs remain untouched. `obylonc logs --deep` is a CLI-only
// interpretation layer that merges the independent streams by timestamp and
// explains what each event means. It also assigns stable Obylon diagnostic
// codes to important failure classes without changing the source logs.

type translatedLogEvent struct {
	When        time.Time
	Source      string
	Level       string
	Component   string
	Message     string
	Fields      map[string]string
	Raw         string
	Code        string
	Explanation string
}

var rawRustLogRE = regexp.MustCompile(`^\[([0-9]+(?:\.[0-9]+)?)\]\s+([A-Z]+)\s+\[([^]]+)\]\s+(.*)$`)
var pythonLogRE = regexp.MustCompile(`^\[(\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\]\s+([✖⚠ℹ])\s+\[([^]]+)\]\s+(.*)$`)
var kvRE = regexp.MustCompile(`([A-Za-z_][A-Za-z0-9_.-]*)=([^\s]+)`)

func parseBrainTimestamp(raw string) time.Time {
	formats := []string{"15:04:05.000000", "15:04:05.000", "15:04:05"}
	for _, layout := range formats {
		if t, err := time.ParseInLocation(layout, raw, time.Local); err == nil {
			now := time.Now()
			result := time.Date(now.Year(), now.Month(), now.Day(), t.Hour(), t.Minute(), t.Second(), t.Nanosecond(), time.Local)
			if result.After(now.Add(12 * time.Hour)) {
				result = result.Add(-24 * time.Hour)
			}
			return result
		}
	}
	return time.Now()
}

func runDeepLogs(lines int, grep string) int {
	if lines <= 0 {
		lines = 120
	}
	ui.PrintCompactHeader("OBYLON LOG STORY", "Human-readable reconstruction of the boot and runtime chain")
	candidates := []struct{ name, path string }{
		{"Broker", paths.BrokerLogFile()},
		{"Core", paths.CoreLogFile()},
		{"Brain", paths.LogFile()},
	}
	var events []translatedLogEvent
	for _, c := range candidates {
		ls, err := readLastLogLines(c.path, lines)
		if err != nil {
			continue
		}
		for _, raw := range ls {
			if grep != "" && !strings.Contains(strings.ToLower(raw), strings.ToLower(grep)) {
				continue
			}
			if e, ok := translateLogLine(c.name, raw); ok {
				events = append(events, e)
			}
		}
	}
	if len(events) == 0 {
		ui.Warn("No readable events were found in broker/core/brain logs.")
		ui.Muted("That itself is useful evidence: use `obylonc doctor --deep` for Windows loader and Task Scheduler evidence.")
		return 1
	}
	sort.SliceStable(events, func(i, j int) bool { return events[i].When.Before(events[j].When) })
	if len(events) > lines*3 {
		events = events[len(events)-lines*3:]
	}
	ui.Section("WHAT HAPPENED")
	for _, e := range events {
		timeText := e.When.Local().Format("2006-01-02 15:04:05")
		prefix := ui.Dim(timeText) + " " + sourceBadge(e.Source) + " "
		message := e.Message
		if e.Code != "" {
			message += " " + ui.Dim("["+e.Code+"]")
		}
		if e.Level == "ERROR" {
			ui.Error("%s%s", prefix, message)
		} else if e.Level == "WARN" {
			ui.Warn("%s%s", prefix, message)
		} else {
			fmt.Println(prefix + message)
		}
		if e.Explanation != "" {
			fmt.Println("  " + ui.Dim("↳ "+e.Explanation))
		}
	}
	printDeepLogSummary(events)
	return deepLogExit(events)
}

func sourceBadge(source string) string {
	switch strings.ToLower(source) {
	case "broker":
		return ui.Bold("BROKER")
	case "core":
		return ui.Bold("CORE")
	case "brain":
		return ui.Bold("BRAIN")
	default:
		return ui.Bold(strings.ToUpper(source))
	}
}

func translateLogLine(source, raw string) (translatedLogEvent, bool) {
	clean := stripANSICodes(raw)
	if pm := pythonLogRE.FindStringSubmatch(clean); len(pm) == 5 {
		when := parseBrainTimestamp(pm[1])
		level := "INFO"
		switch pm[2] {
		case "✖":
			level = "ERROR"
		case "⚠":
			level = "WARN"
		}
		component := pm[3]
		rest := pm[4]
		fields := map[string]string{}
		for _, kv := range kvRE.FindAllStringSubmatch(rest, -1) {
			if len(kv) == 3 {
				fields[kv[1]] = kv[2]
			}
		}
		message := strings.TrimSpace(kvRE.ReplaceAllString(rest, ""))
		code, explanation := classifyDiagnosticEvent(source, component, message, fields)
		return translatedLogEvent{When: when, Source: source, Level: level, Component: component, Message: humanizeMessage(message, fields), Fields: fields, Raw: raw, Code: code, Explanation: explanation}, true
	}
	m := rawRustLogRE.FindStringSubmatch(clean)
	if len(m) != 5 {
		// Unknown legacy format. Preserve it, but make the uncertainty explicit.
		return translatedLogEvent{When: time.Now(), Source: source, Level: "INFO", Message: strings.TrimSpace(clean), Raw: raw, Explanation: "Unrecognized log format; timestamp could not be reconstructed reliably."}, true
	}
	seconds, err := strconv.ParseFloat(m[1], 64)
	if err != nil {
		return translatedLogEvent{}, false
	}
	ns := int64(seconds * 1e9)
	when := time.Unix(0, ns)
	level := strings.ToUpper(m[2])
	component := m[3]
	rest := m[4]
	fields := map[string]string{}
	for _, kv := range kvRE.FindAllStringSubmatch(rest, -1) {
		if len(kv) == 3 {
			fields[kv[1]] = kv[2]
		}
	}
	message := kvRE.ReplaceAllString(rest, "")
	message = strings.TrimSpace(regexp.MustCompile(`\s{2,}`).ReplaceAllString(message, " "))
	code, explanation := classifyDiagnosticEvent(source, component, message, fields)
	return translatedLogEvent{When: when, Source: source, Level: level, Component: component, Message: humanizeMessage(message, fields), Fields: fields, Raw: raw, Code: code, Explanation: explanation}, true
}

func humanizeMessage(message string, fields map[string]string) string {
	switch message {
	case "Session Broker online — waiting for an interactive console session":
		return "Broker started and is waiting for a user session."
	case "Privileges enabled":
		return "Broker enabled the privileges it needs to manage the interactive session."
	case "core spawned into interactive session":
		if pid := fields["pid"]; pid != "" {
			return "Broker launched Obylon Core (PID " + pid + ")."
		}
		return "Broker launched Obylon Core."
	case "ObylonCore starting":
		return "Core started."
	case "another Core instance already owns the endpoint":
		return "Core refused to start because another Core instance already owns the endpoint."
	case "session spawn failed":
		return "Broker tried to launch Core but Windows rejected the session launch."
	case "another broker instance is already active":
		return "A broker is already running, so this duplicate instance exited."
	case "could not create Core ownership job":
		return "Broker could not create the Windows job object used to supervise Core."
	case "could not assign Core to its ownership job; refusing unmanaged Core":
		return "Core started, but Broker refused to leave it unmanaged and terminated it."
	case "stopping managed Core process tree":
		return "Broker stopped the managed Core process tree."
	default:
		return message
	}
}

func classifyDiagnosticEvent(source, component, message string, fields map[string]string) (string, string) {
	lower := strings.ToLower(message)
	if strings.Contains(lower, "session spawn failed") {
		return "OBY-BOOT-CORE-SPAWN", "The Broker reached the Core handoff but Windows rejected the process creation step."
	}
	if strings.Contains(lower, "core spawned") {
		return "OBY-BOOT-CORE-START", "The Broker successfully handed the interactive session to Core."
	}
	if strings.Contains(lower, "obyloncore starting") {
		return "OBY-CORE-START", "Core entered application initialization."
	}
	if strings.Contains(lower, "another core instance") {
		return "OBY-CORE-DUPLICATE", "Core did not take ownership because another instance already holds the global mutex."
	}
	if strings.Contains(lower, "privileges enabled") {
		return "OBY-BROKER-PRIV", "Broker completed its privilege setup."
	}
	if strings.Contains(lower, "cannot open any broker log path") || strings.Contains(lower, "cannot open core log path") {
		return "OBY-LOG-INIT", "The process could not create/open its log file, so later application failures may be invisible."
	}
	if strings.Contains(lower, "0xc0000135") || strings.Contains(lower, "dll") && strings.Contains(lower, "missing") {
		return "OBY-WIN-DLL-MISSING", "Windows could not load a required native DLL. This happens before normal application logging."
	}
	if code := fields["exit_code"]; code != "" {
		if decoded, ok := decodeWindowsExitCode(code); ok {
			return decoded.code, decoded.explanation
		}
	}
	if strings.Contains(lower, "failed") || strings.Contains(lower, "error") || fields["error"] != "" {
		return "OBY-RUNTIME-ERROR", "The component reported a runtime failure; inspect the raw fields and Windows Event Log for the underlying system error."
	}
	return "", ""
}

type decodedExit struct{ code, explanation string }

func decodeWindowsExitCode(raw string) (decodedExit, bool) {
	v := strings.TrimSpace(raw)
	var n uint64
	var err error
	if strings.HasPrefix(strings.ToLower(v), "0x") {
		n, err = strconv.ParseUint(v[2:], 16, 32)
	} else {
		n, err = strconv.ParseUint(v, 10, 32)
	}
	if err != nil {
		return decodedExit{}, false
	}
	switch uint32(n) {
	case 0xC0000135:
		return decodedExit{"OBY-WIN-DLL-MISSING", "Windows loader status 0xC0000135 means a required DLL/runtime was not found."}, true
	case 0xC000007B:
		return decodedExit{"OBY-WIN-BAD-IMAGE", "Windows loader status 0xC000007B usually means the executable or one of its DLLs has the wrong architecture or is invalid."}, true
	case 0xC0000142:
		return decodedExit{"OBY-WIN-DLL-INIT", "Windows status 0xC0000142 means a required DLL failed during initialization."}, true
	case 0xC0000005:
		return decodedExit{"OBY-WIN-ACCESS", "Windows status 0xC0000005 means the process hit an access violation."}, true
	case 78:
		return decodedExit{"OBY-SECURITY-HOLD", "Obylon Core reports its Brain stopped after a terminal security decision; automatic restart is intentionally disabled."}, true
	default:
		return decodedExit{"OBY-WIN-EXIT-UNKNOWN", fmt.Sprintf("Windows/native component exited with code %s (0x%08X); see Windows Event Log for the authoritative explanation.", raw, uint32(n))}, true
	}
}

func printDeepLogSummary(events []translatedLogEvent) {
	ui.Section("STORY SUMMARY")
	startedBroker, startedCore, errs := false, false, 0
	for _, e := range events {
		if e.Source == "Broker" && strings.Contains(strings.ToLower(e.Message), "broker started") {
			startedBroker = true
		}
		if e.Source == "Core" && strings.Contains(strings.ToLower(e.Message), "core started") {
			startedCore = true
		}
		if e.Level == "ERROR" {
			errs++
		}
	}
	if startedBroker {
		ui.Success("Broker startup is evidenced in the timeline.")
	} else {
		ui.Warn("Broker startup is not evidenced in the available logs.")
	}
	if startedCore {
		ui.Success("Core startup is evidenced in the timeline.")
	} else {
		ui.Warn("Core startup is not evidenced in the available logs.")
	}
	if errs > 0 {
		ui.Error("%d error event(s) are present in the reconstructed timeline.", errs)
	} else {
		ui.Success("No ERROR-level events were found in the selected logs.")
	}
}

func deepLogExit(events []translatedLogEvent) int {
	for _, e := range events {
		if e.Level == "ERROR" {
			return 2
		}
	}
	return 0
}

// resolveLogPath checks the agent's real log location first, then the path
// the OLD Python CLI's support-bundle command looked for (which never
// actually matched anything — see paths.LegacyLogFile), then a couple of
// relative fallbacks for running obylonc from a working copy of the agent.
func resolveLogPath() string {
	candidates := []string{
		paths.LogFile(),
		paths.LegacyLogFile(),
		filepath.Join(".", "obylon_logs", "obylon.log"),
		filepath.Join(".", ".obylon_logs", "obylon.log"),
	}
	for _, c := range candidates {
		if info, err := os.Stat(c); err == nil && !info.IsDir() {
			return c
		}
	}
	return ""
}

// ---------------------------------------------------------------------
// support-bundle
// ---------------------------------------------------------------------

func runSupportBundle(args []string) int {
	fs, _, _ := newFlagSet("support-bundle")
	if err := fs.Parse(args); err != nil {
		return usageErr("support-bundle", err.Error())
	}
	hwUUID, _ := identity.LoadOrCreateHardwareUUID()
	target := map[string]interface{}{"hardware_uuid": hwUUID, "type": "device", "operation": "support-bundle"}
	if !requireCLIActionAuthorization("obylon.evidence.read", target) {
		return 1
	}

	sp := ui.NewSpinner("Gathering diagnostics…")
	sp.Start()

	v := vault.New()
	_, _ = v.Load()

	hwFingerprint := identity.HardwareFingerprint()

	filename := fmt.Sprintf("obylon-support-%s.txt", time.Now().Format("20060102-150405"))

	var b strings.Builder
	b.WriteString("--- OBYLON SUPPORT BUNDLE ---\n")
	fmt.Fprintf(&b, "Timestamp: %s\n", time.Now().UTC().Format(time.RFC3339))
	fmt.Fprintf(&b, "Version: %s\n", Version)
	fmt.Fprintf(&b, "OS: %s/%s\n", runtime.GOOS, runtime.GOARCH)
	fmt.Fprintf(&b, "Hardware UUID: %s\n", redactIdentifier(hwUUID))
	fmt.Fprintf(&b, "Hardware Fingerprint: %s\n", redactIdentifier(hwFingerprint))
	b.WriteString("\n--- VAULT STATUS ---\n")
	fmt.Fprintf(&b, "License ID: %s\n", redactIdentifier(v.Get("LICENSE_ID")))
	fmt.Fprintf(&b, "Node ID: %s\n", redactIdentifier(v.Get("NODE_ID")))
	fmt.Fprintf(&b, "License Status: %s\n", v.Get("LICENSE_STATUS"))
	fmt.Fprintf(&b, "Last Heartbeat OK: %s\n", v.Get("LAST_HEARTBEAT_OK_AT"))
	fmt.Fprintf(&b, "Grace Days: %s\n", v.Get("GRACE_DAYS"))

	b.WriteString("\n--- LOG EXTRACT (last 100 lines) ---\n")
	logCandidates := []string{paths.LogFile(), filepath.Join(paths.LogDir(), "broker.log"), filepath.Join(paths.LogDir(), "core.log")}
	foundLogs := 0
	for _, logPath := range logCandidates {
		if info, statErr := os.Stat(logPath); statErr != nil || info.IsDir() {
			continue
		}
		foundLogs++
		fmt.Fprintf(&b, "\n[%s]\n", filepath.Base(logPath))
		if logLines, err := readLastLogLines(logPath, 100); err != nil {
			fmt.Fprintf(&b, "Could not read log file: %v\n", err)
		} else {
			for _, l := range logLines {
				b.WriteString(redactSupportLine(l) + "\n")
			}
		}
	}
	if foundLogs == 0 {
		b.WriteString("No Obylon logs were present. This is itself diagnostic evidence: capture Windows Event Log/task history.\n")
	}

	if err := os.WriteFile(filename, []byte(b.String()), 0o644); err != nil {
		sp.Fail(fmt.Sprintf("Could not write support bundle: %v", err))
		return 1
	}

	sp.Success(fmt.Sprintf("Support bundle written to %s", filename))
	fmt.Println("Please attach this file when contacting Obylon Support.")
	return 0
}

func redactIdentifier(value string) string {
	value = strings.TrimSpace(value)
	if len(value) <= 8 {
		if value == "" {
			return "<none>"
		}
		return "••••"
	}
	return "••••" + value[len(value)-8:]
}

func redactSupportLine(line string) string {
	// Support bundles are meant to cross the support boundary. Remove common
	// token/key forms while preserving the surrounding diagnostic evidence.
	patterns := []*regexp.Regexp{
		regexp.MustCompile(`(?i)(access_token|refresh_token|authorization|bearer|api[_-]?key|server_sig)\s*[:=]\s*[^\s,;]+`),
	}
	out := line
	for _, re := range patterns {
		out = re.ReplaceAllStringFunc(out, func(m string) string {
			idx := strings.IndexAny(m, ":=")
			if idx < 0 {
				return m
			}
			return m[:idx+1] + " <redacted>"
		})
	}
	return out
}

// ---------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------

const bootTaskName = "ObylonAgent"

func bootTaskXML(brokerPath string) string {
	escapedPath := html.EscapeString(brokerPath)
	return fmt.Sprintf(`<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>Umbraxis</Author><Description>Obylon Session Broker</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
  <Principals><Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="System"><Exec><Command>%s</Command></Exec></Actions>
</Task>`, escapedPath)
}

func utf16LEWithBOM(value string) []byte {
	encoded := utf16.Encode([]rune(value))
	bytes := make([]byte, 2+len(encoded)*2)
	bytes[0], bytes[1] = 0xff, 0xfe
	for index, codeUnit := range encoded {
		bytes[2+index*2] = byte(codeUnit)
		bytes[2+index*2+1] = byte(codeUnit >> 8)
	}
	return bytes
}

func installBootTask(appPath string) error {
	appPath, err := filepath.Abs(appPath)
	if err != nil {
		return fmt.Errorf("resolve broker path: %w", err)
	}
	info, err := os.Stat(appPath)
	if err != nil {
		return fmt.Errorf("broker executable is not available at %s: %w", appPath, err)
	}
	if info.IsDir() {
		return fmt.Errorf("broker executable path is a directory: %s", appPath)
	}

	taskFile, err := os.CreateTemp("", "obylon-boot-task-*.xml")
	if err != nil {
		return fmt.Errorf("create temporary task definition: %w", err)
	}
	taskFileName := taskFile.Name()
	defer os.Remove(taskFileName)

	if _, err := taskFile.Write(utf16LEWithBOM(bootTaskXML(appPath))); err != nil {
		taskFile.Close()
		return fmt.Errorf("write temporary task definition: %w", err)
	}
	if err := taskFile.Close(); err != nil {
		return fmt.Errorf("close temporary task definition: %w", err)
	}

	out, err := exec.Command("schtasks", "/create", "/tn", bootTaskName, "/xml", taskFileName, "/f").CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s", strings.TrimSpace(string(out)))
	}
	if ok, message := checkBootTask(); !ok {
		return fmt.Errorf("task registration verification failed: %s", message)
	}
	return nil
}

func runBoot(args []string) int {
	fs, _, _ := newFlagSet("boot")
	exePath := fs.String("exe", "", "override the broker executable path used by the scheduled task")
	if err := fs.Parse(args); err != nil {
		return usageErr("boot", err.Error())
	}
	positional := fs.Args()
	if len(positional) == 0 {
		return usageErr("boot", "an action is required: status, enable, or disable")
	}
	action := positional[0]
	if action != "status" && action != "enable" && action != "disable" {
		return usageErr("boot", fmt.Sprintf("unknown action %q — expected status, enable, or disable", action))
	}

	if runtime.GOOS != "windows" {
		ui.Error("boot task management is only available on Windows (it drives schtasks.exe)")
		return 1
	}

	appPath := *exePath
	if appPath == "" {
		appPath = paths.DefaultBrokerExePath()
	}

	switch action {
	case "status":
		if ok, message := checkBootTask(); ok {
			ui.Success("%s", message)
		} else {
			ui.Error("%s", message)
		}
		return 0
	case "enable":
		hwUUID, _ := identity.LoadOrCreateHardwareUUID()
		target := map[string]interface{}{"hardware_uuid": hwUUID, "type": "device"}
		if !requireCLIActionAuthorization("obylon.boot.enable", target) {
			return 1
		}
		if err := installBootTask(appPath); err != nil {
			ui.Error("Failed to enable boot task: %v", err)
			ui.Muted("Are you running the terminal as Administrator?")
			return 1
		}
		ui.Success("Successfully ENABLED Obylon to run on boot with restart recovery.")
		return 0
	case "disable":
		hwUUID, _ := identity.LoadOrCreateHardwareUUID()
		target := map[string]interface{}{"hardware_uuid": hwUUID, "type": "device"}
		if !requireCLIActionAuthorization("obylon.boot.disable", target) {
			return 1
		}
		out, err := exec.Command("schtasks", "/change", "/tn", bootTaskName, "/disable").CombinedOutput()
		if err != nil {
			ui.Error("Failed to disable boot task: %s", strings.TrimSpace(string(out)))
			ui.Muted("It might not exist, or you're not running as Administrator.")
			return 1
		}
		ui.Success("Successfully DISABLED Obylon from running on boot.")
	}
	return 0
}

// ---------------------------------------------------------------------
// Log tailing (folded in from what was a standalone internal/logtail
// package — its only caller was this file, so the extra package boundary
// wasn't earning its keep). The log file already contains ANSI-colored,
// pre-rendered lines (the agent's structlog renderer writes the same
// colorized text to console and to disk), so this mostly just filters and
// re-emits lines rather than reformatting them.
// ---------------------------------------------------------------------

// tailOptions configures a tailLogFile call.
type tailOptions struct {
	Path    string        // log file to read
	Lines   int           // how many trailing lines to print initially (default 50)
	Follow  bool          // keep watching for new lines after the initial tail
	NoColor bool          // strip ANSI codes before printing
	Level   string        // "", "info", "warning", or "error"/"critical" — filters by rendered icon
	Grep    string        // simple substring filter
	Poll    time.Duration // follow-mode poll interval (default 400ms)
}

// tailLogFile prints the last opts.Lines lines of opts.Path, then — if
// opts.Follow is set — blocks, streaming new lines to out until stop is
// closed or an unrecoverable error occurs.
func tailLogFile(opts tailOptions, out io.Writer, stop <-chan struct{}) error {
	if opts.Lines <= 0 {
		opts.Lines = 50
	}
	if opts.Poll <= 0 {
		opts.Poll = 400 * time.Millisecond
	}

	lines, size, err := readTrailingLines(opts.Path, opts.Lines)
	if err != nil {
		return err
	}
	for _, line := range lines {
		emitLogLine(out, line, opts)
	}
	if !opts.Follow {
		return nil
	}
	return followLogFile(opts.Path, size, out, opts, stop)
}

// readLastLogLines returns up to n trailing lines of path. Exported-style
// (but package-local) for reuse by support-bundle, which embeds the same
// trailing extract in its output file.
func readLastLogLines(path string, n int) ([]string, error) {
	lines, _, err := readTrailingLines(path, n)
	return lines, err
}

func readTrailingLines(path string, n int) ([]string, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, 0, err
	}
	defer f.Close()

	info, err := f.Stat()
	if err != nil {
		return nil, 0, err
	}

	var buf []string
	scanner := bufio.NewScanner(f)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		buf = append(buf, scanner.Text())
		if len(buf) > n {
			buf = buf[1:]
		}
	}
	if err := scanner.Err(); err != nil {
		return buf, info.Size(), err
	}
	return buf, info.Size(), nil
}

// followLogFile polls path for growth every opts.Poll, printing only newly
// appended, complete lines. It re-opens the file on every poll (cheap at
// this interval, and avoids holding a long-lived handle across a possible
// log rotation) and buffers any trailing partial line across polls so a
// write that lands mid-line is never printed truncated.
func followLogFile(path string, startOffset int64, out io.Writer, opts tailOptions, stop <-chan struct{}) error {
	offset := startOffset
	var leftover []byte

	ticker := time.NewTicker(opts.Poll)
	defer ticker.Stop()

	for {
		select {
		case <-stop:
			return nil
		case <-ticker.C:
			info, statErr := os.Stat(path)
			if statErr != nil {
				// File missing/inaccessible for a moment (e.g. log
				// rotation) — keep polling instead of giving up.
				continue
			}
			size := info.Size()
			if size < offset {
				// Truncated or recreated: start reading from the top again.
				offset = 0
				leftover = nil
			}
			if size <= offset {
				continue
			}

			f, err := os.Open(path)
			if err != nil {
				continue
			}
			if _, err := f.Seek(offset, io.SeekStart); err != nil {
				f.Close()
				continue
			}
			chunk := make([]byte, size-offset)
			nRead, _ := io.ReadFull(f, chunk)
			f.Close()
			chunk = chunk[:nRead]
			offset += int64(nRead)

			data := append(leftover, chunk...)
			lastNL := bytes.LastIndexByte(data, '\n')
			if lastNL == -1 {
				leftover = data
				continue
			}
			complete := data[:lastNL]
			leftover = append([]byte{}, data[lastNL+1:]...)
			for _, line := range strings.Split(string(complete), "\n") {
				emitLogLine(out, line, opts)
			}
		}
	}
}

var logAnsiRE = regexp.MustCompile("\x1b\\[[0-9;]*m")

func stripANSICodes(s string) string {
	return logAnsiRE.ReplaceAllString(s, "")
}

func logLineMatchesLevel(line, level string) bool {
	switch strings.ToLower(level) {
	case "":
		return true
	case "error", "critical":
		return strings.Contains(line, "✖")
	case "warning", "warn":
		return strings.Contains(line, "⚠")
	case "info":
		return strings.Contains(line, "ℹ")
	default:
		return true
	}
}

func emitLogLine(out io.Writer, line string, opts tailOptions) {
	if opts.Grep != "" && !strings.Contains(stripANSICodes(line), opts.Grep) {
		return
	}
	if !logLineMatchesLevel(line, opts.Level) {
		return
	}
	if opts.NoColor {
		line = stripANSICodes(line)
	}
	fmt.Fprintln(out, line)
}

func runBrokerLogs(args []string) int {
	return runGenericLogs("broker-logs", paths.BrokerLogFile(), args)
}

func runCoreLogs(args []string) int {
	return runGenericLogs("core-logs", paths.CoreLogFile(), args)
}

func runGenericLogs(cmdName, logPath string, args []string) int {
	fs, _, _ := newFlagSet(cmdName)
	lines := fs.Int("lines", 50, "number of trailing lines to print initially")
	fs.IntVar(lines, "n", 50, "alias for --lines")
	follow := fs.Bool("follow", false, "keep streaming new lines as they're written")
	fs.BoolVar(follow, "f", false, "alias for --follow")
	level := fs.String("level", "", "filter by level: info, warning, or error")
	grep := fs.String("grep", "", "only show lines containing this text")
	noColor := fs.Bool("no-color", false, "strip ANSI color codes from output")
	file := fs.String("file", "", "path to a specific log file")
	if err := fs.Parse(args); err != nil {
		return usageErr(cmdName, err.Error())
	}

	path := *file
	if path == "" {
		path = logPath
	}
	if path == "" {
		ui.Error("no log file found")
		return 1
	}

	// Just reuse runLogs logic but point it to our file
	// A simple hack to reuse the existing runLogs function without refactoring everything:
	newArgs := []string{"--file", path}
	if !*follow {
		newArgs = append(newArgs, "--follow=false")
	}
	if *lines != 50 {
		newArgs = append(newArgs, fmt.Sprintf("--lines=%d", *lines))
	}
	if *level != "" {
		newArgs = append(newArgs, fmt.Sprintf("--level=%s", *level))
	}
	if *grep != "" {
		newArgs = append(newArgs, fmt.Sprintf("--grep=%s", *grep))
	}
	if *noColor {
		newArgs = append(newArgs, "--no-color")
	}

	return runLogs(newArgs)
}
