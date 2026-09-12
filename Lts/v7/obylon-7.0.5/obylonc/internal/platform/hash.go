package platform

import (
	"crypto/sha256"
	"encoding/hex"
)

// sha256Hex is the one bit of platform.HardwareFingerprint that's identical
// on every OS, so it lives here without a build tag rather than being
// duplicated in windows.go and other.go.
func sha256Hex(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}
