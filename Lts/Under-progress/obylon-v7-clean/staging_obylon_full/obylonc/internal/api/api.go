// Package api talks to the same Obylon licensing endpoints the Python agent
// uses for activation and license heartbeats, and verifies the Ed25519
// signatures the server attaches to those responses.
package api

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"
)

// ObylonProjectURL and EnrollmentEndpoint mirror the constants in
// Obylon.py exactly (they're a Supabase project URL + anon key, not
// secrets — the actual gate is server-side row-level security).
const (
	ObylonProjectURL   = "https://ozruikfnrmmvhvozgnoo.supabase.co"
	EnrollmentEndpoint = ObylonProjectURL + "/functions/v1"
	ObylonAnonKey      = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im96cnVpa2Zucm1tdmh2b3pnbm9vIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg0OTQ3NDIsImV4cCI6MjA5NDA3MDc0Mn0.5x-1W8ksL2Bd5Mt_JF7zmBu3crfHJLWAls3kTKBEWEY"
)

// Client is a thin wrapper around http.Client for the two calls obylonc
// needs: activation and a license heartbeat (used by both `status`'s
// underlying data and `diagnose`).
type Client struct {
	HTTP *http.Client
}

// NewClient returns a Client with the given request timeout.
func NewClient(timeout time.Duration) *Client {
	return &Client{HTTP: &http.Client{Timeout: timeout}}
}

// ActivateRequest is the body sent to POST {EnrollmentEndpoint}/activate.
type ActivateRequest struct {
	LicenseKey          string `json:"license_key"`
	Hostname            string `json:"hostname"`
	HardwareUUID        string `json:"hardware_uuid"`
	HardwareFingerprint string `json:"hardware_fingerprint"`
}

// postJSON POSTs payload as JSON with the given headers and always returns
// the HTTP status code plus whatever the body decoded to, if it was JSON.
// err is only set for transport-level failures (DNS, connection refused,
// timeout, TLS) — a non-2xx HTTP response is NOT an error here, callers
// branch on statusCode themselves, mirroring how Obylon.py distinguishes
// urllib.error.HTTPError (has a status+body) from urllib.error.URLError
// (no response at all).
func (c *Client) postJSON(url string, headers map[string]string, payload interface{}) (statusCode int, parsed map[string]interface{}, raw []byte, err error) {
	var bodyReader io.Reader
	if payload != nil {
		b, mErr := json.Marshal(payload)
		if mErr != nil {
			return 0, nil, nil, mErr
		}
		bodyReader = bytes.NewReader(b)
	}
	req, err := http.NewRequest(http.MethodPost, url, bodyReader)
	if err != nil {
		return 0, nil, nil, err
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return 0, nil, nil, err
	}
	defer resp.Body.Close()
	raw, _ = io.ReadAll(resp.Body)
	_ = json.Unmarshal(raw, &parsed) // best-effort; non-JSON bodies just leave parsed nil
	return resp.StatusCode, parsed, raw, nil
}

// Activate calls POST {EnrollmentEndpoint}/activate with the Obylon anon key
// (the activation endpoint's own auth — it issues a real session token in
// the response on success).
func (c *Client) Activate(req ActivateRequest) (statusCode int, parsed map[string]interface{}, raw []byte, err error) {
	headers := map[string]string{
		"apikey":        ObylonAnonKey,
		"Authorization": "Bearer " + ObylonAnonKey,
	}
	return c.postJSON(EnrollmentEndpoint+"/activate", headers, req)
}

// Heartbeat calls POST {EnrollmentEndpoint}/license_heartbeat with the
// workstation's own bearer access token.
func (c *Client) Heartbeat(accessToken, hardwareUUID string) (statusCode int, parsed map[string]interface{}, raw []byte, err error) {
	headers := map[string]string{"Authorization": "Bearer " + accessToken}
	payload := map[string]string{"hardware_uuid": hardwareUUID}
	return c.postJSON(EnrollmentEndpoint+"/license_heartbeat", headers, payload)
}

// ErrorType extracts the {"error": "..."} discriminator the Obylon edge
// functions return on failure, e.g. "node_limit_reached", "invalid_key".
func ErrorType(parsed map[string]interface{}) string {
	if parsed == nil {
		return ""
	}
	if v, ok := parsed["error"].(string); ok {
		return v
	}
	return ""
}

// StringField is a small helper for pulling a string out of a parsed JSON
// response body, returning "" for anything absent/non-string.
func StringField(parsed map[string]interface{}, key string) string {
	if parsed == nil {
		return ""
	}
	if v, ok := parsed[key].(string); ok {
		return v
	}
	return ""
}

// ---------------------------------------------------------------------
// Signature verification
//
// Reproduces Obylon.py's verify_server_signature() field-for-field: the
// same six fields, the same fixed order, and the same compact (no
// whitespace) JSON encoding — any difference in byte layout would make a
// valid signature fail to verify.
// ---------------------------------------------------------------------

// licenseVerifyKeyB64 is the Obylon license server's Ed25519 public key.
// This is a verification key, not a secret — publishing it carries no risk,
// the same way the agent embeds it directly in source.
const licenseVerifyKeyB64 = "oQYy7eR/qxZOlKw/v9QNpmrcDWpNKGOx2YM0q++oXaY="

// Verify checks serverSig (base64 Ed25519 signature) against a canonical
// payload built from license_id, node_id, expires_at, issued_at, and status
// in payload, plus hardware_uuid — which is always the caller's own
// hardwareUUID, never taken from payload, so a signature can't be replayed
// onto a different machine. Any error (bad key, bad signature encoding,
// mismatch) simply returns false, matching the Python function's blanket
// except-and-return-False behavior.
func Verify(payload map[string]interface{}, hardwareUUID, serverSig string) bool {
	if serverSig == "" {
		return false
	}
	keyBytes, err := base64.StdEncoding.DecodeString(licenseVerifyKeyB64)
	if err != nil || len(keyBytes) != ed25519.PublicKeySize {
		return false
	}
	sigBytes, err := base64.StdEncoding.DecodeString(serverSig)
	if err != nil {
		return false
	}
	return ed25519.Verify(ed25519.PublicKey(keyBytes), canonicalSignPayload(payload, hardwareUUID), sigBytes)
}

// signFieldJSON returns the exact JSON encoding of payload[key], preserving
// its original JSON type. This matters because Python's json.dumps()
// re-serializes whatever native type payload.get(key) returned — a str
// stays quoted, an int/float/bool stays bare, and dict.get() returns None
// (-> JSON null) for a missing key. Coercing every value to a Go string
// first (an earlier version of this function did that) would silently
// wrap a numeric or boolean field in quotes and break every valid
// signature the moment the server ever sends one of these six fields as
// a non-string JSON value — confirmed by generating the canonical payload
// both ways for a numeric expires_at and diffing against what Python's
// json.dumps actually produces for the same input.
func signFieldJSON(payload map[string]interface{}, key string) []byte {
	v, ok := payload[key]
	if !ok || v == nil {
		return []byte("null")
	}
	b, err := json.Marshal(v)
	if err != nil {
		return []byte("null")
	}
	return b
}

func canonicalSignPayload(payload map[string]interface{}, hardwareUUID string) []byte {
	hwUUIDJSON, _ := json.Marshal(hardwareUUID)

	var b strings.Builder
	b.WriteByte('{')
	b.WriteString(`"license_id":`)
	b.Write(signFieldJSON(payload, "license_id"))
	b.WriteString(`,"node_id":`)
	b.Write(signFieldJSON(payload, "node_id"))
	b.WriteString(`,"hardware_uuid":`)
	b.Write(hwUUIDJSON)
	b.WriteString(`,"expires_at":`)
	b.Write(signFieldJSON(payload, "expires_at"))
	b.WriteString(`,"issued_at":`)
	b.Write(signFieldJSON(payload, "issued_at"))
	b.WriteString(`,"status":`)
	b.Write(signFieldJSON(payload, "status"))
	b.WriteByte('}')
	return []byte(b.String())
}
