package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"strings"
	"time"

	"obylonc/internal/authz"
	"obylonc/internal/platform"
	"obylonc/internal/ui"
	"obylonc/internal/vault"
)

const defaultAuthScopes = "obylon:read,obylon:diagnose,obylon:policy,obylon:update,obylon:warden,obylon:evidence"

var actionScopes = map[string][]string{
	"obylon.session.connect":          {"obylon:read"},
	"obylon.inspect":                  {"obylon:read"},
	"obylon.diagnose":                 {"obylon:diagnose"},
	"obylon.classroom.focus":          {"obylon:warden"},
	"obylon.policy.update":            {"obylon:policy"},
	"obylon.agent.update":             {"obylon:update"},
	"obylon.warden.lock":              {"obylon:warden"},
	"obylon.warden.terminate_process": {"obylon:warden"},
	"obylon.endpoint.shutdown":        {"obylon:warden"},
	"obylon.evidence.read":            {"obylon:evidence"},
	"obylon.endpoint.deactivate":      {"obylon:update"},
	"obylon.identity.reset":           {"obylon:update"},
	"obylon.boot.enable":              {"obylon:update"},
	"obylon.boot.disable":             {"obylon:update"},
}

// runAuth owns browser-mediated Umbraxis authorization. The local vault only
// protects client material at rest; every permission decision remains remote.
func runAuth(args []string) int {
	if len(args) == 0 || args[0] == "help" || args[0] == "--help" || args[0] == "-h" {
		printAuthHelp()
		return 0
	}
	switch args[0] {
	case "login":
		return runAuthLogin(args[1:], "obylon.session.connect", false)
	case "request":
		return runAuthLogin(args[1:], "", true)
	case "status":
		return runAuthStatus(args[1:])
	case "logout":
		return runAuthLogout(args[1:])
	case "authorize":
		return runAuthAuthorize(args[1:])
	default:
		return usageErr("auth", "unknown subcommand "+args[0])
	}
}

func printAuthHelp() {
	ui.PrintBanner("U M B R A X I S   A U T H")
	fmt.Println("Usage: obylonc auth <login|request|status|logout|authorize> [options]")
	fmt.Println()
	fmt.Println("  login      Authorize this client through the Umbraxis browser session")
	fmt.Println("  request    Request an exact privileged action and target")
	fmt.Println("  status     Show identity-free credential state without secrets")
	fmt.Println("  logout     Revoke the current client credential and clear it locally")
	fmt.Println("  authorize  Ask Umbraxis whether an action is currently allowed")
}

func authServer(flagValue string, v *vault.Vault) string {
	if strings.TrimSpace(flagValue) != "" {
		return strings.TrimSpace(flagValue)
	}
	if value := strings.TrimSpace(os.Getenv("UMBRAxis_AUTHZ_URL")); value != "" {
		return value
	}
	return strings.TrimSpace(v.Get("AUTHZ_BASE_URL"))
}

func runAuthLogin(args []string, defaultAction string, forceAction bool) int {
	fs, _, _ := newFlagSet("auth " + map[bool]string{true: "request", false: "login"}[forceAction])
	server := fs.String("server", "", "Umbraxis HTTPS base URL")
	actionID := fs.String("action", defaultAction, "registered action identifier")
	scopesFlag := fs.String("scopes", defaultAuthScopes, "comma-separated requested scopes")
	targetJSON := fs.String("target", "", "exact action target as JSON object (required for auth request)")
	if err := fs.Parse(args); err != nil {
		return usageErr("auth", err.Error())
	}
	if forceAction && strings.TrimSpace(*actionID) == "" {
		return usageErr("auth request", "--action is required")
	}

	v := vault.New()
	if _, err := v.Load(); err != nil {
		return usageErr("auth", err.Error())
	}
	baseURL := authServer(*server, v)
	if baseURL == "" {
		return usageErr("auth", "--server or UMBRAxis_AUTHZ_URL is required for the first login")
	}
	client, err := authz.NewClient(baseURL)
	if err != nil {
		return usageErr("auth", err.Error())
	}

	fingerprint, reliable := platform.HardwareFingerprintWithStatus()
	if !reliable {
		ui.Error("could not derive a stable device fingerprint")
		return 1
	}
	hostname, _ := os.Hostname()
	requestedScopes := splitScopes(*scopesFlag)
	if forceAction {
		var known bool
		requestedScopes, known = actionScopes[*actionID]
		if !known {
			return usageErr("auth request", "unknown action; use a registered action ID")
		}
	}
	target := map[string]interface{}{}
	if strings.TrimSpace(*targetJSON) != "" {
		if err := json.Unmarshal([]byte(*targetJSON), &target); err != nil {
			return usageErr("auth", "--target must be a JSON object")
		}
	}
	if forceAction && len(target) == 0 {
		return usageErr("auth request", "--target is required for an exact privileged action")
	}

	created, err := client.Create(authz.CreateRequest{
		Application: "obylon", DeviceName: hostname, DevicePlatform: runtime.GOOS,
		DeviceFingerprint: fingerprint, RequestedScopes: requestedScopes, ActionID: *actionID, Target: target,
	})
	if err != nil {
		ui.Error("Could not start authorization: %v", err)
		return 1
	}
	ui.PrintBox("AUTHORIZE OBYLON", []string{
		"Open this URL in a signed-in Umbraxis browser:",
		created.VerificationURIComplete,
		"",
		"Code: " + ui.Bold(formatAuthCode(created.UserCode)),
		"Action: " + *actionID,
		"Waiting for a server-authoritative decision…",
	}, ui.Cyan)

	deadline := time.Now().Add(time.Duration(created.ExpiresIn) * time.Second)
	interval := time.Duration(created.Interval) * time.Second
	if interval < time.Second {
		interval = 3 * time.Second
	}
	for time.Now().Before(deadline) {
		time.Sleep(interval)
		status, pollErr := client.Poll(created.RequestID, created.DeviceCode)
		if pollErr != nil {
			if apiErr, ok := pollErr.(*authz.APIError); ok && (apiErr.Code == "SLOW_DOWN" || apiErr.Code == "PENDING") {
				continue
			}
			ui.Error("Authorization polling failed: %v", pollErr)
			return 1
		}
		switch status.Status {
		case "PENDING", "APPROVAL_REQUIRED":
			continue
		case "APPROVED":
			credential, exchangeErr := client.Exchange(created.RequestID, created.DeviceCode)
			if exchangeErr != nil {
				ui.Error("Authorization exchange failed: %v", exchangeErr)
				return 1
			}
			if err := persistCredential(v, baseURL, credential); err != nil {
				ui.Error("Credential received but could not be stored: %v", err)
				return 1
			}
			ui.Success("Authorization complete. Credential expires %s.", credential.ExpiresAt)
			return 0
		case "DENIED", "EXPIRED", "CONSUMED":
			ui.Error("Authorization %s.", strings.ToLower(status.Status))
			return 1
		default:
			ui.Error("Authorization returned an unknown state: %s", status.Status)
			return 1
		}
	}
	ui.Error("Authorization request expired before a decision was received.")
	return 1
}

func runAuthStatus(args []string) int {
	fs, _, _ := newFlagSet("auth status")
	if err := fs.Parse(args); err != nil {
		return usageErr("auth status", err.Error())
	}
	v := vault.New()
	if _, err := v.Load(); err != nil {
		return usageErr("auth status", err.Error())
	}
	if v.Get("AUTHZ_ACCESS_TOKEN") == "" {
		ui.Warn("No Umbraxis authorization credential is stored.")
		return 0
	}
	state := "ACTIVE"
	if expiry, err := parseISO(v.Get("AUTHZ_EXPIRES_AT")); err == nil && time.Now().After(expiry) {
		state = "EXPIRED"
	}
	ui.PrintBox("UMBRAXIS AUTHORIZATION", []string{
		"State: " + state,
		"Action: " + defaultString(v.Get("AUTHZ_ACTION_ID"), "session authorization"),
		"Scopes: " + defaultString(v.Get("AUTHZ_SCOPES"), "none"),
		"Expires: " + defaultString(v.Get("AUTHZ_EXPIRES_AT"), "unknown"),
		"Device: " + defaultString(v.Get("AUTHZ_DEVICE_ID"), "unknown"),
	}, ui.Cyan)
	return 0
}

func runAuthLogout(args []string) int {
	fs, _, _ := newFlagSet("auth logout")
	if err := fs.Parse(args); err != nil {
		return usageErr("auth logout", err.Error())
	}
	v := vault.New()
	if _, err := v.Load(); err != nil {
		return usageErr("auth logout", err.Error())
	}
	accessToken := v.Get("AUTHZ_ACCESS_TOKEN")
	if accessToken != "" {
		if client, err := authz.NewClient(authServer("", v)); err == nil {
			if err := client.Revoke(accessToken); err != nil {
				ui.Warn("Server revocation did not complete: %v", err)
			}
		}
	}
	for _, key := range []string{"AUTHZ_BASE_URL", "AUTHZ_ACCESS_TOKEN", "AUTHZ_REFRESH_TOKEN", "AUTHZ_EXPIRES_AT", "AUTHZ_SCOPES", "AUTHZ_ACTION_ID", "AUTHZ_CREDENTIAL_ID", "AUTHZ_DEVICE_ID"} {
		v.Delete(key)
	}
	if err := v.Save(); err != nil {
		ui.Error("Could not clear local authorization: %v", err)
		return 1
	}
	ui.Success("Umbraxis authorization cleared locally.")
	return 0
}

func runAuthAuthorize(args []string) int {
	fs, _, _ := newFlagSet("auth authorize")
	actionID := fs.String("action", "", "registered action identifier")
	targetJSON := fs.String("target", "", "exact target as JSON object")
	if err := fs.Parse(args); err != nil {
		return usageErr("auth authorize", err.Error())
	}
	if *actionID == "" || *targetJSON == "" {
		return usageErr("auth authorize", "--action and --target are required")
	}
	var target map[string]interface{}
	if err := json.Unmarshal([]byte(*targetJSON), &target); err != nil || len(target) == 0 {
		return usageErr("auth authorize", "--target must be a non-empty JSON object")
	}
	v := vault.New()
	if _, err := v.Load(); err != nil {
		return usageErr("auth authorize", err.Error())
	}
	client, err := authz.NewClient(authServer("", v))
	if err != nil {
		return usageErr("auth authorize", err.Error())
	}
	decision, err := client.Authorize(v.Get("AUTHZ_ACCESS_TOKEN"), *actionID, target)
	if err != nil {
		ui.Error("Authorization denied: %v", err)
		return 1
	}
	if decision.Decision != "ALLOW" {
		ui.Error("Authorization denied: %s", decision.Decision)
		return 1
	}
	ui.Success("Authorized %s until %s.", decision.ActionID, decision.ExpiresAt)
	return 0
}

func persistCredential(v *vault.Vault, baseURL string, credential authz.Credential) error {
	v.SetMany(map[string]string{
		"AUTHZ_BASE_URL": baseURL, "AUTHZ_ACCESS_TOKEN": credential.AccessToken, "AUTHZ_REFRESH_TOKEN": credential.RefreshToken,
		"AUTHZ_EXPIRES_AT": credential.ExpiresAt, "AUTHZ_SCOPES": strings.Join(credential.Scopes, ","),
		"AUTHZ_ACTION_ID": credential.ActionID, "AUTHZ_CREDENTIAL_ID": credential.CredentialID, "AUTHZ_DEVICE_ID": credential.DeviceID,
	})
	return v.Save()
}

func splitScopes(value string) []string {
	seen := map[string]bool{}
	var scopes []string
	for _, scope := range strings.Split(value, ",") {
		scope = strings.TrimSpace(scope)
		if scope != "" && !seen[scope] {
			scopes, seen[scope] = append(scopes, scope), true
		}
	}
	return scopes
}

func formatAuthCode(code string) string {
	if len(code) > 4 {
		return code[:4] + "-" + code[4:]
	}
	return code
}

func defaultString(value, fallback string) string {
	if value != "" {
		return value
	}
	return fallback
}

// requireCLIActionAuthorization is a centralized helper that demands Umbraxis
// authorization before executing a privileged CLI command.
func requireCLIActionAuthorization(actionID string, target map[string]interface{}) bool {
	v := vault.New()
	if _, err := v.Load(); err != nil {
		ui.Error("AUTHENTICATION_REQUIRED: Local vault error: %v", err)
		return false
	}
	accessToken := v.Get("AUTHZ_ACCESS_TOKEN")
	if accessToken == "" {
		ui.Error("AUTHENTICATION_REQUIRED: No authorization credential is stored. Run 'obylonc auth login' first.")
		return false
	}
	if expiry, err := parseISO(v.Get("AUTHZ_EXPIRES_AT")); err == nil && time.Now().After(expiry) {
		ui.Error("AUTHENTICATION_REQUIRED: Authorization credential expired. Run 'obylonc auth login' again.")
		return false
	}
	client, err := authz.NewClient(authServer("", v))
	if err != nil {
		ui.Error("AUTHENTICATION_REQUIRED: Client config error: %v", err)
		return false
	}
	decision, err := client.Authorize(accessToken, actionID, target)
	if err != nil {
		ui.Error("AUTHENTICATION_REQUIRED: Authorization denied: %v", err)
		return false
	}
	if decision.Decision == "ALLOW" {
		return true
	}
	if decision.Decision == "APPROVAL_REQUIRED" {
		ui.Error("Authorization denied: APPROVAL_REQUIRED")
		return false
	}
	ui.Error("Authorization denied: %s", decision.Decision)
	return false
}
