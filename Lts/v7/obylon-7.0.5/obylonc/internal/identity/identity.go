// Package identity resolves this workstation's identity the same way the
// Python agent does: a random, machine-scoped UUID minted once and cached
// in a file (LoadOrCreateHardwareUUID), plus a WMI-derived hash used to
// detect cloned disk images (HardwareFingerprint, implemented per-OS in
// internal/platform).
package identity

import (
	"crypto/rand"
	"fmt"
	"os"
	"strings"

	"obylonc/internal/paths"
	"obylonc/internal/platform"
)

func newUUIDv4() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // RFC 4122 variant
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16]), nil
}

// LoadOrCreateHardwareUUID reads the cached machine identity file, or mints
// and persists a new random UUID if none exists yet. It always returns a
// usable id — on a write failure it still returns the freshly minted id
// (ephemeral for this run) alongside the error, matching the agent's
// load_or_create_hardware_uuid().
func LoadOrCreateHardwareUUID() (string, error) {
	idFile := paths.IdentityFile()
	if data, err := os.ReadFile(idFile); err == nil {
		if v := strings.TrimSpace(string(data)); v != "" {
			return v, nil
		}
	}

	newID, err := newUUIDv4()
	if err != nil {
		return "", fmt.Errorf("failed to generate a machine identity: %w", err)
	}

	dir := paths.ObylonDir()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return newID, fmt.Errorf("could not persist machine identity, using an ephemeral id for this run: %w", err)
	}
	if err := os.WriteFile(idFile, []byte(newID), 0o600); err != nil {
		return newID, fmt.Errorf("could not persist machine identity, using an ephemeral id for this run: %w", err)
	}
	_ = platform.HideFile(idFile)
	return newID, nil
}

// HardwareFingerprint returns this machine's WMI-derived fingerprint hash
// (sha256 of motherboard UUID | disk serial | MAC address). It's a thin
// wrapper so callers keep saying identity.HardwareFingerprint() — the real,
// per-OS implementation lives in internal/platform.
func HardwareFingerprint() string {
	return platform.HardwareFingerprint()
}
