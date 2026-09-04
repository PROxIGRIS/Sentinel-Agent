package cmd

import (
	"fmt"
	"os/exec"
	"strings"
	"time"

	"obylonc/internal/api"
	"obylonc/internal/platform"
	"obylonc/internal/ui"
	"obylonc/internal/vault"
)

func runLogin(args []string) int {
	fs, _, _ := newFlagSet("login")
	if err := fs.Parse(args); err != nil {
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

	ui.PrintBanner("O B Y L O N   L O G I N")

	client := api.NewClient(10 * time.Second)
	baseURL := "https://umbraxis.tclservice.in"

	// 1. Initiate Device Authorization
	sp := ui.NewSpinner("Initiating device authorization...")
	sp.Start()

	fingerprint, reliable := platform.HardwareFingerprintWithStatus()
	if !reliable {
		fingerprint = "unknown-device-fallback"
	}
	payload := map[string]interface{}{
		"application": "obylon", 
		"deviceFingerprint": fingerprint,
		"requestedScopes": []string{"obylon:read"},
		"actionId": "obylon.session.connect",
	}

	statusCode, data, _, err := client.PostJSON(baseURL+"/api/auth/authorization-requests", nil, payload)
	if err != nil {
		sp.Fail(fmt.Sprintf("Network error: %v", err))
		return 1
	}
	if statusCode >= 400 {
		sp.Fail(fmt.Sprintf("Server rejected request (HTTP %d)", statusCode))
		return 1
	}
	sp.Stop()

	deviceCode := api.StringField(data, "device_code")
	verificationURIComplete := api.StringField(data, "verification_uri_complete")
	
	userCode := api.StringField(data, "user_code")
	verificationURI := api.StringField(data, "verification_uri")
	
	if deviceCode == "" || verificationURIComplete == "" {
		ui.Error("Invalid response from server (missing device_code or verification_uri_complete)")
		return 1
	}

	fmt.Printf("\n%s\n\n", ui.Green("Please authorize this CLI in your browser."))
	fmt.Printf("  %s\n\n", ui.Bold(verificationURIComplete))
	
	if userCode != "" && verificationURI != "" {
		fmt.Printf("%s\n", ui.Dim("If your browser didn't open automatically, visit:"))
		fmt.Printf("%s %s %s\n\n", ui.Dim("  "+verificationURI), ui.Dim("and enter code:"), ui.Bold(userCode))
	}
	
	// Automatically launch the browser on Windows
	if err := exec.Command("rundll32", "url.dll,FileProtocolHandler", verificationURIComplete).Start(); err != nil {
		// Fallback if rundll32 fails
		_ = exec.Command("cmd", "/c", "start", "", verificationURIComplete).Start()
	}

	fmt.Printf("%s\n\n", ui.Dim("Waiting for authorization..."))

	// 2. Poll for exchange
	intervalMs := 3000
	
	requestID := api.StringField(data, "id") 
	if requestID == "" {
		requestID = api.StringField(data, "request_id")
	}
	
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
			token := api.StringField(exData, "access_token")
			refreshToken := api.StringField(exData, "refresh_token")
			expiresAt := api.StringField(exData, "expires_at")
			
			v := vault.New()
			_, _ = v.Load()
			v.Set("AUTHZ_ACCESS_TOKEN", token)
			v.Set("AUTHZ_REFRESH_TOKEN", refreshToken)
			v.Set("AUTHZ_EXPIRES_AT", expiresAt)
			if err := v.Save(); err != nil {
				ui.Error("Failed to save credentials to vault: %v", err)
				return 1
			}
			
			ui.Success("Successfully authenticated!")
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
