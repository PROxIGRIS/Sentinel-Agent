//go:build !windows

package platform

import "errors"

// errUnsupportedPlatform is returned by the DPAPI functions, which are
// inherently Windows-only (same as the Python agent, which can't even
// import win32crypt elsewhere). Everything else below is a harmless no-op
// so `logs`, `ai`, `version`, and `--help` all still work for local
// development off Windows.
var errUnsupportedPlatform = errors.New("this operation uses Windows-only APIs and is only available on Windows")

// EncryptDPAPI is only available on Windows.
func EncryptDPAPI(plain []byte) ([]byte, error) {
	return nil, errUnsupportedPlatform
}

// DecryptDPAPI is only available on Windows.
func DecryptDPAPI(cipher []byte) ([]byte, error) {
	return nil, errUnsupportedPlatform
}

// HideFile is a no-op outside Windows.
func HideFile(path string) error {
	return nil
}

// UnhideFile is a no-op outside Windows.
func UnhideFile(path string) error {
	return nil
}

// HardwareFingerprint outside Windows returns the hash of the same
// "unknown|unknown|unknown" placeholder the Python agent falls back to when
// its WMI query fails entirely — there is no WMI to query.
func HardwareFingerprint() string {
	return sha256Hex("unknown|unknown|unknown")
}

// EnableConsoleANSI is a no-op outside Windows — every other supported
// terminal already interprets ANSI escapes natively.
func EnableConsoleANSI() {}

// ThreadSample/ProcessSample mirror the Windows types so doctor.go
// compiles unchanged on every platform; SnapshotProcesses never actually
// populates one here.
type ThreadSample struct {
	TID        uint32
	Name       string
	KernelTime uint64
	UserTime   uint64
}

func (t ThreadSample) CPUTime100ns() uint64 { return t.KernelTime + t.UserTime }

type ProcessSample struct {
	PID        uint32
	Name       string
	Found      bool
	KernelTime uint64
	UserTime   uint64
	Threads    []ThreadSample
}

func (p ProcessSample) CPUTime100ns() uint64 { return p.KernelTime + p.UserTime }

// CurrentProcessCPUTime is Windows-only.
func CurrentProcessCPUTime() (kernel, user uint64, ok bool) {
	return 0, 0, false
}

// SnapshotProcesses is Windows-only (Toolhelp32 has no equivalent this
// codebase reaches for elsewhere) — every requested name comes back
// Found: false rather than erroring.
func SnapshotProcesses(exeNames []string) ([]ProcessSample, error) {
	result := make([]ProcessSample, len(exeNames))
	for i, n := range exeNames {
		result[i] = ProcessSample{Name: n}
	}
	return result, errUnsupportedPlatform
}
