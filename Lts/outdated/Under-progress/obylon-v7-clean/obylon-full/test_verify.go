package main
import (
    "fmt"
    "encoding/json"
    "strings"
    "encoding/base64"
    "crypto/ed25519"
)

const licenseVerifyKeyB64 = "oQYy7eR/qxZOlKw/v9QNpmrcDWpNKGOx2YM0q++oXaY="

func signFieldJSON(payload map[string]interface{}, key string) []byte {
	v, ok := payload[key]
	if !ok || v == nil {
		return []byte("null")
	}
	b, _ := json.Marshal(v)
	return b
}

func canonicalSignPayload(payload map[string]interface{}, hardwareUUID string) []byte {
	hwUUIDJSON, _ := json.Marshal(hardwareUUID)
	var b strings.Builder
	b.WriteByte('{')
	b.WriteString("\"license_id\":")
	b.Write(signFieldJSON(payload, "license_id"))
	b.WriteString(",\"node_id\":")
	b.Write(signFieldJSON(payload, "node_id"))
	b.WriteString(",\"hardware_uuid\":")
	b.Write(hwUUIDJSON)
	b.WriteString(",\"expires_at\":")
	b.Write(signFieldJSON(payload, "expires_at"))
	b.WriteString(",\"issued_at\":")
	b.Write(signFieldJSON(payload, "issued_at"))
	b.WriteString(",\"status\":")
	b.Write(signFieldJSON(payload, "status"))
	b.WriteByte('}')
	return []byte(b.String())
}

func Verify(payload map[string]interface{}, hardwareUUID, sigB64 string) bool {
	sigBytes, err := base64.StdEncoding.DecodeString(sigB64)
	if err != nil { return false }
	keyBytes, err := base64.StdEncoding.DecodeString(licenseVerifyKeyB64)
	if err != nil { return false }
    fmt.Printf("Payload: %s\n", canonicalSignPayload(payload, hardwareUUID))
	return ed25519.Verify(ed25519.PublicKey(keyBytes), canonicalSignPayload(payload, hardwareUUID), sigBytes)
}

func main() {
    p := map[string]interface{}{
        "license_id": "456",
        "node_id": "123",
        "expires_at": nil,
        "issued_at": "2026-08-29T00:00:00Z",
        "status": "active",
    }
    // Signature from earlier JS generation script
    sig := "tWQqQNpL+SXk61QYBdu89vhT5dV9etoRJ+3fUvVVkk3exE4bOsjWZVjmJoWGQnp3JZ85rnqQ/K1+KOvMBIk5Bg=="
    fmt.Println(Verify(p, "abc", sig))
}
