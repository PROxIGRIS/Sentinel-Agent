// Package vault reads and writes the same encrypted config file the Python
// agent's ObylonVault class uses: JSON, encrypted at rest with Windows DPAPI
// (CRYPTPROTECT_LOCAL_MACHINE, no extra entropy), stored at
// %PROGRAMDATA%\Obylon\obylon.enc. obylonc and the agent can therefore read
// each other's writes with no IPC needed.
//
// One deliberate behavior difference from the Python agent: on a corrupt or
// foreign-machine vault, the agent silently deletes the file and starts
// fresh. obylonc treats that as an error and reports it instead — an
// interactively-run admin tool shouldn't quietly destroy state. Use
// `obylonc reset-identity --confirm` or `obylonc deactivate` to clear it
// explicitly.
package vault

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"obylonc/internal/paths"
	"obylonc/internal/platform"
)

// Vault is an in-memory view of the encrypted config file. All values are
// normalized to strings on load, matching how the Python side treats them
// once written via ObylonVault.set() (which always does self._data[key] =
// str(value)) — see normalizeJSONValue for the one place a legacy numeric
// field is coerced.
type Vault struct {
	path   string
	data   map[string]string
	loaded bool
}

// New returns a Vault bound to the standard shared path.
func New() *Vault {
	return &Vault{path: paths.VaultFile(), data: map[string]string{}}
}

// Path returns the file this vault reads from / writes to.
func (v *Vault) Path() string { return v.path }

// Load reads and decrypts the vault file. ok is false (with a nil error)
// when the workstation simply hasn't been activated yet — that's the normal
// "not an error" case every caller needs to check first.
func (v *Vault) Load() (ok bool, err error) {
	b, err := os.ReadFile(v.path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("could not read vault file: %w", err)
	}
	plain, err := platform.DecryptDPAPI(b)
	if err != nil {
		return false, fmt.Errorf("vault decrypt failed (corrupt file, or a vault copied from another machine — DPAPI keys are per-machine): %w", err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(plain, &raw); err != nil {
		return false, fmt.Errorf("vault content is not valid JSON: %w", err)
	}
	data := make(map[string]string, len(raw))
	for k, rm := range raw {
		data[k] = normalizeJSONValue(rm)
	}
	v.data = data
	v.loaded = true
	return true, nil
}

// normalizeJSONValue coerces any JSON scalar to its string form. This
// matters because the Python agent occasionally stores raw JSON numbers
// (e.g. GRACE_DAYS from an activation response) rather than strings, and Go
// won't silently unmarshal a number into a string field the way Python's
// dynamically-typed dict does.
func normalizeJSONValue(rm json.RawMessage) string {
	var s string
	if err := json.Unmarshal(rm, &s); err == nil {
		return s
	}
	var f float64
	if err := json.Unmarshal(rm, &f); err == nil {
		if f == math.Trunc(f) {
			return strconv.FormatInt(int64(f), 10)
		}
		return strconv.FormatFloat(f, 'f', -1, 64)
	}
	var bv bool
	if err := json.Unmarshal(rm, &bv); err == nil {
		return strconv.FormatBool(bv)
	}
	trimmed := strings.TrimSpace(string(rm))
	if trimmed == "null" {
		return ""
	}
	return trimmed
}

// Get returns a stored value, or "" if absent — mirrors ObylonVault.get().
func (v *Vault) Get(key string) string {
	return v.data[key]
}

// Set stores a value in memory only; call Save to persist.
func (v *Vault) Set(key, value string) {
	if v.data == nil {
		v.data = map[string]string{}
	}
	v.data[key] = value
}

// Delete removes one value without disturbing unrelated agent state.
func (v *Vault) Delete(key string) {
	delete(v.data, key)
}

// SetMany stores several values at once (used after a successful activate).
func (v *Vault) SetMany(m map[string]string) {
	for k, val := range m {
		v.Set(k, val)
	}
}

// Data returns a shallow copy of everything currently loaded/set, handy for
// support-bundle dumps or building a signature-verification payload.
func (v *Vault) Data() map[string]string {
	out := make(map[string]string, len(v.data))
	for k, val := range v.data {
		out[k] = val
	}
	return out
}

// Save encrypts and writes the current in-memory data back to disk. If the
// primary %PROGRAMDATA% path isn't writable (e.g. running as a non-admin
// user), it degrades to a per-user fallback file, same as the agent does,
// and returns a non-fatal error describing the degraded state so the caller
// can warn the user.
func (v *Vault) Save() error {
	if v.data == nil {
		v.data = map[string]string{}
	}
	plain, err := json.Marshal(v.data)
	if err != nil {
		return fmt.Errorf("could not encode vault data: %w", err)
	}
	enc, err := platform.EncryptDPAPI(plain)
	if err != nil {
		return fmt.Errorf("vault encrypt failed: %w", err)
	}

	dir := filepath.Dir(v.path)
	if mkErr := os.MkdirAll(dir, 0o755); mkErr != nil {
		return v.writeFallback(enc, fmt.Errorf("could not create %s: %w", dir, mkErr))
	}
	if writeErr := writeAtomically(v.path, enc); writeErr != nil {
		return v.writeFallback(enc, writeErr)
	}
	_ = platform.HideFile(v.path)
	v.loaded = true
	return nil
}

func (v *Vault) writeFallback(enc []byte, causeErr error) error {
	fallback := paths.VaultFallbackFile()
	if werr := writeAtomically(fallback, enc); werr != nil {
		return fmt.Errorf("primary vault write failed (%v) and fallback write also failed (%v)", causeErr, werr)
	}
	_ = platform.HideFile(fallback)
	v.path = fallback
	v.loaded = true
	return fmt.Errorf("primary vault path unavailable (%v) — wrote a degraded fallback vault to %s; re-run as Administrator to fix this permanently", causeErr, fallback)
}

func writeAtomically(path string, data []byte) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}

	temporaryFile, err := os.CreateTemp(dir, ".obylon-vault-*.tmp")
	if err != nil {
		return err
	}
	temporaryPath := temporaryFile.Name()
	keepTemporary := true
	defer func() {
		if keepTemporary {
			_ = temporaryFile.Close()
			_ = os.Remove(temporaryPath)
		}
	}()

	if err := temporaryFile.Chmod(0o600); err != nil {
		return err
	}
	if _, err := temporaryFile.Write(data); err != nil {
		return err
	}
	if err := temporaryFile.Sync(); err != nil {
		return err
	}
	if err := temporaryFile.Close(); err != nil {
		return err
	}

	_ = platform.UnhideFile(path)
	if err := os.Rename(temporaryPath, path); err != nil {
		return err
	}
	keepTemporary = false
	return nil
}

// Loaded reports whether Load() has successfully populated this vault.
func (v *Vault) Loaded() bool { return v.loaded }
