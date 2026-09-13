package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"obylonc/internal/api"
	"obylonc/internal/identity"
	"obylonc/internal/paths"
	"obylonc/internal/platform"
	"obylonc/internal/ui"
	"obylonc/internal/vault"
)

// ---------------------------------------------------------------------
// activate
// ---------------------------------------------------------------------

func runActivate(args []string) int {
	logFile, _ := os.OpenFile("C:\\ProgramData\\Obylon\\logs\\activate_debug.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	defer logFile.Close()
	fmt.Fprintf(logFile, "Activation attempt started\n")
	fs, dev, _ := newFlagSet("activate")
	keyFile := fs.String("key-file", "", "path to a file containing the license key (deleted after read)")
	nodeNameFlag := fs.String("node-name", "", "explicit workstation/node name (defaults to Windows COMPUTERNAME)")
	if err := fs.Parse(args); err != nil {
		return usageErr("activate", err.Error())
	}

	// Prefer --key-file so the license key never appears on the process
	// command line (visible to EDR/SIEM tooling) — same rationale as the
	// Python CLI. The key file is always deleted after a successful read,
	// even if activation itself later fails.
	var licenseKey string
	if *keyFile != "" {
		b, err := os.ReadFile(*keyFile)
		if err != nil {
			ui.Error("could not read key file: %v", err)
			return 1
		}
		licenseKey = strings.TrimSpace(string(b))
		_ = os.Remove(*keyFile)
	} else if positional := fs.Args(); len(positional) > 0 {
		licenseKey = positional[0]
	}
	if licenseKey == "" {
		ui.Error("no license key provided. Use: obylonc activate <LICENSE_KEY> or --key-file <path>")
		return 1
	}

	nodeName := strings.TrimSpace(*nodeNameFlag)
	if nodeName == "" {
		nodeName = workstationNodeName()
	}
	if nodeName == "" || strings.EqualFold(nodeName, "OBYLON-ENDPOINT") {
		ui.Warn("Windows returned no usable workstation name; using a deterministic fallback.")
	}
	hwUUID, idErr := identity.LoadOrCreateHardwareUUID()
	if idErr != nil && *dev {
		ui.Muted("[dev] %v", idErr)
	}
	hwFingerprint, fingerprintReliable := platform.HardwareFingerprintWithStatus()
	if !fingerprintReliable {
		ui.Error("could not derive a stable hardware identity; wait for Windows device discovery and retry activation")
		return 1
	}

	sp := ui.NewSpinner("Provisioning agent…")
	sp.Start()

	client := api.NewClient(15 * time.Second)
	ui.Info("Registering node as %s", ui.Bold(nodeName))
	statusCode, data, raw, err := client.Activate(api.ActivateRequest{
		LicenseKey:          licenseKey,
		Hostname:            nodeName,
		NodeName:            nodeName,
		DeviceName:          nodeName,
		HardwareUUID:        hwUUID,
		HardwareFingerprint: hwFingerprint,
	})
	if err != nil {
		sp.Fail("Activation failed: network unreachable. Check connectivity and retry.")

		os.WriteFile("C:\\ProgramData\\Obylon\\logs\\network_error.txt", []byte(err.Error()), 0644)
		if *dev {
			ui.Muted("[dev] %v", err)
		}
		return 1
	}

	if statusCode >= 400 {
		errType := api.ErrorType(data)
		switch errType {
		case "node_limit_reached":
			sp.Fail(fmt.Sprintf("Activation failed: license node limit reached (%v/%v active).",
				data["active_nodes"], data["node_limit"]))
		case "license_expired", "license_revoked", "license_suspended":
			sp.Fail("Activation failed: " + strings.ReplaceAll(errType, "_", " ") + ".")
		case "invalid_key":
			sp.Fail("Activation failed: invalid license key.")
		default:
			if errType != "" {
				sp.Fail("Activation failed: " + errType + ".")
			} else {
				sp.Fail(fmt.Sprintf("Activation failed: HTTP %d.", statusCode))
			}
		}
		if *dev {
			ui.Muted("[dev] response: %s", string(raw))

			ui.Error("Server response: %s", string(raw))
			os.WriteFile("C:\\ProgramData\\Obylon\\logs\\activate_error.txt", raw, 0644)
		}
		return 1
	}

	if !verifiedActivationResponse(data, hwUUID) {
		sp.Fail("Activation failed: server response failed cryptographic verification.")
		ui.Warn("The response is missing required signed fields, has the wrong hardware binding, or has an invalid signature.")
		if *dev {
			ui.Muted("[dev] payload: %s", string(raw))
		}
		return 1
	}

	issuedAt := api.StringField(data, "issued_at")
	graceDays := boundedGraceDays(data)

	v := vault.New()
	nodeID := api.StringField(data, "node_id")
	nodeNameReturned := firstStringField(data, "node_name", "nodeName", "device_name", "hostname", "name")
	if nodeNameReturned == "" {
		nodeNameReturned = nodeName
	}

	v.SetMany(map[string]string{
		"SUPABASE_URL":                       api.StringField(data, "supabase_url"),
		"SUPABASE_ANON_KEY":                  api.StringField(data, "anon_key"),
		"ACCESS_TOKEN":                       api.StringField(data, "access_token"),
		"REFRESH_TOKEN":                      api.StringField(data, "refresh_token"),
		"LICENSE_ID":                         api.StringField(data, "license_id"),
		"NODE_ID":                            nodeID,
		"NODE_NAME":                          nodeNameReturned,
		"WORKSTATION_NAME":                   nodeNameReturned,
		"LICENSE_STATUS":                     api.StringField(data, "status"),
		"LAST_HEARTBEAT_OK_AT":               issuedAt,
		"MAX_SEEN_UTC":                       issuedAt,
		"EXPIRES_AT":                         api.StringField(data, "expires_at"),
		"GRACE_DAYS":                         graceDays,
		"SERVER_SIG":                         api.StringField(data, "server_sig"),
		"HARDWARE_FINGERPRINT_AT_ACTIVATION": hwFingerprint,
	})
	if err := v.Save(); err != nil {
		sp.Fail(fmt.Sprintf("Activation succeeded but saving the vault failed: %v", err))
		return 1
	}

	sp.Success("Activation complete. Agent ready for background execution.")
	return 0
}

func workstationNodeName() string {
	for _, value := range []string{os.Getenv("COMPUTERNAME")} {
		if name := strings.TrimSpace(value); name != "" {
			return name
		}
	}
	if name, err := os.Hostname(); err == nil {
		if name = strings.TrimSpace(name); name != "" {
			return name
		}
	}
	// Never send an empty node name. The fallback is deterministic enough for
	// the local activation transaction and is replaced by the server's name
	// when the response provides one.
	return "OBYLON-ENDPOINT"
}

func firstStringField(data map[string]interface{}, keys ...string) string {
	for _, key := range keys {
		if value := strings.TrimSpace(api.StringField(data, key)); value != "" {
			return value
		}
	}
	return ""
}

func verifiedActivationResponse(data map[string]interface{}, hardwareUUID string) bool {
	serverSig := api.StringField(data, "server_sig")
	if serverSig == "" {
		return false
	}
	for _, field := range []string{"license_id", "node_id", "issued_at", "status"} {
		if api.StringField(data, field) == "" {
			return false
		}
	}
	if expiresAt, present := data["expires_at"]; present && expiresAt != nil {
		if value, ok := expiresAt.(string); !ok || value == "" {
			return false
		}
	}
	if claimedHardwareUUID, present := data["hardware_uuid"]; present && claimedHardwareUUID != nil {
		value, ok := claimedHardwareUUID.(string)
		if !ok || (value != "" && value != hardwareUUID) {
			return false
		}
	}
	return api.Verify(data, hardwareUUID, serverSig)
}

func boundedGraceDays(data map[string]interface{}) string {
	const maximumOfflineGraceDays = 14
	value, present := data["grace_days"]
	if !present || value == nil {
		return strconv.Itoa(maximumOfflineGraceDays)
	}
	graceDays, err := strconv.Atoi(fmt.Sprintf("%v", value))
	if err != nil {
		return strconv.Itoa(maximumOfflineGraceDays)
	}
	if graceDays < 0 {
		return "0"
	}
	if graceDays > maximumOfflineGraceDays {
		graceDays = maximumOfflineGraceDays
	}
	return strconv.Itoa(graceDays)
}

// ---------------------------------------------------------------------
// status
// ---------------------------------------------------------------------

func runStatus(args []string) int {
	fs, _, _ := newFlagSet("status")
	if err := fs.Parse(args); err != nil {
		return usageErr("status", err.Error())
	}

	v := vault.New()
	ok, err := v.Load()
	if err != nil {
		ui.Error("could not read the local vault: %v", err)
		return 1
	}
	if !ok || v.Get("ACCESS_TOKEN") == "" {
		if JSONMode() {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"tool": "obylonc status", "version": Version, "activated": false, "agent": "unknown"})
			return 0
		}
		ui.PrintCompactHeader("OBYLON STATUS", "Endpoint state at a glance")
		ui.PrintBox("WORKSTATION", []string{ui.StatusWarn("Not activated"), "No local license token is available.", "Run: obylonc activate <LICENSE_KEY>"}, ui.Yellow)
		return 0
	}

	status := v.Get("LICENSE_STATUS")
	expiresStr := v.Get("EXPIRES_AT")
	lastHB := v.Get("LAST_HEARTBEAT_OK_AT")
	grace := v.Get("GRACE_DAYS")
	licenseHealthy := strings.EqualFold(status, "active")

	processState := map[string]bool{
		"broker": processExists("ObylonBroker.exe"),
		"core":   processExists("ObylonCore.exe"),
		"brain":  processExists("obylon.exe"),
	}
	agentState := "stopped"
	if processState["broker"] || processState["core"] || processState["brain"] {
		agentState = "running"
	}
	if processState["broker"] && !processState["core"] {
		agentState = "degraded"
	}

	if JSONMode() {
		expires := ""
		if expiresStr != "" {
			expires = expiresStr
		}
		_ = json.NewEncoder(os.Stdout).Encode(map[string]any{
			"tool": "obylonc status", "version": Version, "activated": true,
			"license":   map[string]any{"status": status, "expires_at": expires, "grace_days": grace, "node_id": v.Get("NODE_ID"), "node_name": v.Get("NODE_NAME")},
			"agent":     map[string]any{"state": agentState, "broker": processState["broker"], "core": processState["core"], "brain": processState["brain"]},
			"heartbeat": lastHB,
		})
		if !licenseHealthy || agentState == "degraded" {
			return 1
		}
		return 0
	}

	ui.PrintCompactHeader("OBYLON STATUS", "One-screen endpoint health")
	licenseValue := ui.Green("ACTIVE")
	if !licenseHealthy {
		licenseValue = ui.Red(strings.ToUpper(defaultString(status, "UNKNOWN")))
	}
	agentValue := ui.Green("RUNNING")
	if agentState == "degraded" {
		agentValue = ui.Yellow("DEGRADED")
	} else if agentState == "stopped" {
		agentValue = ui.Red("STOPPED")
	}

	ui.PrintBox("HEALTH", []string{
		fmt.Sprintf("License       %s", licenseValue),
		fmt.Sprintf("Agent         %s", agentValue),
		fmt.Sprintf("Broker        %s", boolStatus(processState["broker"])),
		fmt.Sprintf("Core          %s", boolStatus(processState["core"])),
		fmt.Sprintf("Brain         %s", boolStatus(processState["brain"])),
	}, ui.Blue)

	lines := []string{
		fmt.Sprintf("Node          %s", ui.Bold(defaultString(v.Get("NODE_NAME"), "unknown"))),
		fmt.Sprintf("Node ID       %s", ui.Dim(defaultString(v.Get("NODE_ID"), "unknown"))),
		fmt.Sprintf("Version       %s", Version),
	}
	if expiresStr != "" {
		if expDT, perr := parseISO(expiresStr); perr == nil {
			days := int(time.Until(expDT) / (24 * time.Hour))
			if days >= 0 {
				lines = append(lines, fmt.Sprintf("Expires       %s (%d days)", safeSlice(expiresStr, 10), days))
			} else {
				lines = append(lines, fmt.Sprintf("Expires       %s", ui.Red(fmt.Sprintf("expired %d days ago", -days))))
			}
		}
	}
	if lastHB != "" {
		lines = append(lines, fmt.Sprintf("Heartbeat     %s UTC", formatHeartbeat(lastHB)))
	}
	if grace != "" {
		lines = append(lines, fmt.Sprintf("Offline grace %s days", grace))
	}
	ui.PrintBox("DETAILS", lines, ui.Cyan)

	if agentState == "degraded" || agentState == "stopped" {
		ui.Hint("Run `obylonc doctor --deep` for evidence and a root-cause explanation.")
		return 1
	} else if licenseHealthy {
		ui.Hint("Endpoint is provisioned and the boot chain is currently running.")
	}
	if !licenseHealthy {
		return 1
	}
	return 0
}

func boolStatus(ok bool) string {
	if ok {
		return ui.Green("● running")
	}
	return ui.Dim("○ not running")
}

// ---------------------------------------------------------------------
// diagnose
// ---------------------------------------------------------------------

func runDiagnose(args []string) int {
	fs, dev, _ := newFlagSet("diagnose")
	if err := fs.Parse(args); err != nil {
		return usageErr("diagnose", err.Error())
	}

	ui.PrintBanner("D I A G N O S T I C   S U I T E")

	v := vault.New()
	_, _ = v.Load()
	accessToken := v.Get("ACCESS_TOKEN")

	ui.Step("VAULT CHECK")
	if accessToken == "" {
		ui.Error("No ACCESS_TOKEN found in local vault.")
		ui.Warn("Resolution: this workstation is not activated. Run `obylonc activate <LICENSE_KEY>`")
		return 1
	}
	ui.Success("Access token found")

	ui.Step("NETWORK & REACHABILITY")
	ui.Muted("Target: %s/license_heartbeat", api.EnrollmentEndpoint)

	hwUUID, _ := identity.LoadOrCreateHardwareUUID()
	client := api.NewClient(5 * time.Second)
	statusCode, data, raw, err := client.Heartbeat(accessToken, hwUUID)
	if err != nil {
		ui.Error("Connection error: %v", err)
		ui.Step("ROOT CAUSE ANALYSIS")
		fmt.Println("  The agent could not reach the internet, or the Obylon cloud is unreachable.")
		fmt.Printf("  Check local firewall policies for traffic to: %s\n", api.EnrollmentEndpoint)
		if *dev {
			ui.Muted("[dev] %v", err)
		}
		return 1
	}

	if statusCode >= 400 {
		ui.Error("HTTP %d", statusCode)
		ui.Step("ROOT CAUSE ANALYSIS")
		switch statusCode {
		case 401, 403:
			fmt.Println("  " + ui.Red("Authentication rejected."))
			fmt.Println("  This does " + ui.Yellow("not") + " necessarily mean the license was revoked.")
			fmt.Println("  It means the access token used in the request could not be verified by the server.")
			fmt.Println("  If the agent is actively running, it will gracefully fall back to the offline grace period.")
			fmt.Println("  If this persists past the token rotation window (~15 min), contact Obylon Support.")
		case 404:
			fmt.Println("  " + ui.Red("Endpoint or license not found."))
			fmt.Println("  The remote database no longer holds a record for this license node.")
		default:
			fmt.Println("  Unexpected server error.")
		}
		if *dev {
			ui.Muted("[dev] response body:\n%s", string(raw))

			ui.Error("Server response: %s", string(raw))
			os.WriteFile("C:\\ProgramData\\Obylon\\logs\\activate_error.txt", raw, 0644)
		}
		return 1
	}

	ui.Success("HTTP %d OK", statusCode)

	ui.Step("CRYPTOGRAPHIC VERIFICATION")
	if !verifiedActivationResponse(data, hwUUID) {
		ui.Error("Signature verification failed")

		os.WriteFile("C:\\ProgramData\\Obylon\\logs\\verify_error.txt", []byte("Signature verification failed\n"), 0644)
		fmt.Println()
		ui.Warn("The response is unsigned, has incomplete signed fields, is bound to another endpoint, or failed verification.")
		if *dev {
			ui.Muted("[dev] payload: %s", string(raw))
		}
		return 1
	}
	ui.Success("Payload signature verified")

	ui.Step("LICENSE STATUS")
	status := api.StringField(data, "status")
	if strings.EqualFold(status, "active") {
		ui.Success("ACTIVE (expires: %s)", api.StringField(data, "expires_at"))
	} else {
		ui.Error("%s", strings.ToUpper(status))
	}

	fmt.Println()
	ui.Success("Diagnostic complete. System operational.")
	fmt.Println()
	return 0
}

// ---------------------------------------------------------------------
// deactivate
// ---------------------------------------------------------------------

func runDeactivate(args []string) int {
	fs, dev, _ := newFlagSet("deactivate")
	yes := fs.Bool("yes", false, "skip the confirmation prompt")
	fs.BoolVar(yes, "y", false, "alias for --yes")
	if err := fs.Parse(args); err != nil {
		return usageErr("deactivate", err.Error())
	}

	if !*yes && !ui.Confirm("This will wipe the local vault.") {
		return 0
	}

	hwUUID, _ := identity.LoadOrCreateHardwareUUID()
	target := map[string]interface{}{"hardware_uuid": hwUUID, "type": "device"}
	if !requireCLIActionAuthorization("obylon.endpoint.deactivate", target) {
		return 1
	}

	targets := []string{paths.IdentityFile(), paths.AliasFile(), paths.VaultFile(), paths.VaultDBFile()}
	for _, p := range targets {
		if _, err := os.Stat(p); err != nil {
			continue // doesn't exist — nothing to remove
		}
		_ = platform.UnhideFile(p)
		if err := os.Remove(p); err != nil {
			ui.Error("Error clearing vault: %v", err)
			if *dev {
				ui.Muted("[dev] failed removing %s", p)
			}
			return 1
		}
	}
	ui.Success("Vault cleared successfully. The agent is now deactivated.")
	return 0
}

// ---------------------------------------------------------------------
// reset-identity
// ---------------------------------------------------------------------

func runResetIdentity(args []string) int {
	fs, _, _ := newFlagSet("reset-identity")
	confirm := fs.Bool("confirm", false, "confirm the identity wipe")
	if err := fs.Parse(args); err != nil {
		return usageErr("reset-identity", err.Error())
	}
	if !*confirm {
		ui.Error(`the --confirm flag is required — this wipes machine identity for image capture`)
		return 1
	}

	hwUUID, _ := identity.LoadOrCreateHardwareUUID()
	target := map[string]interface{}{"hardware_uuid": hwUUID, "type": "device"}
	if !requireCLIActionAuthorization("obylon.identity.reset", target) {
		return 1
	}

	targets := []string{paths.IdentityFile(), paths.VaultFile(), paths.AliasFile()}
	for _, p := range targets {
		if _, err := os.Stat(p); err != nil {
			continue
		}
		_ = platform.UnhideFile(p)
		if err := os.Remove(p); err != nil {
			ui.Error("Failed to remove %s: %v", filepath.Base(p), err)
			continue
		}
		ui.Success("Removed %s", filepath.Base(p))
	}
	fmt.Println()
	ui.Success("Identity wiped. Safe to sysprep/image capture.")
	ui.Muted("The server-side license entitlement is NOT affected.")
	return 0
}

// ---------------------------------------------------------------------
// small formatting helpers shared by the commands above
// ---------------------------------------------------------------------

func parseISO(s string) (time.Time, error) {
	layouts := []string{time.RFC3339, time.RFC3339Nano, "2006-01-02T15:04:05", "2006-01-02"}
	var lastErr error
	for _, layout := range layouts {
		if t, err := time.Parse(layout, s); err == nil {
			return t, nil
		} else {
			lastErr = err
		}
	}
	return time.Time{}, lastErr
}

func safeSlice(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

func formatHeartbeat(s string) string {
	return strings.ReplaceAll(safeSlice(s, 16), "T", " ")
}
