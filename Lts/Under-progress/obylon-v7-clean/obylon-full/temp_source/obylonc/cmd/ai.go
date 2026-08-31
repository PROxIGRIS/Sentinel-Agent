package cmd

import (
	"bufio"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"time"

	"obylonc/internal/paths"
	"obylonc/internal/ui"
)

// ---------------------------------------------------------------------
// obylonc ai — the interactive command
// ---------------------------------------------------------------------

func runAI(args []string) int {
	fs, dev, _ := newFlagSet("ai")
	interactive := fs.Bool("interactive", false, "keep chatting after answering the initial prompt")
	fs.BoolVar(interactive, "i", false, "alias for --interactive")
	if err := fs.Parse(args); err != nil {
		return usageErr("ai", err.Error())
	}
	initialPrompt := strings.TrimSpace(strings.Join(fs.Args(), " "))

	// A single Ctrl+C cancels whatever's in flight (or the current prompt)
	// and exits cleanly, rather than killing the process mid-render.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt)
	go func() {
		<-sigCh
		cancel()
	}()

	session := newAISession()
	printAIHeader()

	if initialPrompt != "" {
		ok := askOnce(ctx, session, initialPrompt, *dev)
		if !*interactive {
			if ok {
				return 0
			}
			return 1
		}
		fmt.Println()
	}

	return runAIRepl(ctx, session, *dev)
}

func printAIHeader() {
	ui.PrintBox("Obylon AI · Support Assistant", []string{
		"Ask about activation, licensing, deployment, or logs.",
		ui.Dim("Type 'exit' or 'quit' to leave."),
	}, ui.Cyan)
	fmt.Println()
}

// runAIRepl drives the interactive chat loop. Stdin is read on its own
// goroutine and fed through a channel so a Ctrl+C at the prompt (which
// cancels ctx) can interrupt a blocked read instead of being silently
// swallowed until the next line arrives.
func runAIRepl(ctx context.Context, session *aiSession, dev bool) int {
	lineCh := make(chan string)
	doneCh := make(chan struct{})
	go func() {
		reader := bufio.NewReader(os.Stdin)
		for {
			line, err := reader.ReadString('\n')
			if err != nil {
				close(doneCh)
				return
			}
			lineCh <- line
		}
	}()

	for {
		fmt.Print(ui.Bold(ui.Green("❯ ")))
		select {
		case <-ctx.Done():
			fmt.Println()
			fmt.Println(ui.Dim("Goodbye!"))
			return 0
		case <-doneCh:
			fmt.Println()
			fmt.Println(ui.Dim("Goodbye!"))
			return 0
		case line := <-lineCh:
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			if line == "exit" || line == "quit" {
				fmt.Println(ui.Dim("Goodbye!"))
				return 0
			}
			askOnce(ctx, session, line, dev)
			fmt.Println()
		}
	}
}

// askOnce sends one message and renders the streamed reply as it arrives —
// a "thinking…" spinner up front, replaced in place by the response the
// moment the first token comes back. It returns false if the turn failed
// outright (network error, rate limit, empty response).
func askOnce(ctx context.Context, session *aiSession, prompt string, dev bool) bool {
	sp := ui.NewSpinner("Obylon AI is thinking…")
	sp.Start()

	first := true
	onDelta := func(chunk string) {
		if first {
			sp.Stop()
			fmt.Println(ui.Bold(ui.Cyan("Obylon AI")))
			fmt.Print("  ")
			first = false
		}
		fmt.Print(strings.ReplaceAll(chunk, "\n", "\n  "))
	}

	_, remaining, err := session.ask(ctx, prompt, onDelta)
	if err != nil {
		msg := fmt.Sprintf("Couldn't reach Obylon AI: %v", err)
		if first {
			sp.Fail(msg)
		} else {
			fmt.Println()
			ui.Error("%s", msg)
		}
		if dev {
			ui.Muted("[dev] prompt: %q", prompt)
		}
		return false
	}

	fmt.Println()
	fmt.Println()
	ui.Muted("[%d messages left this hour]", remaining)
	return true
}

// ---------------------------------------------------------------------
// Streaming Gemini chat session (folded in from what was a standalone
// internal/aichat package — its only caller was this file). Streaming
// (rather than a single blocking call, which is what the Python CLI did)
// is the one real behavior upgrade here: responses render token-by-token
// instead of appearing all at once.
// ---------------------------------------------------------------------

const (
	aiModel            = "gemini-2.5-flash"
	aiRateLimitPerHour = 20
	aiRateLimitWindow  = time.Hour
	aiRequestTimeout   = 60 * time.Second
)

// aiDefaultAPIKeyB64 is the same embedded Gemini key the Python CLI shipped
// with, decoded the same way. Set OBYLON_AI_API_KEY in the environment to
// override it (e.g. to rotate the key without rebuilding the binary) —
// that's the one addition here; default behavior is unchanged.
const aiDefaultAPIKeyB64 = "QVEuQWI4Uk42SWxJREsxQktaTGFmOVlXcGVrZUFFRnNSZ2ZNLTZ1eWRScWM2d2R6VFpZakE="

func aiAPIKey() string {
	if v := os.Getenv("OBYLON_AI_API_KEY"); v != "" {
		return v
	}
	decoded, err := base64.StdEncoding.DecodeString(aiDefaultAPIKeyB64)
	if err != nil {
		return ""
	}
	return string(decoded)
}

// aiSystemInstruction keeps the assistant scoped to Obylon support and
// gives it an accurate picture of the CLI it's describing to users.
const aiSystemInstruction = `You are Obylon AI, a dedicated technical support assistant for the Obylon Sentinel Endpoint Agent.
Your scope is ONLY technical support for Obylon. Refuse to answer questions outside this scope.

CLI Structure (obylonc):
- obylonc activate <LICENSE_KEY> [--key-file <path>]: Activates this workstation.
- obylonc status: Prints human-readable license status.
- obylonc diagnose [--dev]: Runs network and authentication checks.
- obylonc logs [-f] [-n <count>] [--level <info|warning|error>] [--grep <text>]: Tails or follows the agent's live log.
- obylonc support-bundle: Writes a support bundle file for troubleshooting.
- obylonc boot {status|enable|disable}: Manages the boot-time scheduled task (requires Admin).
- obylonc reset-identity --confirm: Wipes machine identity for golden-image capture (requires Admin).
- obylonc deactivate [-y]: Wipes the local vault and deactivates the agent.

Fleet Deployment Instructions (Seed Mode):
To deploy Obylon across an entire school fleet without manual UI interaction:
1. Create a plain text file named license_seed.txt.
2. Paste a valid Obylon License Key (e.g. OBY-XXXX) into this file, no extra spaces.
3. Place license_seed.txt in the same folder as the installer.
4. Run the installer silently via MDM, Group Policy (GPO), or Intune.
5. The installer auto-detects the seed file, activates, and registers the workstation.

Reply in clear, helpful, terminal-friendly plain text. Be concise but polite.`

// aiLimitState is persisted as JSON at paths.AIRateLimitFile(), in the same
// shape and location the Python CLI used, so the hourly counter is shared
// even if both CLIs are ever run on the same machine.
type aiLimitState struct {
	Count       int   `json:"count"`
	WindowStart int64 `json:"window_start"`
}

// checkAndBumpAIRateLimit enforces the 20-messages-per-hour quota and
// returns how many messages remain in the current window. It counts this
// attempt immediately, before the network call — so, matching the Python
// CLI, a failed request still spends a slot rather than being refunded.
func checkAndBumpAIRateLimit() (remaining int, err error) {
	path := paths.AIRateLimitFile()
	var state aiLimitState
	if b, rerr := os.ReadFile(path); rerr == nil {
		_ = json.Unmarshal(b, &state)
	}
	now := time.Now().Unix()
	if now-state.WindowStart > int64(aiRateLimitWindow.Seconds()) {
		state = aiLimitState{Count: 0, WindowStart: now}
	}
	if state.Count >= aiRateLimitPerHour {
		return 0, fmt.Errorf("rate limit exceeded — you can only send %d messages per hour", aiRateLimitPerHour)
	}
	state.Count++
	if b, merr := json.Marshal(state); merr == nil {
		_ = os.WriteFile(path, b, 0o600)
	}
	return aiRateLimitPerHour - state.Count, nil
}

type aiPart struct {
	Text string `json:"text"`
}

type aiContent struct {
	Role  string   `json:"role"`
	Parts []aiPart `json:"parts"`
}

type aiGenerateRequest struct {
	Contents          []aiContent `json:"contents"`
	SystemInstruction struct {
		Parts []aiPart `json:"parts"`
	} `json:"systemInstruction"`
	GenerationConfig struct {
		Temperature float64 `json:"temperature"`
	} `json:"generationConfig"`
}

type aiStreamChunk struct {
	Candidates []struct {
		Content struct {
			Parts []aiPart `json:"parts"`
		} `json:"content"`
	} `json:"candidates"`
}

func (c aiStreamChunk) text() string {
	if len(c.Candidates) == 0 || len(c.Candidates[0].Content.Parts) == 0 {
		return ""
	}
	return c.Candidates[0].Content.Parts[0].Text
}

// aiSession holds conversation history for one chat (REPL or single prompt).
type aiSession struct {
	history []aiContent
}

// newAISession returns an empty chat session.
func newAISession() *aiSession {
	return &aiSession{}
}

// ask sends userText plus the running history to the model and streams the
// reply through onDelta as chunks arrive. It returns the full reply text,
// the number of messages left in the current hourly window, and an error
// if the call failed outright (in which case the failed user turn is rolled
// back out of history so a retry doesn't duplicate it).
func (s *aiSession) ask(ctx context.Context, userText string, onDelta func(string)) (reply string, remaining int, err error) {
	remaining, err = checkAndBumpAIRateLimit()
	if err != nil {
		return "", 0, err
	}

	s.history = append(s.history, aiContent{Role: "user", Parts: []aiPart{{Text: userText}}})
	rollback := func() {
		s.history = s.history[:len(s.history)-1]
	}

	var reqBody aiGenerateRequest
	reqBody.Contents = s.history
	reqBody.SystemInstruction.Parts = []aiPart{{Text: aiSystemInstruction}}
	reqBody.GenerationConfig.Temperature = 0.2

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		rollback()
		return "", remaining, err
	}

	url := fmt.Sprintf(
		"https://generativelanguage.googleapis.com/v1beta/models/%s:streamGenerateContent?alt=sse&key=%s",
		aiModel, aiAPIKey(),
	)
	reqCtx, cancel := context.WithTimeout(ctx, aiRequestTimeout)
	defer cancel()
	httpReq, err := http.NewRequestWithContext(reqCtx, http.MethodPost, url, bytes.NewReader(bodyBytes))
	if err != nil {
		rollback()
		return "", remaining, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	client := &http.Client{}
	resp, err := client.Do(httpReq)
	if err != nil {
		rollback()
		return "", remaining, err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		raw := make([]byte, 512)
		n, _ := resp.Body.Read(raw)
		rollback()
		return "", remaining, fmt.Errorf("AI service returned HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(raw[:n])))
	}

	var full strings.Builder
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if payload == "" || payload == "[DONE]" {
			continue
		}
		var chunk aiStreamChunk
		if err := json.Unmarshal([]byte(payload), &chunk); err != nil {
			continue
		}
		if text := chunk.text(); text != "" {
			full.WriteString(text)
			if onDelta != nil {
				onDelta(text)
			}
		}
	}
	if scanErr := scanner.Err(); scanErr != nil && full.Len() == 0 {
		rollback()
		return "", remaining, scanErr
	}

	finalText := full.String()
	if finalText == "" {
		rollback()
		return "", remaining, errors.New("AI service returned an empty response")
	}
	s.history = append(s.history, aiContent{Role: "model", Parts: []aiPart{{Text: finalText}}})
	return finalText, remaining, nil
}
