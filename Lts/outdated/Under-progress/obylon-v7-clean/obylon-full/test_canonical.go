package main
import (
    "fmt"
    "encoding/json"
    "strings"
)

func signFieldJSON(payload map[string]interface{}, key string) []byte {
	v, ok := payload[key]
	if !ok || v == nil {
		return []byte("null")
	}
	b, _ := json.Marshal(v)
	return b
}

func canonicalSignPayload(payload map[string]interface{}, hardwareUUID string) string {
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
	return b.String()
}

func main() {
    p := map[string]interface{}{
        "license_id": "456",
        "node_id": "123",
        "expires_at": nil,
        "issued_at": "2026-08-29T00:00:00Z",
        "status": "active",
    }
    fmt.Println(canonicalSignPayload(p, "abc"))
}
