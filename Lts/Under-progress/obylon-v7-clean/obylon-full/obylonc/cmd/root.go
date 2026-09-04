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
	

	"obylonc/internal/platform"
	"obylonc/internal/ui"
)

// ---------------------------------------------------------------------
// Version metadata
// ---------------------------------------------------------------------

// Version, BuildDate, and Commit default to the same values baked into the
// Python agent (Obylon.py's BuildInfo class) so `obylonc version` and the
// agent's own boot banner agree. Override at build time with, e.g.:
//
//	go build -ldflags "-X obylonc/cmd.Version=7.1.0 -X obylonc/cmd.Commit=$(git rev-parse --short HEAD)"
var (
	Version   = "7.0.0-LTS"
	BuildDate = "2026-08-18"
	Commit    = "session-broker+provenance+multilingual"
)

func runVersion(args []string) int {
	fs, _, _ := newFlagSet("version")
	if err := fs.Parse(args); err != nil {
		return usageErr("version", err.Error())
	}

	ui.PrintBanner("S E N T I N E L   C L I")
	ui.KV("Version", ui.Bold(Version))
	ui.KV("Build date", BuildDate)
	ui.KV("Commit", Commit)
	fmt.Println()
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
	run   func(args []string) int
	brief string
}

var commands = map[string]commandEntry{
	"activate":       {runActivate, "Activate this workstation with a license key"},
	"login":          {runLogin, "Authenticate the CLI via browser (Device Code)"},
	"status":         {runStatus, "Print human-readable license status"},
	"diagnose":       {runDiagnose, "Run connectivity and authentication checks"},
	"doctor":         {runDoctor, "Health check, CPU profile (--profile), or auto-repair (--fix)"},
	"logs":           {runLogs, "Tail or follow the agent's live log file"},
	"ai":             {runAI, "Ask the Obylon Support AI a question"},
	"boot":           {runBoot, "Check or change startup behavior (Admin)"},
	"support-bundle": {runSupportBundle, "Generate a support bundle for troubleshooting"},
	"reset-identity": {runResetIdentity, "Wipe machine identity for image capture (Admin)"},
	"deactivate":     {runDeactivate, "Wipe the local vault and deactivate the agent"},
	"version":        {runVersion, "Print version information"},
	"internal-fingerprint": {runInternalFingerprint, ""},
}

// commandOrder controls display order in help output — roughly the order a
// technician would use them day to day, destructive/admin tools last.
var commandOrder = []string{
	"activate", "status", "diagnose", "doctor", "logs", "ai",
	"boot", "support-bundle", "reset-identity", "deactivate", "version",
}

// Execute is the CLI entry point, returning a process exit code.
func Execute() int {
	platform.EnableConsoleANSI()

	args := os.Args[1:]
	if len(args) == 0 {
		printHelp()
		return 0
	}

	switch args[0] {
	case "-h", "--help", "help":
		printHelp()
		return 0
	case "-v", "--version":
		return runVersion(nil)
	}

	entry, ok := commands[args[0]]
	if !ok {
		ui.Error("obylonc: unknown command %q", args[0])
		fmt.Println()
		printHelp()
		return 1
	}
	return entry.run(args[1:])
}

func printHelp() {
	ui.PrintBanner("S E N T I N E L   C L I")
	fmt.Println(ui.Bold("Usage:") + " obylonc <command> [options]")
	fmt.Println()
	
	printCategory("Public Info & Auth", []string{"login", "status", "version"})
	printCategory("Helper Diagnostics", []string{"diagnose", "doctor", "logs", "ai", "support-bundle"})
	printCategory("Admin Actions", []string{"activate", "boot", "deactivate", "reset-identity"})
	
	fmt.Println()
	fmt.Println(ui.Bold("Global flags:"))
	fmt.Println("  --dev              enable developer mode (verbose errors, raw payloads)")
	fmt.Println("  --verbose, --debug enable verbose output")
	fmt.Println("  -v, --version      print version information")
	fmt.Println("  -h, --help         show this help")
	fmt.Println()
	fmt.Println(ui.Bold("Examples:"))
	fmt.Println(ui.Dim("  obylonc login"))
	fmt.Println(ui.Dim("  obylonc activate OBY-XXXX-XXXX"))
	fmt.Println(ui.Dim("  obylonc diagnose --dev"))
	fmt.Println(ui.Dim("  obylonc logs -f --level warning"))
	fmt.Println(ui.Dim(`  obylonc ai "how do I deploy to a whole lab?"`))
	fmt.Println()
}

func printCategory(title string, cmds []string) {
	fmt.Println(ui.Bold(title + ":"))
	for _, name := range cmds {
		cmd, ok := commands[name]
		if ok && cmd.brief != "" {
			fmt.Printf("  %-16s%s\n", name, cmd.brief)
		}
	}
	fmt.Println()
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
