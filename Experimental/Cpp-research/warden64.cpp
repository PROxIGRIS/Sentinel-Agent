/*
 * NEXUS SENTINEL — The Muscle (Sidecar Architecture)
 * Native C++ Win32 API Agent
 * Handles: IPC Named Pipes, Zero-Gap Process Tracking, USB Events, Hardware Lock
 */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <dbt.h>
#include <wbemidl.h>
#include <comdef.h>
#include <iostream>
#include <string>
#include <thread>
#include <atomic>
#include <mutex>

#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")
#pragma comment(lib, "wbemuuid.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "advapi32.lib")

// --- GLOBAL STATE ---
std::atomic<bool> g_IsLocked{ false };
HANDLE g_hPipe = INVALID_HANDLE_VALUE;
std::mutex g_PipeMutex;
HHOOK g_KeyHook = nullptr;
HHOOK g_MouseHook = nullptr;

// --- IPC: SEND TO PYTHON ---
void SendToBrain(const std::string& jsonMsg) {
    std::lock_guard<std::mutex> lock(g_PipeMutex);
    if (g_hPipe == INVALID_HANDLE_VALUE) return;
    
    std::string payload = jsonMsg + "\n";
    DWORD bytesWritten;
    WriteFile(g_hPipe, payload.c_str(), (DWORD)payload.length(), &bytesWritten, NULL);
}

// --- WARDEN: HARDWARE LOCK ---
LRESULT CALLBACK LowLevelKeyboardProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION && g_IsLocked.load(std::memory_order_relaxed)) return 1; // Swallow keystroke
    return CallNextHookEx(g_KeyHook, nCode, wParam, lParam);
}

LRESULT CALLBACK LowLevelMouseProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION && g_IsLocked.load(std::memory_order_relaxed)) return 1; // Swallow mouse
    return CallNextHookEx(g_MouseHook, nCode, wParam, lParam);
}

void EngageLock() {
    if (g_IsLocked.load()) return;
    g_IsLocked.store(true);
    
    // The Ultimate Failsafe: Requires Admin privileges to sever OS input stream
    BlockInput(TRUE); 
    
    std::cout << "[WARDEN] Hardware locked.\n";
}

void DisengageLock() {
    if (!g_IsLocked.load()) return;
    g_IsLocked.store(false);
    BlockInput(FALSE);
    std::cout << "[WARDEN] Hardware released.\n";
}

// --- WARDEN: THE SCALPEL ---
void KillProcess(const std::string& targetName) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return;

    PROCESSENTRY32 pe;
    pe.dwSize = sizeof(pe);
    if (Process32First(snap, &pe)) {
        do {
            std::string procName = pe.szExeFile;
            // Basic case-insensitive comparison
            if (_stricmp(procName.c_str(), targetName.c_str()) == 0) {
                HANDLE hProc = OpenProcess(PROCESS_TERMINATE, FALSE, pe.th32ProcessID);
                if (hProc) {
                    TerminateProcess(hProc, 1);
                    CloseHandle(hProc);
                    std::cout << "[SCALPEL] Terminated: " << targetName << "\n";
                }
            }
        } while (Process32Next(snap, &pe));
    }
    CloseHandle(snap);
}

// --- IPC: RECEIVE FROM PYTHON ---
void PipeListenerThread() {
    char buffer[1024];
    DWORD bytesRead;

    while (true) {
        // Wait for Python to create the pipe server
        g_hPipe = CreateFileA("\\\\.\\pipe\\NexusSentinel", GENERIC_READ | GENERIC_WRITE, 
                              0, NULL, OPEN_EXISTING, 0, NULL);
        
        if (g_hPipe != INVALID_HANDLE_VALUE) {
            std::cout << "[IPC] Tethered to Python Brain.\n";
            
            while (ReadFile(g_hPipe, buffer, sizeof(buffer) - 1, &bytesRead, NULL) && bytesRead > 0) {
                buffer[bytesRead] = '\0';
                std::string cmd(buffer);
                
                // Extremely lightweight string parsing (Zero Dependencies)
                if (cmd.find("\"cmd\":\"lock\"") != std::string::npos) {
                    EngageLock();
                    // We'll let Python handle the duration and send an unlock command
                } 
                else if (cmd.find("\"cmd\":\"unlock\"") != std::string::npos) {
                    DisengageLock();
                }
                else if (cmd.find("\"cmd\":\"kill\"") != std::string::npos) {
                    // Extract target (e.g., {"cmd":"kill", "target":"cmd.exe"})
                    size_t pos = cmd.find("\"target\":\"");
                    if (pos != std::string::npos) {
                        pos += 10;
                        size_t endPos = cmd.find("\"", pos);
                        if (endPos != std::string::npos) {
                            KillProcess(cmd.substr(pos, endPos - pos));
                        }
                    }
                }
            }
            std::cout << "[IPC] Tether broken. Brain disconnected.\n";
            CloseHandle(g_hPipe);
            g_hPipe = INVALID_HANDLE_VALUE;
            
            // Failsafe: If Python dies while we are locked, release the hardware
            DisengageLock(); 
        }
        Sleep(1000); // Polling for pipe restoration
    }
}

// --- WMI PROCESS SINK (Zero CPU) ---
class ProcessEventSink : public IWbemObjectSink {
    ULONG m_lRef = 1;
public:
    ULONG STDMETHODCALLTYPE AddRef() { return InterlockedIncrement(&m_lRef); }
    ULONG STDMETHODCALLTYPE Release() {
        ULONG lRef = InterlockedDecrement(&m_lRef);
        if (lRef == 0) delete this;
        return lRef;
    }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) {
        if (riid == IID_IUnknown || riid == IID_IWbemObjectSink) {
            *ppv = (IWbemObjectSink*)this; AddRef(); return WBEM_S_NO_ERROR;
        }
        return E_NOINTERFACE;
    }
    
    HRESULT STDMETHODCALLTYPE Indicate(LONG lObjectCount, IWbemClassObject** apObjArray) {
        for (LONG i = 0; i < lObjectCount; i++) {
            VARIANT vName;
            if (SUCCEEDED(apObjArray[i]->Get(L"ProcessName", 0, &vName, NULL, NULL))) {
                if (vName.vt == VT_BSTR) {
                    std::wstring wName(vName.bstrVal);
                    std::string procName(wName.begin(), wName.end());
                    
                    // Shoot process name up the pipe to Python
                    SendToBrain("{\"event\":\"process_create\", \"name\":\"" + procName + "\"}");
                }
                VariantClear(&vName);
            }
        }
        return WBEM_S_NO_ERROR;
    }
    HRESULT STDMETHODCALLTYPE SetStatus(LONG, HRESULT, BSTR, IWbemClassObject*) { return WBEM_S_NO_ERROR; }
};

void WmiProcessMonitorThread() {
    CoInitializeEx(0, COINIT_MULTITHREADED);
    CoInitializeSecurity(NULL, -1, NULL, NULL, RPC_C_AUTHN_LEVEL_DEFAULT, RPC_C_IMP_LEVEL_IMPERSONATE, NULL, EOAC_NONE, NULL);
    
    IWbemLocator* pLoc = NULL;
    CoCreateInstance(CLSID_WbemLocator, 0, CLSCTX_INPROC_SERVER, IID_IWbemLocator, (LPVOID*)&pLoc);
    
    IWbemServices* pSvc = NULL;
    pLoc->ConnectServer(_bstr_t(L"ROOT\\CIMV2"), NULL, NULL, 0, NULL, 0, 0, &pSvc);
    CoSetProxyBlanket(pSvc, RPC_C_AUTHN_WINNT, RPC_C_AUTHZ_NONE, NULL, RPC_C_AUTHN_LEVEL_CALL, RPC_C_IMP_LEVEL_IMPERSONATE, NULL, EOAC_NONE);
    
    ProcessEventSink* pSink = new ProcessEventSink();
    pSvc->ExecNotificationQueryAsync(_bstr_t("WQL"), _bstr_t("SELECT * FROM Win32_ProcessStartTrace"), WBEM_FLAG_SEND_STATUS, NULL, pSink);
    
    std::cout << "[WMI] Process monitor armed (Ring 0 Push).\n";
    
    // Keep thread alive
    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg); DispatchMessage(&msg);
    }
}

// --- USB MONITOR (Hidden Window) ---
LRESULT CALLBACK UsbWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    if (msg == WM_DEVICECHANGE && wParam == DBT_DEVICEARRIVAL) {
        PDEV_BROADCAST_HDR pHdr = (PDEV_BROADCAST_HDR)lParam;
        if (pHdr->dbch_devicetype == DBT_DEVTYP_VOLUME) {
            PDEV_BROADCAST_VOLUME pVol = (PDEV_BROADCAST_VOLUME)pHdr;
            for (int i = 0; i < 26; ++i) {
                if (pVol->dbcv_unitmask & (1 << i)) {
                    std::string drive = std::string(1, 'A' + i) + ":\\\\";
                    SendToBrain("{\"event\":\"usb_insert\", \"drive\":\"" + drive + "\"}");
                }
            }
        }
    }
    return DefWindowProc(hwnd, msg, wParam, lParam);
}

void UsbMonitorThread() {
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = UsbWndProc;
    wc.lpszClassName = "UsbWardenGhost";
    RegisterClassA(&wc);
    HWND hwnd = CreateWindowA("UsbWardenGhost", NULL, 0, 0, 0, 0, 0, HWND_MESSAGE, NULL, NULL, NULL);
    
    std::cout << "[USB] Hardware monitor armed.\n";
    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg); DispatchMessage(&msg);
    }
}

// --- ENTRY POINT ---
int main() {
    // Hide console in production
    // ShowWindow(GetConsoleWindow(), SW_HIDE);
    
    std::cout << "=======================================\n";
    std::cout << "  NEXUS SENTINEL: MUSCLE (v7.0)        \n";
    std::cout << "=======================================\n";

    // Setup Global Hooks
    g_KeyHook = SetWindowsHookEx(WH_KEYBOARD_LL, LowLevelKeyboardProc, NULL, 0);
    g_MouseHook = SetWindowsHookEx(WH_MOUSE_LL, LowLevelMouseProc, NULL, 0);

    std::thread t1(PipeListenerThread);
    std::thread t2(WmiProcessMonitorThread);
    std::thread t3(UsbMonitorThread);

    // Main thread pumps messages for the hooks
    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    return 0;
}
