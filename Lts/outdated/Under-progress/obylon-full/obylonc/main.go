// Command obylonc is the standalone management CLI for the Obylon Sentinel
// endpoint agent — activation, license status, diagnostics, live logs, and
// the AI support assistant. See package cmd for the full command set.
package main

import (
	"os"

	"obylonc/cmd"
)

func main() {
	os.Exit(cmd.Execute())
}
