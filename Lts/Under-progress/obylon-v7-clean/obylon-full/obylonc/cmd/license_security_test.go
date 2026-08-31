package cmd

import "testing"

func TestVerifiedActivationResponseRejectsUnsignedOrInvalidPayloads(t *testing.T) {
	hardwareUUID := "endpoint-a"
	validFields := map[string]interface{}{
		"license_id": "license",
		"node_id":    "node",
		"issued_at":  "2026-08-31T00:00:00+00:00",
		"status":     "active",
		"expires_at": nil,
	}

	if verifiedActivationResponse(validFields, hardwareUUID) {
		t.Fatal("an unsigned license response must be rejected")
	}

	wrongEndpoint := map[string]interface{}{
		"license_id":   "license",
		"node_id":      "node",
		"issued_at":    "2026-08-31T00:00:00+00:00",
		"status":       "active",
		"hardware_uuid": "endpoint-b",
		"server_sig":   "not-a-valid-signature",
	}
	if verifiedActivationResponse(wrongEndpoint, hardwareUUID) {
		t.Fatal("a response bound to another endpoint must be rejected before use")
	}
}

func TestBoundedGraceDaysCapsServerValue(t *testing.T) {
	if got := boundedGraceDays(map[string]interface{}{"grace_days": float64(90)}); got != "14" {
		t.Fatalf("got %q, want capped grace of 14 days", got)
	}
	if got := boundedGraceDays(map[string]interface{}{"grace_days": float64(-1)}); got != "0" {
		t.Fatalf("got %q, want non-negative grace of 0 days", got)
	}
}
