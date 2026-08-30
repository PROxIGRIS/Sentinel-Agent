package cmd

import (
	"fmt"
	"os"
	"path/filepath"
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

	hostname, _ := os.Hostname()
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
	statusCode, data, raw, err := client.Activate(api.ActivateRequest{
		LicenseKey:          licenseKey,
		Hostname:            hostname,
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

	if sig := api.StringField(data, "server_sig"); sig != "" {
		if !api.Verify(data, hwUUID, sig) {
			sp.Fail("Activation failed: server response failed cryptographic verification.")
			ui.Warn("This can indicate tampering, a MITM proxy, or a key-rotation issue — contact Obylon Support with this output.")
			if *dev {
				ui.Muted("[dev] payload: %s", string(raw))
			}
			return 1
		}
	}

	nowISO := time.Now().UTC().Format(time.RFC3339)
	issuedAt := api.StringField(data, "issued_at")
	if issuedAt == "" {
		issuedAt = nowISO
	}
	graceDays := "14"
	if gd, ok := data["grace_days"]; ok && gd != nil {
		graceDays = fmt.Sprintf("%v", gd)
	}

	v := vault.New()
	v.SetMany(map[string]string{
		"SUPABASE_URL":                       api.StringField(data, "supabase_url"),
		"SUPABASE_ANON_KEY":                  api.StringField(data, "anon_key"),
		"ACCESS_TOKEN":                       api.StringField(data, "access_token"),
		"REFRESH_TOKEN":                      api.StringField(data, "refresh_token"),
		"LICENSE_ID":                         api.StringField(data, "license_id"),
		"NODE_ID":                            api.StringField(data, "node_id"),
		"LICENSE_STATUS":                     "active",
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
		ui.Warn("This workstation has not been activated. Run: obylonc activate <LICENSE_KEY>")
		return 0
	}

	status := v.Get("LICENSE_STATUS")
	expiresStr := v.Get("EXPIRES_AT")
	lastHB := v.Get("LAST_HEARTBEAT_OK_AT")
	grace := v.Get("GRACE_DAYS")

	statusColor := ui.Red
	if strings.EqualFold(status, "active") {
		statusColor = ui.Green
	}
	var lines []string
	lines = append(lines, fmt.Sprintf("%-16s%s", "Status:", statusColor(strings.ToUpper(status))))

	if expiresStr != "" {
		if expDT, perr := parseISO(expiresStr); perr == nil {
			days := int(time.Until(expDT) / (24 * time.Hour))
			if days >= 0 {
				lines = append(lines, fmt.Sprintf("%-16s%s (%d days remaining)", "Expiration:", safeSlice(expiresStr, 10), days))
			} else {
				lines = append(lines, fmt.Sprintf("%-16s%s", "Expiration:", ui.Red(fmt.Sprintf("Expired %d days ago", -days))))
			}
		}
	}
	if lastHB != "" {
		lines = append(lines, fmt.Sprintf("%-16s%s UTC", "Last Heartbeat:", formatHeartbeat(lastHB)))
	}
	if grace != "" {
		lines = append(lines, fmt.Sprintf("%-16s%s days", "Offline Grace:", grace))
	}
	lines = append(lines, "")
	lines = append(lines, fmt.Sprintf("%-16s%s", "Node ID:", ui.Dim(v.Get("NODE_ID"))))
	lines = append(lines, fmt.Sprintf("%-16sv%s", "Agent Version:", Version))

	ui.PrintBox("OBYLON SENTINEL STATUS", lines, ui.Blue)
	return 0
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
	if sig := api.StringField(data, "server_sig"); sig != "" {
		if !api.Verify(data, hwUUID, sig) {
			ui.Error("Signature verification failed")

		os.WriteFile("C:\\ProgramData\\Obylon\\logs\\verify_error.txt", []byte("Signature verification failed\n"), 0644)
			fmt.Println()
			ui.Warn("What does this mean?")
			fmt.Println("  The server's response could not be cryptographically verified.")
			fmt.Println("  This usually indicates a payload mismatch or an ongoing key-rotation issue,")
			fmt.Println("  NOT a revoked license. Please contact Obylon Support with this output.")
			if *dev {
				ui.Muted("[dev] payload: %s", string(raw))
			}
			return 1
		}
		ui.Success("Payload signature verified")
	} else {
		ui.Warn("No server signature returned in payload")
	}

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
