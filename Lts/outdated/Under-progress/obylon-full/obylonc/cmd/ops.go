package cmd

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"

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
	follow := fs.Bool("follow", false, "keep streaming new lines as they're written")
	fs.BoolVar(follow, "f", false, "alias for --follow")
	level := fs.String("level", "", "filter by level: info, warning, or error")
	grep := fs.String("grep", "", "only show lines containing this text")
	noColor := fs.Bool("no-color", false, "strip ANSI color codes from output")
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

	sp := ui.NewSpinner("Gathering diagnostics…")
	sp.Start()

	v := vault.New()
	_, _ = v.Load()

	hwUUID, _ := identity.LoadOrCreateHardwareUUID()
	hwFingerprint := identity.HardwareFingerprint()

	filename := fmt.Sprintf("obylon-support-%s.txt", time.Now().Format("20060102-150405"))

	var b strings.Builder
	b.WriteString("--- OBYLON SUPPORT BUNDLE ---\n")
	fmt.Fprintf(&b, "Timestamp: %s\n", time.Now().UTC().Format(time.RFC3339))
	fmt.Fprintf(&b, "Version: %s\n", Version)
	fmt.Fprintf(&b, "OS: %s/%s\n", runtime.GOOS, runtime.GOARCH)
	fmt.Fprintf(&b, "Hardware UUID: %s\n", hwUUID)
	fmt.Fprintf(&b, "Hardware Fingerprint: %s\n", hwFingerprint)
	b.WriteString("\n--- VAULT STATUS ---\n")
	fmt.Fprintf(&b, "License ID: %s\n", v.Get("LICENSE_ID"))
	fmt.Fprintf(&b, "Node ID: %s\n", v.Get("NODE_ID"))
	fmt.Fprintf(&b, "License Status: %s\n", v.Get("LICENSE_STATUS"))
	fmt.Fprintf(&b, "Last Heartbeat OK: %s\n", v.Get("LAST_HEARTBEAT_OK_AT"))
	fmt.Fprintf(&b, "Grace Days: %s\n", v.Get("GRACE_DAYS"))

	b.WriteString("\n--- LOG EXTRACT (last 100 lines) ---\n")
	if logPath := resolveLogPath(); logPath == "" {
		b.WriteString("Log file not found.\n")
	} else if logLines, err := readLastLogLines(logPath, 100); err != nil {
		fmt.Fprintf(&b, "Could not read log file: %v\n", err)
	} else {
		for _, l := range logLines {
			b.WriteString(l + "\n")
		}
	}

	if err := os.WriteFile(filename, []byte(b.String()), 0o644); err != nil {
		sp.Fail(fmt.Sprintf("Could not write support bundle: %v", err))
		return 1
	}

	sp.Success(fmt.Sprintf("Support bundle written to %s", filename))
	fmt.Println("Please attach this file when contacting Obylon Support.")
	return 0
}

// ---------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------

const bootTaskName = "ObylonAgent"

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
		out, err := exec.Command("schtasks", "/query", "/tn", bootTaskName).CombinedOutput()
		if err == nil {
			if strings.Contains(string(out), "Disabled") {
				ui.Warn("Boot task exists but is currently DISABLED.")
			} else {
				ui.Success("Boot task is configured and ENABLED.")
			}
		} else {
			ui.Error("Boot task is NOT FOUND or not configured.")
		}
	case "enable":
		// No subcommand argument here — ObylonBroker.exe is a standalone
		// Session 0 supervisor binary, not the old Python agent invoked
		// with "host". Registering this against the wrong binary (or with
		// a stray "host" argument a Rust binary doesn't understand) would
		// silently no-op every boot.
		out, err := exec.Command("schtasks", "/create", "/tn", bootTaskName,
			"/tr", fmt.Sprintf(`"%s"`, appPath),
			"/sc", "onstart", "/ru", "SYSTEM", "/rl", "HIGHEST", "/f").CombinedOutput()
		if err != nil {
			ui.Error("Failed to enable boot task: %s", strings.TrimSpace(string(out)))
			ui.Muted("Are you running the terminal as Administrator?")
			return 1
		}
		ui.Success("Successfully ENABLED Obylon to run on boot.")
	case "disable":
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
