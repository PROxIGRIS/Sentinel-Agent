// Package ui is obylonc's small, dependency-free terminal styling kit:
// colors, icons, boxed panels, and a spinner. Everything here is plain ANSI
// escape sequences over the standard library — no external TUI framework —
// so the CLI stays a single static binary with no third-party supply chain.
package ui

import (
	"fmt"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
)

// ColorEnabled controls whether escape codes are emitted at all. It honors
// the NO_COLOR convention (https://no-color.org) and can be forced off via
// --no-color in commands that accept it.
var ColorEnabled = os.Getenv("NO_COLOR") == ""

// DisableColor turns off all styling for the remainder of the process.
func DisableColor() { ColorEnabled = false }

func wrap(code, s string) string {
	if !ColorEnabled || s == "" {
		return s
	}
	return "\033[" + code + "m" + s + "\033[0m"
}

func Bold(s string) string    { return wrap("1", s) }
func Dim(s string) string     { return wrap("90", s) }
func Cyan(s string) string    { return wrap("96", s) }
func BlueB(s string) string   { return wrap("1;34", s) }
func Blue(s string) string    { return wrap("34", s) }
func Green(s string) string   { return wrap("92", s) }
func Red(s string) string     { return wrap("91", s) }
func Yellow(s string) string  { return wrap("93", s) }
func White(s string) string   { return wrap("97", s) }
func Magenta(s string) string { return wrap("95", s) }

// Icons used throughout command output. Kept as plain glyphs (not colored)
// so callers can color them contextually; the Success/Error/Warn/Info
// helpers below apply the conventional color for each.
const (
	IconOK     = "✔"
	IconErr    = "✖"
	IconWarn   = "⚠"
	IconInfo   = "ℹ"
	IconArrow  = "▶"
	IconBullet = "•"
	IconDash   = "→"
)

func Success(format string, a ...any) {
	fmt.Printf("%s %s\n", Green(IconOK), fmt.Sprintf(format, a...))
}

func Error(format string, a ...any) {
	fmt.Fprintf(os.Stderr, "%s %s\n", Red(IconErr), fmt.Sprintf(format, a...))
}

func Warn(format string, a ...any) {
	fmt.Printf("%s %s\n", Yellow(IconWarn), fmt.Sprintf(format, a...))
}

func Info(format string, a ...any) {
	fmt.Printf("%s %s\n", Cyan(IconInfo), fmt.Sprintf(format, a...))
}

// Step prints a section header, e.g. "▶ NETWORK & REACHABILITY".
func Step(format string, a ...any) {
	fmt.Printf("\n%s %s\n", Cyan(IconArrow), Bold(Cyan(fmt.Sprintf(format, a...))))
}

// Muted prints a low-emphasis line, for secondary/meta detail.
func Muted(format string, a ...any) {
	fmt.Println(Dim(fmt.Sprintf(format, a...)))
}

// KV prints a "Label: value" line with a dim label and bright value —
// used by `status` and `support-bundle` for field/value listings.
func KV(label, value string) {
	fmt.Printf("%s %s\n", Dim(label+":"), value)
}

// ansiRE strips ANSI SGR escape sequences, used to measure visible width of
// already-colored strings when laying out boxes.
var ansiRE = regexp.MustCompile("\x1b\\[[0-9;]*m")

func visibleLen(s string) int {
	return len([]rune(ansiRE.ReplaceAllString(s, "")))
}

// Box renders a rounded panel around the given lines, sized to the widest
// line (title included). Lines may already contain ANSI color codes.
func Box(title string, lines []string, borderColor func(string) string) string {
	if borderColor == nil {
		borderColor = Cyan
	}
	width := visibleLen(title)
	for _, l := range lines {
		if w := visibleLen(l); w > width {
			width = w
		}
	}
	width += 2 // one space padding each side
	var b strings.Builder
	top := "╭" + strings.Repeat("─", width) + "╮"
	bottom := "╰" + strings.Repeat("─", width) + "╯"
	b.WriteString(borderColor(top))
	b.WriteByte('\n')
	if title != "" {
		pad := width - 1 - visibleLen(title)
		if pad < 0 {
			pad = 0
		}
		b.WriteString(borderColor("│") + " " + Bold(title) + strings.Repeat(" ", pad) + borderColor("│"))
		b.WriteByte('\n')
		divider := "├" + strings.Repeat("─", width) + "┤"
		b.WriteString(borderColor(divider))
		b.WriteByte('\n')
	}
	for _, l := range lines {
		pad := width - 1 - visibleLen(l)
		if pad < 0 {
			pad = 0
		}
		b.WriteString(borderColor("│") + " " + l + strings.Repeat(" ", pad) + borderColor("│"))
		b.WriteByte('\n')
	}
	b.WriteString(borderColor(bottom))
	return b.String()
}

// PrintBox is Box() written straight to stdout.
func PrintBox(title string, lines []string, borderColor func(string) string) {
	fmt.Println(Box(title, lines, borderColor))
}

// logo is the OBYLON wordmark, unchanged from the agent's own boot banner
// so the CLI and the agent look like one product.
const logo = `     ██████╗ ██████╗ ██╗   ██╗██╗      ██████╗ ███╗   ██╗
    ██╔═══██╗██╔══██╗╚██╗ ██╔╝██║     ██╔═══██╗████╗  ██║
    ██║   ██║██████╔╝ ╚████╔╝ ██║     ██║   ██║██╔██╗ ██║
    ██║   ██║██╔══██╗  ╚██╔╝  ██║     ██║   ██║██║╚██╗██║
    ╚██████╔╝██████╔╝   ██║   ███████╗╚██████╔╝██║ ╚████║
     ╚═════╝ ╚═════╝    ╚═╝   ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝`

// PrintBanner prints the OBYLON wordmark with a byline underneath.
func PrintBanner(byline string) {
	fmt.Println(Cyan(logo))
	if byline != "" {
		fmt.Println(Dim("                   " + byline))
	}
	fmt.Println()
}

// Confirm prompts a yes/no question on stdin, defaulting to "no".
func Confirm(prompt string) bool {
	fmt.Printf("%s %s ", Yellow(IconWarn), prompt+" [y/N]")
	var answer string
	_, _ = fmt.Scanln(&answer)
	answer = strings.ToLower(strings.TrimSpace(answer))
	return answer == "y" || answer == "yes"
}

// ---------------------------------------------------------------------
// Spinner
// ---------------------------------------------------------------------

var spinnerFrames = []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}

// Spinner is a minimal, goroutine-driven progress indicator, in the spirit
// of the "thinking…"/"working…" spinners in modern agentic CLIs. It writes
// to stdout using carriage returns, so it should not be used alongside other
// concurrent stdout writers.
type Spinner struct {
	mu      sync.Mutex
	message string
	stopCh  chan struct{}
	doneCh  chan struct{}
	active  bool
	lastLen int
}

// NewSpinner creates a spinner with the given initial message. Call Start to
// begin animating.
func NewSpinner(message string) *Spinner {
	return &Spinner{message: message}
}

// Start begins animating the spinner on its own goroutine. No-op if it's
// already running, or if color/animation is disabled (NO_COLOR / non-tty
// pipelines), in which case it prints the message once and returns.
func (s *Spinner) Start() {
	s.mu.Lock()
	if s.active {
		s.mu.Unlock()
		return
	}
	s.active = true
	s.stopCh = make(chan struct{})
	s.doneCh = make(chan struct{})
	msg := s.message
	s.mu.Unlock()

	if !ColorEnabled {
		fmt.Println(msg)
		close(s.doneCh)
		return
	}

	go func() {
		defer close(s.doneCh)
		frame := 0
		ticker := time.NewTicker(90 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-s.stopCh:
				return
			case <-ticker.C:
				s.mu.Lock()
				line := fmt.Sprintf("%s %s", Cyan(spinnerFrames[frame%len(spinnerFrames)]), s.message)
				s.render(line)
				s.mu.Unlock()
				frame++
			}
		}
	}()
}

// UpdateMessage changes the text shown next to the spinner.
func (s *Spinner) UpdateMessage(message string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.message = message
}

// render must be called with s.mu held.
func (s *Spinner) render(line string) {
	pad := s.lastLen - visibleLen(line)
	if pad < 0 {
		pad = 0
	}
	fmt.Fprintf(os.Stdout, "\r%s%s", line, spacesN(pad))
	s.lastLen = visibleLen(line)
}

func spacesN(n int) string {
	if n <= 0 {
		return ""
	}
	b := make([]byte, n)
	for i := range b {
		b[i] = ' '
	}
	return string(b)
}

// clearLine must be called with s.mu held.
func (s *Spinner) clearLine() {
	fmt.Fprintf(os.Stdout, "\r%s\r", spacesN(s.lastLen))
	s.lastLen = 0
}

// Stop halts the animation and clears the spinner line without printing a
// final message.
func (s *Spinner) Stop() {
	s.mu.Lock()
	if !s.active {
		s.mu.Unlock()
		return
	}
	s.active = false
	close(s.stopCh)
	s.mu.Unlock()
	<-s.doneCh
	s.mu.Lock()
	if ColorEnabled {
		s.clearLine()
	}
	s.mu.Unlock()
}

// Success stops the spinner and prints a green checkmark line in its place.
func (s *Spinner) Success(message string) {
	s.Stop()
	Success("%s", message)
}

// Fail stops the spinner and prints a red X line in its place.
func (s *Spinner) Fail(message string) {
	s.Stop()
	Error("%s", message)
}
