package cmd

import (
	"flag"
	"fmt"
	"os/exec"
	"runtime"
	"strings"
	"time"

	"obylonc/internal/api"
	"obylonc/internal/platform"
	"obylonc/internal/ui"
	"obylonc/internal/vault"
)

func runLogin(args []string) int {
	fs, devFlag, _ := newFlagSet("login")
	if err := fs.Parse(args); err != nil {
		if err == flag.ErrHelp {
			printLoginHelp()
			return 0
		}
		return usageErr("login", err.Error())
	}

	positionals := fs.Args()
	if len(positionals) > 0 {
		switch positionals[0] {
		case "status":
			return runLoginStatus()
		case "logout":
			return runLoginLogout()
		case "help":
			printLoginHelp()
			return 0
		default:
			return usageErr("login", fmt.Sprintf("unknown subcommand %q. Available: status, logout", positionals[0]))
		}
	}

	if len(args) > 0 && (args[0] == "-h" || args[0] == "--help") {
		printLoginHelp()
		return 0
	}

	vLocal := vault.New()
	vLocal.Load()
	if token := vLocal.Get("AUTHZ_ACCESS_TOKEN"); token != "" {
		if expiry, err := parseISO(vLocal.Get("AUTHZ_EXPIRES_AT")); err == nil && time.Now().Before(expiry) {
			ui.Warn("You are already logged in.")
			ui.Muted("To log in as a different user, run: obylonc login logout")
			return 0
		}
	}

	ui.PrintCompactHeader("OBYLON · DEVICE LOGIN", "Secure browser authorization for this workstation")
	ui.PrintBox("AUTHENTICATION", []string{
		ui.StatusNeutral("Preparing browser authorization"),
		"A browser window will open automatically.",
		ui.Dim("No password is entered into this terminal."),
	}, ui.Cyan)
	fmt.Println()

	client := api.NewClient(30 * time.Second)
	baseURL := "https://umbraxis.tclservice.in"

	// 1. Initiate Device Authorization
	sp := ui.NewSpinner("Initiating device authorization...")
	sp.Start()

	fingerprint, reliable := platform.HardwareFingerprintWithStatus()
	if !reliable {
		fingerprint = "unknown-device-fallback"
	}
	nodeName := workstationNodeName()
	payload := map[string]interface{}{
		"application":       "obylon",
		"deviceName":        nodeName,
		"nodeName":          nodeName,
		"devicePlatform":    platformName(),
		"deviceFingerprint": fingerprint,
		"requestedScopes":   defaultAuthScopeList(),
		"actionId":          "obylon.session.connect",
	}

	statusCode, data, _, err := client.PostJSON(baseURL+"/api/auth/authorization-requests", nil, payload)
	if err != nil {
		if *devFlag {
			sp.Fail(fmt.Sprintf("Network error: %v", err))
		} else {
			sp.Fail("Something went wrong, please try again.")
		}
		return 1
	}
	if statusCode >= 400 {
		if *devFlag {
			sp.Fail(fmt.Sprintf("Server rejected request (HTTP %d)", statusCode))
		} else {
			sp.Fail("Something went wrong, please try again.")
		}
		return 1
	}
	sp.Stop()

	ui.Success("Authorization request created")
	ui.Hint("Step 1/2  Open the browser and approve this workstation.")

	deviceCode := api.StringField(data, "device_code")
	verificationURIComplete := api.StringField(data, "verification_uri_complete")

	userCode := api.StringField(data, "user_code")
	verificationURI := api.StringField(data, "verification_uri")

	if deviceCode == "" || verificationURIComplete == "" {
		ui.Error("Invalid response from server (missing device_code or verification_uri_complete)")
		return 1
	}

	fmt.Println()
	ui.PrintBox("BROWSER AUTHORIZATION", []string{
		ui.Bold("Open this link in a browser:"),
		ui.Cyan(verificationURIComplete),
	}, ui.Blue)

	if userCode != "" && verificationURI != "" {
		fmt.Printf("%s\n", ui.Dim("If your browser didn't open automatically, visit:"))
		fmt.Printf("%s %s %s\n\n", ui.Dim("  "+verificationURI), ui.Dim("and enter code:"), ui.Bold(userCode))
	}

	// Automatically launch the browser on Windows
	if err := exec.Command("rundll32", "url.dll,FileProtocolHandler", verificationURIComplete).Start(); err != nil {
		// Fallback if rundll32 fails
		_ = exec.Command("cmd", "/c", "start", "", verificationURIComplete).Start()
	}

	ui.Hint("Step 2/2  Waiting for approval and secure token exchange…")
	fmt.Println()

	// 2. Poll for exchange
	intervalMs := 3000

	requestID := api.StringField(data, "id")
	if requestID == "" {
		requestID = api.StringField(data, "request_id")
	}

	sp = ui.NewSpinner("Waiting for browser authorization…")
	sp.Start()
	defer sp.Stop()

	for {
		time.Sleep(time.Duration(intervalMs) * time.Millisecond)

		status, exData, _, exErr := client.PostJSON(
			fmt.Sprintf("%s/api/auth/authorization-requests/%s/exchange", baseURL, requestID),
			nil,
			map[string]interface{}{"device_code": deviceCode},
		)

		if exErr != nil {
			continue // network blip
		}

		if status == 200 {
			sp.Stop()
			token := api.StringField(exData, "access_token")
			refreshToken := api.StringField(exData, "refresh_token")
			expiresAt := api.StringField(exData, "expires_at")

			v := vault.New()
			_, _ = v.Load()
			v.Set("AUTHZ_ACCESS_TOKEN", token)
			v.Set("AUTHZ_REFRESH_TOKEN", refreshToken)
			v.Set("AUTHZ_EXPIRES_AT", expiresAt)
			v.Set("AUTHZ_SCOPES", strings.Join(stringSliceField(exData, "scopes", "granted_scopes"), ","))
			v.Set("AUTHZ_ACTION_ID", api.StringField(exData, "action_id"))
			v.Set("AUTHZ_CREDENTIAL_ID", api.StringField(exData, "credential_id"))
			v.Set("AUTHZ_DEVICE_ID", api.StringField(exData, "device_id"))
			v.Set("AUTHZ_BASE_URL", baseURL)
			if err := v.Save(); err != nil {
				ui.Error("Failed to save credentials to vault: %v", err)
				return 1
			}

			ui.PrintBox("AUTHENTICATED", []string{
				ui.StatusOK("CLI session is active"),
				"Credentials stored in the protected local vault.",
			}, ui.Green)
			ui.Hint("You can now run: obylonc status")
			return 0
		}

		if status >= 400 {
			errType := api.StringField(exData, "error")
			if strings.Contains(errType, "PENDING") || status == 409 || status == 429 {
				continue
			}
			if strings.Contains(errType, "EXPIRED") || status == 410 {
				ui.Error("Authorization request expired. Please run 'obylonc login' again.")
				return 1
			}
			if strings.Contains(errType, "DENIED") {
				ui.Error("Authorization was denied.")
				return 1
			}
		}
	}
}
func defaultAuthScopeList() []string {
	return splitScopes(defaultAuthScopesAndAdmin())
}

func defaultAuthScopesAndAdmin() string {
	return "obylon:read,obylon:diagnose,obylon:policy,obylon:update,obylon:warden,obylon:evidence,obylon:admin"
}

func stringSliceField(data map[string]interface{}, keys ...string) []string {
	for _, key := range keys {
		if raw, ok := data[key].([]interface{}); ok {
			var out []string
			for _, item := range raw {
				if value, ok := item.(string); ok && strings.TrimSpace(value) != "" {
					out = append(out, strings.TrimSpace(value))
				}
			}
			return out
		}
	}
	return nil
}

func platformName() string {
	return runtime.GOOS
}

func runLoginStatus() int {
	v := vault.New()
	if _, err := v.Load(); err != nil {
		ui.Error("Vault error: %v", err)
		return 1
	}

	token := v.Get("AUTHZ_ACCESS_TOKEN")
	if token == "" {
		ui.Warn("Not logged in. Run 'obylonc login' to authenticate.")
		return 0
	}

	if expiry, err := parseISO(v.Get("AUTHZ_EXPIRES_AT")); err == nil && time.Now().After(expiry) {
		ui.Warn("Session expired on %s. Run 'obylonc login' to re-authenticate.", expiry.Local().Format(time.RFC1123))
		return 0
	}

	ui.Success("Logged in and active.")
	ui.KV("Access Token", "Present")
	ui.KV("Expires", v.Get("AUTHZ_EXPIRES_AT"))
	return 0
}

func runLoginLogout() int {
	v := vault.New()
	if _, err := v.Load(); err != nil {
		ui.Error("Vault error: %v", err)
		return 1
	}

	if v.Get("AUTHZ_ACCESS_TOKEN") == "" {
		ui.Warn("Not currently logged in.")
		return 0
	}

	v.Delete("AUTHZ_ACCESS_TOKEN")
	v.Delete("AUTHZ_REFRESH_TOKEN")
	v.Delete("AUTHZ_EXPIRES_AT")

	if err := v.Save(); err != nil {
		ui.Error("Failed to clear session: %v", err)
		return 1
	}

	ui.Success("Logged out successfully.")
	return 0
}

func printLoginHelp() {
	fmt.Println(ui.Bold("obylonc login"))
	fmt.Println("Authenticate the CLI via browser (Device Code)")
	fmt.Println()
	fmt.Println(ui.Bold("Usage:"))
	fmt.Println("  obylonc login [command]")
	fmt.Println()
	fmt.Println(ui.Bold("Available Commands:"))
	fmt.Println("  status      Check current CLI login status")
	fmt.Println("  logout      Clear the current CLI session")
	fmt.Println()
	fmt.Println(ui.Bold("Examples:"))
	fmt.Println(ui.Dim("  obylonc login"))
	fmt.Println(ui.Dim("  obylonc login status"))
}
