package cmd

import (
	"fmt"
	"strings"
	"time"

	"obylonc/internal/api"
	"obylonc/internal/ui"
	"obylonc/internal/vault"
)

func runLogin(args []string) int {
	fs, _, _ := newFlagSet("login")
	if err := fs.Parse(args); err != nil {
		return usageErr("login", err.Error())
	}

	ui.PrintBanner("O B Y L O N   L O G I N")

	client := api.NewClient(10 * time.Second)
	baseURL := "https://umbraxis.tclservice.in"

	// 1. Initiate Device Authorization
	sp := ui.NewSpinner("Initiating device authorization...")
	sp.Start()

	payload := map[string]interface{}{
		"application_id": "app_cli_0000000000000", 
		"requested_scopes": []string{"admin", "read", "write"},
		"action_id": "cli_login",
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
	
	if deviceCode == "" || verificationURIComplete == "" {
		ui.Error("Invalid response from server (missing device_code or verification_uri_complete)")
		return 1
	}

	fmt.Printf("\n%s\n\n", ui.Green("Please open the following URL in your browser to authorize this CLI:"))
	fmt.Printf("  %s\n\n", ui.Bold(verificationURIComplete))
	
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
			
			v := vault.New()
			_, _ = v.Load()
			v.Set("ACCESS_TOKEN", token)
			v.Set("LICENSE_STATUS", "active")
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
