package main

import (
	"fmt"
	"strings"
)

func canonicalSignPayload(payload map[string]interface{}, hardwareUUID string) []byte {
	var b strings.Builder
	b.WriteString("{")

	signFieldJSON(&b, payload, "license_id")
	b.WriteString(",")
	signFieldJSON(&b, payload, "node_id")
	b.WriteString(",")

	b.WriteString("hardware_uuid":)
	b.WriteString(" + hardwareUUID + ")
	b.WriteString(",")

	signFieldJSON(&b, payload, "expires_at")
	b.WriteString(",")
	signFieldJSON(&b, payload, "issued_at")
	b.WriteString(",")
	signFieldJSON(&b, payload, "status")

	b.WriteString("}")
	return []byte(b.String())
}

func signFieldJSON(b *strings.Builder, payload map[string]interface{}, key string) {
	b.WriteString(" + key + ":)
	val, ok := payload[key]
	if !ok || val == nil {
		b.WriteString("null")
		return
	}
	if strVal, isStr := val.(string); isStr {
		b.WriteString(" + strVal + ")
		return
	}
	b.WriteString("null")
}

func main() {
	payload := map[string]interface{}{
		"license_id": "456",
		"node_id":    "123",
		"expires_at": nil,
		"issued_at":  "2026-08-29T13:43:53.000Z",
		"status":     "active",
	}
	fmt.Println("GO sign_payload:", string(canonicalSignPayload(payload, "TEST-UUID")))
}
