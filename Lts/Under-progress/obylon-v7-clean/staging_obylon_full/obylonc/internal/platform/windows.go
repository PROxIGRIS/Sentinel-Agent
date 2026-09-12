//go:build windows

// Package platform holds every piece of OS-specific code obylonc needs,
// split into exactly two files by Go build tag: this one (real Windows
// syscalls/WMI) and other.go (stubs so the rest of the CLI still builds on
// macOS/Linux for local development). Every other package in this project
// is pure, portable Go that calls into these functions rather than doing
// its own platform detection.
package platform

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

var (
	modkernel32 = syscall.NewLazyDLL("kernel32.dll")
	modcrypt32  = syscall.NewLazyDLL("crypt32.dll")

	procLocalFree          = modkernel32.NewProc("LocalFree")
	procSetFileAttributesW = modkernel32.NewProc("SetFileAttributesW")
	procGetConsoleMode     = modkernel32.NewProc("GetConsoleMode")
	procSetConsoleMode     = modkernel32.NewProc("SetConsoleMode")
	procCryptProtectData   = modcrypt32.NewProc("CryptProtectData")
	procCryptUnprotectData = modcrypt32.NewProc("CryptUnprotectData")
)

// ---------------------------------------------------------------------
// DPAPI (used by internal/vault to read/write the encrypted config file
// shared with the Python agent)
// ---------------------------------------------------------------------

// dataBlob mirrors the Win32 DATA_BLOB struct used by CryptProtectData /
// CryptUnprotectData.
type dataBlob struct {
	cbData uint32
	pbData *byte
}

// cryptProtectLocalMachine: the blob is decryptable by any user account on
// this machine (not tied to the encrypting user's profile key). This must
// match the flag the Python agent's win32crypt.CryptProtectData call uses,
// or the two won't be able to read each other's vault.
const cryptProtectLocalMachine = 0x4

// vaultDescription is passed as CryptProtectData's descriptive string. It is
// metadata only — DPAPI does not require it to decrypt, and no entropy is
// used on either side, matching the agent's
// CryptProtectData(data, "ObylonSecure", None, None, None, CRYPTPROTECT_LOCAL_MACHINE).
const vaultDescription = "ObylonSecure"

func bytesToBlob(b []byte) dataBlob {
	if len(b) == 0 {
		return dataBlob{}
	}
	return dataBlob{cbData: uint32(len(b)), pbData: &b[0]}
}

func blobToBytes(b dataBlob) []byte {
	if b.cbData == 0 || b.pbData == nil {
		return nil
	}
	out := make([]byte, b.cbData)
	copy(out, unsafe.Slice(b.pbData, int(b.cbData)))
	return out
}

// EncryptDPAPI wraps CryptProtectData with CRYPTPROTECT_LOCAL_MACHINE and no
// optional entropy.
func EncryptDPAPI(plain []byte) ([]byte, error) {
	in := bytesToBlob(plain)
	var out dataBlob
	descr, err := syscall.UTF16PtrFromString(vaultDescription)
	if err != nil {
		return nil, err
	}
	r, _, callErr := procCryptProtectData.Call(
		uintptr(unsafe.Pointer(&in)),
		uintptr(unsafe.Pointer(descr)),
		0, // pOptionalEntropy
		0, // pvReserved
		0, // pPromptStruct
		uintptr(cryptProtectLocalMachine),
		uintptr(unsafe.Pointer(&out)),
	)
	runtime.KeepAlive(plain)
	runtime.KeepAlive(in)
	if r == 0 {
		return nil, fmt.Errorf("CryptProtectData failed: %w", callErr)
	}
	defer procLocalFree.Call(uintptr(unsafe.Pointer(out.pbData)))
	return blobToBytes(out), nil
}

// DecryptDPAPI wraps CryptUnprotectData. We don't need the descriptive
// string back, so ppszDataDescr is NULL.
func DecryptDPAPI(cipher []byte) ([]byte, error) {
	in := bytesToBlob(cipher)
	var out dataBlob
	r, _, callErr := procCryptUnprotectData.Call(
		uintptr(unsafe.Pointer(&in)),
		0, // ppszDataDescr
		0, // pOptionalEntropy
		0, // pvReserved
		0, // pPromptStruct
		uintptr(cryptProtectLocalMachine),
		uintptr(unsafe.Pointer(&out)),
	)
	runtime.KeepAlive(cipher)
	runtime.KeepAlive(in)
	if r == 0 {
		return nil, fmt.Errorf("CryptUnprotectData failed: %w", callErr)
	}
	defer procLocalFree.Call(uintptr(unsafe.Pointer(out.pbData)))
	return blobToBytes(out), nil
}

// ---------------------------------------------------------------------
// File attributes (used by internal/vault and internal/identity to keep
// their small state files out of a casual directory listing)
// ---------------------------------------------------------------------

const (
	fileAttributeHidden = 0x2
	fileAttributeNormal = 0x80
)

func setFileAttributes(path string, attrs uint32) error {
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	r, _, callErr := procSetFileAttributesW.Call(uintptr(unsafe.Pointer(p)), uintptr(attrs))
	if r == 0 {
		return callErr
	}
	return nil
}

// HideFile marks path with the Windows FILE_ATTRIBUTE_HIDDEN flag.
func HideFile(path string) error {
	return setFileAttributes(path, fileAttributeHidden)
}

// UnhideFile clears special attributes on path (FILE_ATTRIBUTE_NORMAL),
// which Windows requires before it will let a file be rewritten or deleted
// by a process that doesn't already hold it open.
func UnhideFile(path string) error {
	return setFileAttributes(path, fileAttributeNormal)
}

// ---------------------------------------------------------------------
// Hardware fingerprint (used by internal/identity to detect a cloned disk
// image — same WMI properties the Python agent's
// get_hardware_fingerprint() reads)
// ---------------------------------------------------------------------

const fingerprintTimeout = 60 * time.Second

// fingerprintScript queries Win32_ComputerSystemProduct.UUID, the first
// Win32_DiskDrive.SerialNumber, and the first physical
// Win32_NetworkAdapter.MACAddress, each printed on its own line ("unknown"
// on failure or an empty result). Shelling out to PowerShell/CIM avoids
// linking a WMI/COM library, keeping this a zero-dependency binary.
const fingerprintScript = `
$ErrorActionPreference = 'SilentlyContinue'
function Emit($v) {
  if ([string]::IsNullOrWhiteSpace($v)) { Write-Output "unknown" } else { Write-Output $v.Trim() }
}
try { $u = (Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID } catch { $u = $null }
Emit $u
try { $d = (Get-CimInstance -ClassName Win32_DiskDrive | Where-Object { $_.MediaType -eq 'Fixed hard disk media' } | Sort-Object Index | Select-Object -First 1).SerialNumber } catch { $d = $null }
Emit $d
try {
  $m = (Get-CimInstance -ClassName Win32_NetworkAdapter -Filter "PhysicalAdapter=True" |
        Where-Object { $_.PNPDeviceID -match '^(PCI|SD)' } | 
        Sort-Object { [int]$_.DeviceID } | 
        Select-Object -First 1).MACAddress
} catch { $m = $null }
Emit $m
`

// HardwareFingerprint returns sha256(motherboardUUID|diskSerial|macAddress)
// in hex, identical in shape to the Python agent's HARDWARE_FINGERPRINT.
// Callers that need to make a security decision should use
// HardwareFingerprintWithStatus so an incomplete boot-time WMI response is
// never mistaken for a real machine identity.
func HardwareFingerprint() string {
	sum, _ := HardwareFingerprintWithStatus()
	return sum
}

// HardwareFingerprintWithStatus returns the legacy-compatible hash plus a
// reliability flag. The hash remains available for backwards-compatible
// callers, while the flag requires all three source values to be present and
// the query to have completed successfully.
func HardwareFingerprintWithStatus() (string, bool) {
	components := []string{"unknown", "unknown", "unknown"}

	ctx, cancel := context.WithTimeout(context.Background(), fingerprintTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe",
		"-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", fingerprintScript)
	out, err := cmd.Output()
	if err == nil {
		text := strings.ReplaceAll(strings.TrimSpace(string(out)), "\r\n", "\n")
		lines := strings.Split(text, "\n")
		for i := 0; i < len(components) && i < len(lines); i++ {
			if v := strings.TrimSpace(lines[i]); v != "" {
				components[i] = v
			}
		}
	}

	sum := sha256Hex(strings.Join(components, "|"))
	for _, component := range components {
		if component == "unknown" {
			return sum, false
		}
	}
	return sum, err == nil
}

// ---------------------------------------------------------------------
// Console (used once, at startup, so cmd.exe / older PowerShell hosts
// interpret ANSI color codes — modern Windows Terminal already has this on)
// ---------------------------------------------------------------------

const enableVirtualTerminalProcessing = 0x0004

// EnableConsoleANSI turns on ANSI escape-code interpretation in the current
// console. Best-effort: failures are silently ignored — worst case the CLI
// prints raw escape codes instead of colors, never a crash.
func EnableConsoleANSI() {
	stdout := syscall.Handle(os.Stdout.Fd())
	var mode uint32
	r, _, _ := procGetConsoleMode.Call(uintptr(stdout), uintptr(unsafe.Pointer(&mode)))
	if r == 0 {
		return
	}
	_, _, _ = procSetConsoleMode.Call(uintptr(stdout), uintptr(mode|enableVirtualTerminalProcessing))
}

// ---------------------------------------------------------------------
// Process/thread CPU-time snapshotting (used by `obylonc doctor --profile`)
// ---------------------------------------------------------------------
// Deliberately reads CUMULATIVE CPU time per thread — the same quantity
// Task Manager and every other Windows profiler reads — rather than
// polling continuously. `doctor --profile` takes exactly two snapshots
// (once at the start of the observation window, once at the end) and
// diffs them; nothing in this file runs in a loop, so doctor's own CPU
// use during a 20-minute profile is whatever two Toolhelp32 walks cost —
// a few milliseconds, not a sustained load.

var (
	procCreateToolhelp32Snapshot = modkernel32.NewProc("CreateToolhelp32Snapshot")
	procProcess32FirstW          = modkernel32.NewProc("Process32FirstW")
	procProcess32NextW           = modkernel32.NewProc("Process32NextW")
	procThread32First            = modkernel32.NewProc("Thread32First")
	procThread32Next             = modkernel32.NewProc("Thread32Next")
	procOpenThread               = modkernel32.NewProc("OpenThread")
	procGetThreadTimes           = modkernel32.NewProc("GetThreadTimes")
	procGetThreadDescription     = modkernel32.NewProc("GetThreadDescription")
	procOpenProcess              = modkernel32.NewProc("OpenProcess")
	procGetProcessTimes          = modkernel32.NewProc("GetProcessTimes")
	procCloseHandle              = modkernel32.NewProc("CloseHandle")
	procGetCurrentProcess        = modkernel32.NewProc("GetCurrentProcess")
)

const (
	th32csSnapProcess       = 0x00000002
	th32csSnapThread        = 0x00000004
	invalidHandleValue      = ^uintptr(0)
	threadQueryLimitedInfo  = 0x0800
	processQueryLimitedInfo = 0x1000
	maxPathW                = 260
)

type processEntry32W struct {
	Size            uint32
	CntUsage        uint32
	ProcessID       uint32
	DefaultHeapID   uintptr
	ModuleID        uint32
	CntThreads      uint32
	ParentProcessID uint32
	PriClassBase    int32
	Flags           uint32
	ExeFile         [maxPathW]uint16
}

type threadEntry32 struct {
	Size           uint32
	Usage          uint32
	ThreadID       uint32
	OwnerProcessID uint32
	BasePri        int32
	DeltaPri       int32
	Flags          uint32
}

type filetime struct {
	LowDateTime  uint32
	HighDateTime uint32
}

func (f filetime) as100ns() uint64 {
	return uint64(f.HighDateTime)<<32 | uint64(f.LowDateTime)
}

// ThreadSample is one thread's identity + cumulative CPU time (in 100ns
// units, matching Win32 FILETIME) at the moment it was read.
type ThreadSample struct {
	TID        uint32
	Name       string // from SetThreadDescription; empty if the thread never named itself
	KernelTime uint64
	UserTime   uint64
}

// CPUTime100ns is KernelTime+UserTime — the number doctor actually diffs
// between two samples to compute a percentage.
func (t ThreadSample) CPUTime100ns() uint64 { return t.KernelTime + t.UserTime }

// ProcessSample is one process's identity, its own total CPU time (ground
// truth for the "Unattributed" row), and every thread found inside it.
type ProcessSample struct {
	PID        uint32
	Name       string
	Found      bool
	KernelTime uint64
	UserTime   uint64
	Threads    []ThreadSample
}

func (p ProcessSample) CPUTime100ns() uint64 { return p.KernelTime + p.UserTime }

func toolhelp32Snapshot(flags uint32) (syscall.Handle, error) {
	r, _, err := procCreateToolhelp32Snapshot.Call(uintptr(flags), 0)
	if r == invalidHandleValue || r == 0 {
		return 0, fmt.Errorf("CreateToolhelp32Snapshot: %w", err)
	}
	return syscall.Handle(r), nil
}

func getThreadDescription(tid uint32) string {
	h, _, _ := procOpenThread.Call(uintptr(threadQueryLimitedInfo), 0, uintptr(tid))
	if h == 0 {
		return ""
	}
	defer procCloseHandle.Call(h)

	var strPtr uintptr
	hr, _, _ := procGetThreadDescription.Call(h, uintptr(unsafe.Pointer(&strPtr)))
	if int32(hr) < 0 || strPtr == 0 {
		return ""
	}
	defer procLocalFree.Call(strPtr)

	var chars []uint16
	for i := 0; ; i++ {
		c := *(*uint16)(unsafe.Pointer(strPtr + uintptr(i)*2))
		if c == 0 {
			break
		}
		chars = append(chars, c)
		if i > 512 {
			break
		}
	}
	return syscall.UTF16ToString(chars)
}

func getThreadTimes(tid uint32) (kernel, user uint64, ok bool) {
	h, _, _ := procOpenThread.Call(uintptr(threadQueryLimitedInfo), 0, uintptr(tid))
	if h == 0 {
		return 0, 0, false
	}
	defer procCloseHandle.Call(h)

	var creation, exit, k, u filetime
	r, _, _ := procGetThreadTimes.Call(
		h,
		uintptr(unsafe.Pointer(&creation)),
		uintptr(unsafe.Pointer(&exit)),
		uintptr(unsafe.Pointer(&k)),
		uintptr(unsafe.Pointer(&u)),
	)
	if r == 0 {
		return 0, 0, false
	}
	return k.as100ns(), u.as100ns(), true
}

func getProcessTimes(pid uint32) (kernel, user uint64, ok bool) {
	h, _, _ := procOpenProcess.Call(uintptr(processQueryLimitedInfo), 0, uintptr(pid))
	if h == 0 {
		return 0, 0, false
	}
	defer procCloseHandle.Call(h)

	var creation, exit, k, u filetime
	r, _, _ := procGetProcessTimes.Call(
		h,
		uintptr(unsafe.Pointer(&creation)),
		uintptr(unsafe.Pointer(&exit)),
		uintptr(unsafe.Pointer(&k)),
		uintptr(unsafe.Pointer(&u)),
	)
	if r == 0 {
		return 0, 0, false
	}
	return k.as100ns(), u.as100ns(), true
}

// CurrentProcessCPUTime returns this process's own cumulative kernel+user
// CPU time. `doctor --profile` uses this to report its own footprint
// directly rather than assert it. GetCurrentProcess() returns a
// pseudo-handle that doesn't need closing.
func CurrentProcessCPUTime() (kernel, user uint64, ok bool) {
	h, _, _ := procGetCurrentProcess.Call()
	var creation, exit, k, u filetime
	r, _, _ := procGetProcessTimes.Call(
		h,
		uintptr(unsafe.Pointer(&creation)),
		uintptr(unsafe.Pointer(&exit)),
		uintptr(unsafe.Pointer(&k)),
		uintptr(unsafe.Pointer(&u)),
	)
	if r == 0 {
		return 0, 0, false
	}
	return k.as100ns(), u.as100ns(), true
}

// SnapshotProcesses returns one ProcessSample per requested exe name that's
// currently running (Found: false for any name not currently running).
// Matching is case-insensitive exact basename match.
func SnapshotProcesses(exeNames []string) ([]ProcessSample, error) {
	want := make(map[string]int)
	result := make([]ProcessSample, len(exeNames))
	for i, n := range exeNames {
		result[i] = ProcessSample{Name: n}
		want[strings.ToLower(n)] = i
	}

	snap, err := toolhelp32Snapshot(th32csSnapProcess)
	if err != nil {
		return result, err
	}
	defer procCloseHandle.Call(uintptr(snap))

	var pe processEntry32W
	pe.Size = uint32(unsafe.Sizeof(pe))
	r, _, _ := procProcess32FirstW.Call(uintptr(snap), uintptr(unsafe.Pointer(&pe)))
	for r != 0 {
		name := syscall.UTF16ToString(pe.ExeFile[:])
		if idx, ok := want[strings.ToLower(name)]; ok {
			k, u, kuOK := getProcessTimes(pe.ProcessID)
			result[idx].PID = pe.ProcessID
			result[idx].Found = true
			if kuOK {
				result[idx].KernelTime = k
				result[idx].UserTime = u
			}
			result[idx].Threads = snapshotThreadsForProcess(pe.ProcessID)
		}
		r, _, _ = procProcess32NextW.Call(uintptr(snap), uintptr(unsafe.Pointer(&pe)))
	}
	return result, nil
}

func snapshotThreadsForProcess(pid uint32) []ThreadSample {
	snap, err := toolhelp32Snapshot(th32csSnapThread)
	if err != nil {
		return nil
	}
	defer procCloseHandle.Call(uintptr(snap))

	var threads []ThreadSample
	var te threadEntry32
	te.Size = uint32(unsafe.Sizeof(te))
	r, _, _ := procThread32First.Call(uintptr(snap), uintptr(unsafe.Pointer(&te)))
	for r != 0 {
		if te.OwnerProcessID == pid {
			k, u, ok := getThreadTimes(te.ThreadID)
			if ok {
				threads = append(threads, ThreadSample{
					TID:        te.ThreadID,
					Name:       getThreadDescription(te.ThreadID),
					KernelTime: k,
					UserTime:   u,
				})
			}
		}
		r, _, _ = procThread32Next.Call(uintptr(snap), uintptr(unsafe.Pointer(&te)))
	}
	return threads
}
