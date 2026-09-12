// Package cmd implements every obylonc subcommand. It's the standalone
// management CLI for the Obylon Sentinel endpoint agent: activation,
// license status, connectivity diagnostics, live logs, the AI support
// assistant, and the handful of admin/imaging utilities IT staff need.
//
// obylonc intentionally does not implement `host` (the Session-0 broker
// that spawns the agent into the active console session) or the bare,
// no-argument agent boot sequence — both stay in the agent binary, since
// they're the agent's own entry points rather than admin CLI commands.
//
// Files in this package are grouped by theme rather than one-per-command:
// root.go (this file) is CLI plumbing — dispatch, help, shared flags, and
// `version`; license.go covers the vault/license lifecycle (activate,
// status, diagnose, deactivate, reset-identity); ops.go covers day-to-day
// operations (logs, support-bundle, boot); ai.go is the support-assistant
// REPL.
package cmd

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"obylonc/internal/platform"
	"obylonc/internal/ui"
)

// ---------------------------------------------------------------------
// Version metadata
// ---------------------------------------------------------------------

// Version, BuildDate, BuildNumber, and Commit default to the same values
// baked into the Python agent (Obylon.py's BuildInfo class) so `obylonc version`
// and the agent's boot banner identify the same source release. Override at
// build time with ldflags when producing a signed artifact.
var (
	Version     = "7.0.6-LTS"
	BuildDate   = "2026-09-05"
	BuildNumber = "7.0.6-202609061200"
	Commit      = "f12411e"
)

func runVersion(args []string) int {
	fs, _, _ := newFlagSet("version")
	if err := fs.Parse(args); err != nil {
		return usageErr("version", err.Error())
	}

	ui.PrintCompactHeader("OBYLON SENTINEL · CLI", "Endpoint administration and diagnostics")
	ui.PrintBox("RELEASE", []string{
		fmt.Sprintf("Version       %s", ui.Bold(Version)),
		fmt.Sprintf("Build number   %s", BuildNumber),
		fmt.Sprintf("Build date     %s", BuildDate),
		fmt.Sprintf("Commit         %s", ui.Dim(Commit)),
	}, ui.Blue)
	return 0
}

// ---------------------------------------------------------------------
// Shared flag helper
// ---------------------------------------------------------------------

// newFlagSet returns a FlagSet pre-registered with the two flags every
// obylonc subcommand accepts (mirroring every argparse subparser in the
// Python CLI, which redeclared --dev/--verbose/--debug on each one). Output
// is silenced (each command prints its own styled usage on error) and
// os.Exit is never called directly by the flag package (ContinueOnError),
// so a bad flag can't skip our own error formatting.
func newFlagSet(name string) (fs *flag.FlagSet, dev *bool, verbose *bool) {
	fs = flag.NewFlagSet("obylonc "+name, flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	dev = fs.Bool("dev", false, "enable developer mode (verbose errors, raw payloads)")
	verbose = fs.Bool("verbose", false, "enable verbose output")
	fs.BoolVar(verbose, "debug", false, "alias for --verbose")
	return fs, dev, verbose
}

// usageErr prints a consistent "bad usage" message and returns the exit
// code callers should return from their run function.
func usageErr(command, msg string) int {
	ui.Error("obylonc %s: %s", command, msg)
	return 1
}

// ---------------------------------------------------------------------
// Dispatch + help
// ---------------------------------------------------------------------

type commandEntry struct {
	run    func(args []string) int
	brief  string
	scope  string
	action string
	admin  bool
}

// commands is the single source of truth for the public CLI surface. Every
// operational command is explicitly assigned a permission scope and, where
// the operation is privileged, a server-authoritative action ID. This keeps
// help, `admin`, and `auth request` aligned instead of maintaining several
// subtly different command lists.
var commands = map[string]commandEntry{
	"activate":     {run: runActivate, brief: "Activate this workstation with a license key", scope: "license", action: "obylon.license.activate", admin: true},
	"login":        {run: runLogin, brief: "Authenticate the CLI via browser (Device Code)", scope: "auth", action: "obylon.session.connect", admin: true},
	"status":       {run: runStatus, brief: "Print license, node, and authorization status", scope: "read", action: "obylon.inspect", admin: false},
	"diagnose":     {run: runDiagnose, brief: "Run connectivity, token, and signature diagnostics", scope: "diagnose", action: "obylon.diagnose", admin: false},
	"troubleshoot": {run: runTroubleshoot, brief: "Deep dive smart diagnostic engine for boot/spawn failures", scope: "diagnose", action: "obylon.diagnose", admin: true},
	"doctor":       {run: runDoctor, brief: "Health check, profiling, or safe repair", scope: "diagnose/update", action: "obylon.agent.update", admin: false},
	"logs":         {run: runLogs, brief: "Tail or follow the agent's live log", scope: "evidence", action: "obylon.evidence.read", admin: false},
	"broker-logs":  {run: runBrokerLogs, brief: "Tail or follow the broker's live log", scope: "evidence", action: "obylon.evidence.read", admin: false},
	"core-logs":    {run: runCoreLogs, brief: "Tail or follow the core's live log", scope: "evidence", action: "obylon.evidence.read", admin: false},
	// "logs":                 {run: runLogs, brief: "Tail or follow the agent's live log", scope: "evidence", action: "obylon.evidence.read", admin: false},
	"ai":                   {run: runAI, brief: "Ask the Obylon Support AI", scope: "read", action: "obylon.inspect", admin: false},
	"boot":                 {run: runBoot, brief: "Check or change startup behavior", scope: "update", action: "obylon.boot.enable|obylon.boot.disable", admin: true},
	"support-bundle":       {run: runSupportBundle, brief: "Generate a troubleshooting support bundle", scope: "diagnose/evidence", action: "obylon.evidence.read", admin: true},
	"reset-identity":       {run: runResetIdentity, brief: "Reset machine identity for imaging", scope: "update", action: "obylon.identity.reset", admin: true},
	"deactivate":           {run: runDeactivate, brief: "Deactivate this endpoint and clear local activation", scope: "update", action: "obylon.endpoint.deactivate", admin: true},
	"version":              {run: runVersion, brief: "Print exact release metadata", scope: "read", action: "obylon.inspect", admin: false},
	"admin":                {run: runAdmin, brief: "Run an operational command through the Admin scope", scope: "admin", action: "", admin: true},
	"auth":                 {run: runAuth, brief: "Manage Umbraxis authorization and privileged requests", scope: "auth", action: "obylon.session.connect", admin: true},
	"internal-fingerprint": {run: runInternalFingerprint, brief: "", scope: "internal", action: "", admin: false},
}

// commandOrder controls display order in help output.
var commandOrder = []string{
	"activate", "login", "status", "diagnose", "doctor", "logs", "broker-logs", "core-logs", "ai",
	"support-bundle", "boot", "reset-identity", "deactivate", "version",
}

// adminOperational is intentionally independent from commands so the Admin
// namespace does not create an initialization cycle in the command registry.
// It also makes the privileged surface explicit.
var adminOperational = map[string]commandEntry{
	"activate":     {run: runActivate, brief: "Provision a license", scope: "license", action: "obylon.license.activate", admin: true},
	"login":        {run: runLogin, brief: "Authenticate the technician session", scope: "auth", action: "obylon.session.connect", admin: true},
	"status":       {run: runStatus, brief: "Inspect license and node state", scope: "read", action: "obylon.inspect", admin: true},
	"diagnose":     {run: runDiagnose, brief: "Run endpoint diagnostics", scope: "diagnose", action: "obylon.diagnose", admin: true},
	"troubleshoot": {run: runTroubleshoot, brief: "Deep dive smart diagnostic engine", scope: "diagnose", action: "obylon.diagnose", admin: true},
	"doctor":       {run: runDoctor, brief: "Health check / safe repair", scope: "diagnose/update", action: "obylon.agent.update", admin: true},
	"logs":         {run: runLogs, brief: "Inspect agent logs", scope: "evidence", action: "obylon.evidence.read", admin: true},
	"broker-logs":  {run: runBrokerLogs, brief: "Inspect broker logs", scope: "evidence", action: "obylon.evidence.read", admin: true},
	"core-logs":    {run: runCoreLogs, brief: "Inspect core logs", scope: "evidence", action: "obylon.evidence.read", admin: true},
	// "logs":           {run: runLogs, brief: "Inspect agent logs", scope: "evidence", action: "obylon.evidence.read", admin: true},
	"ai":             {run: runAI, brief: "Ask support AI", scope: "read", action: "obylon.inspect", admin: true},
	"support-bundle": {run: runSupportBundle, brief: "Collect diagnostics", scope: "diagnose/evidence", action: "obylon.evidence.read", admin: true},
	"boot":           {run: runBoot, brief: "Manage boot integration", scope: "update", action: "obylon.boot.enable|obylon.boot.disable", admin: true},
	"reset-identity": {run: runResetIdentity, brief: "Reset machine identity", scope: "update", action: "obylon.identity.reset", admin: true},
	"deactivate":     {run: runDeactivate, brief: "Deactivate endpoint", scope: "update", action: "obylon.endpoint.deactivate", admin: true},
	"version":        {run: runVersion, brief: "Print release metadata", scope: "read", action: "obylon.inspect", admin: true},
}

// Execute is the CLI entry point, returning a process exit code.
func Execute() int {
	platform.EnableConsoleANSI()

	args := os.Args[1:]
	if len(args) == 0 {
		printHelp()
		return 0
	}

	if args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
		if len(args) > 1 && args[1] != "-h" && args[1] != "--help" {
			printCommandHelp(args[1])
		} else {
			printHelp()
		}
		return 0
	}
	if args[0] == "-v" || args[0] == "--version" {
		return runVersion(nil)
	}

	entry, ok := commands[args[0]]
	if !ok {
		ui.Error("obylonc: unknown command %q", args[0])
		if suggestion := suggestCommand(args[0]); suggestion != "" {
			ui.Hint("Did you mean `obylonc %s`?", suggestion)
		}
		ui.Hint("Use `obylonc help` to see every public command and admin scope.")
		return 1
	}
	if len(args) > 1 && (args[1] == "-h" || args[1] == "--help") {
		printCommandHelp(args[0])
		return 0
	}
	return entry.run(args[1:])
}

func suggestCommand(input string) string {
	input = strings.ToLower(strings.TrimSpace(input))
	if input == "" {
		return ""
	}
	best := ""
	bestDistance := 5
	for name := range adminOperational {
		d := editDistance(input, name)
		if d < bestDistance {
			best, bestDistance = name, d
		}
	}
	for name := range commands {
		d := editDistance(input, name)
		if d < bestDistance {
			best, bestDistance = name, d
		}
	}
	return best
}

func editDistance(a, b string) int {
	ar, br := []rune(a), []rune(b)
	prev := make([]int, len(br)+1)
	for j := range prev {
		prev[j] = j
	}
	for i, ca := range ar {
		cur := make([]int, len(br)+1)
		cur[0] = i + 1
		for j, cb := range br {
			cost := 0
			if ca != cb {
				cost = 1
			}
			cur[j+1] = minInt(prev[j+1]+1, cur[j]+1, prev[j]+cost)
		}
		prev = cur
	}
	return prev[len(br)]
}

func minInt(values ...int) int {
	best := values[0]
	for _, value := range values[1:] {
		if value < best {
			best = value
		}
	}
	return best
}

func printHelp() {
	ui.PrintBanner("S E N T I N E L   C L I")

	ui.PrintBox("COMMAND CENTER", []string{
		ui.Bold("Daily operations"),
		"  activate       Provision a license onto this endpoint",
		"  login          Authenticate the technician session",
		"  status         Show license, node, and auth state",
		"  diagnose       Run connectivity and signature diagnostics",
		"  troubleshoot   Deep dive smart diagnostic engine for boot/spawn failures",
		"  doctor         Health check / profile / safe repair",
		"  logs           Inspect the live agent log",
		"  ai             Ask the Obylon support assistant",
		"",
		ui.Bold("Administration"),
		"  admin <cmd>    Explicit Admin-scope command path",
		"  auth <cmd>     Authorization, request, and admin shortcuts",
		"  boot           Manage boot integration",
		"  support-bundle Collect endpoint diagnostics",
		"  reset-identity Reset identity for imaging",
		"  deactivate     Remove local activation",
		"",
		ui.Bold("Inspection"),
		"  version        Print exact build metadata",
	}, ui.Cyan)

	ui.Section("Permission model")
	fmt.Println("  read                 non-destructive inspection")
	fmt.Println("  diagnose             diagnostics and health inspection")
	fmt.Println("  evidence             log / forensic evidence access")
	fmt.Println("  update               endpoint configuration and lifecycle changes")
	fmt.Println("  policy               policy configuration")
	fmt.Println("  warden               enforcement actions")
	fmt.Println("  auth / admin         Umbraxis authorization and elevated admin scope")

	ui.Section("Examples")
	fmt.Println(ui.Dim("  obylonc activate --key-file C:\\Temp\\obylon.key"))
	fmt.Println(ui.Dim("  obylonc status"))
	fmt.Println(ui.Dim("  obylonc auth status"))
	fmt.Println(ui.Dim("  obylonc admin boot status"))
	fmt.Println(ui.Dim("  obylonc admin deactivate"))
	fmt.Println(ui.Dim("  obylonc diagnose --dev"))
	fmt.Println(ui.Dim("  obylonc logs -f --level warning"))
	fmt.Println()
	ui.Hint("The installer can provision a license; the CLI activation path remains available for recovery and re-provisioning.")
	ui.Hint("Run `obylonc <command> --help` or `obylonc help <command>` for exact usage.")
}

func printCommandHelp(name string) {
	if name == "admin" {
		printAdminHelp()
		return
	}
	if name == "auth" {
		printAuthHelp()
		return
	}
	entry, ok := adminOperational[name]
	if !ok {
		ui.Error("unknown command %q", name)
		return
	}
	ui.PrintCompactHeader("OBYLON SENTINEL · "+strings.ToUpper(name), entry.brief)
	ui.PrintBox("COMMAND", []string{
		fmt.Sprintf("Usage        obylonc %s %s", name, commandUsageTail(name)),
		fmt.Sprintf("Scope        %s", entry.scope),
		fmt.Sprintf("Action       %s", defaultString(entry.action, "local / license-provisioned")),
		fmt.Sprintf("Admin path   %s", adminPathFor(name)),
	}, ui.Blue)
	fmt.Println()
	for _, line := range commandHelpLines(name) {
		fmt.Println("  " + line)
	}
}

func commandUsageTail(name string) string {
	switch name {
	case "activate":
		return "<LICENSE_KEY> [--key-file <path>]"
	case "login":
		return "[status|logout]"
	case "diagnose", "status", "logs", "broker-logs", "core-logs", "ai", "support-bundle", "doctor", "version":
		return "[options]"
	case "boot":
		return "{status|enable|disable}"
	case "reset-identity":
		return "--confirm"
	case "deactivate":
		return "[-y]"
	case "admin":
		return "<command> [options]"
	case "auth":
		return "<login|request|status|logout|authorize|admin-command> [options]"
	default:
		return "[options]"
	}
}

func adminPathFor(name string) string {
	if name == "admin" || name == "auth" {
		return name
	}
	entry, ok := adminOperational[name]
	if !ok || !entry.admin {
		return "public"
	}
	return "admin " + name
}

func commandHelpLines(name string) []string {
	switch name {
	case "activate":
		return []string{
			"Activates this endpoint directly against the Obylon enrollment service.",
			"The workstation/node name is collected automatically from Windows.",
			"Use --key-file to avoid exposing a license key in the process command line.",
		}
	case "login":
		return []string{"Browser/device authorization; no password is entered into the terminal.", "Use `login status` or `login logout` for the local session."}
	case "status":
		return []string{"Shows license, expiration, node ID/name, hardware-bound state, and Umbraxis auth state."}
	case "diagnose":
		return []string{"Checks vault availability, enrollment heartbeat, server response, and license signature validity."}
	case "doctor":
		return []string{"Default: endpoint health check. `--profile 60s` profiles CPU. `--fix` applies only bounded repairs and requires update authorization."}
	case "logs", "broker-logs", "core-logs":
		return []string{"Use -f to follow. Filters: -n, --level, --grep, --no-color."}
	case "ai":
		return []string{"Technical support assistant for activation, deployment, licensing, logs, and diagnostics."}
	case "boot":
		return []string{"status is read-only. enable/disable are privileged lifecycle operations and are server-authorized."}
	case "support-bundle":
		return []string{"Collects version, identity metadata, vault state summary, and recent logs for support."}
	case "reset-identity":
		return []string{"Destructive imaging operation. Requires --confirm and identity.reset authorization."}
	case "deactivate":
		return []string{"Clears local activation state. Does not silently reactivate or recreate the license."}
	case "auth":
		return []string{"Use `auth request` for exact action authorization, `auth authorize` to test a token, and `auth admin-*` shortcuts for privileged lifecycle commands."}
	}
	if entry, ok := adminOperational[name]; ok {
		return []string{entry.brief}
	}
	return []string{"Use `obylonc help` to inspect the command registry."}
}

func printAdminHelp() {
	ui.PrintCompactHeader("OBYLON SENTINEL · ADMIN", "Explicit administrative command namespace")
	fmt.Println("Usage: obylonc admin <command> [options]")
	fmt.Println()
	adminOrder := []string{"activate", "status", "diagnose", "troubleshoot", "doctor", "logs", "broker-logs", "core-logs", "ai", "support-bundle", "boot", "reset-identity", "deactivate"}
	for _, name := range adminOrder {
		entry := adminOperational[name]
		fmt.Printf("  %-16s %s  [%s]\n", name, entry.brief, entry.scope)
	}
	fmt.Println()
	ui.Hint("Admin is a namespace, not a bypass. Privileged actions still call Umbraxis authorization.")
	ui.Hint("Activation is shown here for discoverability, but license-key enrollment is authenticated by the license service itself.")
}

// runAdmin exposes one predictable privileged namespace. Top-level commands
// remain for compatibility, while this path makes the administrative boundary
// obvious to technicians and automation.
func runAdmin(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		printAdminHelp()
		return 0
	}
	name := args[0]
	entry, ok := adminOperational[name]
	if !ok {
		return usageErr("admin", fmt.Sprintf("unknown admin command %q; use `obylonc admin --help`", name))
	}
	if len(args) > 1 && (args[1] == "-h" || args[1] == "--help") {
		printCommandHelp(name)
		return 0
	}
	return entry.run(args[1:])
}

func pad(s string, width int) string {
	n := width - len(s)
	if n <= 0 {
		return ""
	}
	b := make([]byte, n)
	for i := range b {
		b[i] = ' '
	}
	return string(b)
}
func runInternalFingerprint(args []string) int {
	fingerprint, reliable := platform.HardwareFingerprintWithStatus()
	if !reliable {
		fmt.Fprintln(os.Stderr, "hardware fingerprint is unavailable or incomplete")
		return 2
	}
	fmt.Print(fingerprint)
	return 0
}
