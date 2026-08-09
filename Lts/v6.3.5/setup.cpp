#include <windows.h>
#include <iostream>
#include <string>
#include <vector>
#include <urlmon.h>

#pragma comment(lib, "urlmon.lib")

using namespace std;

// Checks if the executable is running with elevated privileges
bool IsRunAsAdmin() {
    BOOL fRet = FALSE;
    HANDLE hToken = NULL;
    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &hToken)) {
        TOKEN_ELEVATION Elevation;
        DWORD cbSize = sizeof(TOKEN_ELEVATION);
        if (GetTokenInformation(hToken, TokenElevation, &Elevation, sizeof(Elevation), &cbSize)) {
            fRet = Elevation.TokenIsElevated;
        }
    }
    if (hToken) CloseHandle(hToken);
    return fRet;
}

int main() {
    // 1. Branding
    cout << "===================================================\n";
    cout << "   OBYLON SENTINEL - ENTERPRISE SETUP WIZARD\n";
    cout << "===================================================\n\n";

    // 2. Privilege Check
    if (!IsRunAsAdmin()) {
        cout << "[!] Administrator privileges required.\n";
        cout << "[*] Please right-click this installer and select 'Run as Administrator'.\n";
        system("pause");
        return 1;
    }

    cout << "[+] Administrator Privileges Confirmed.\n";
    
    // 3. License Token Prompt
    string token;
    cout << "Enter School License Token (UUID): ";
    cin >> token;

    // 4. Create Safe Zone
    string targetDir = "C:\\ProgramData\\Obylon";
    CreateDirectoryA(targetDir.c_str(), NULL);

    // 5. Exclude Safe Zone from Windows Defender
    cout << "\n[*] Configuring Windows Defender Exclusions...\n";
    string psCommand = "powershell -Command \"Add-MpPreference -ExclusionPath '" + targetDir + "'\"";
    system(psCommand.c_str());

    // --- CONFIGURE YOUR PAYLOAD URL HERE ---
    string url = "https://github.com/PROxIGRIS/obylon-release/releases/download/release/ObylonSentinel.exe";
    string destPath = targetDir + "\\obylon_agent.exe";

    // 6. Download Payload into Safe Zone
    cout << "[*] Downloading Obylon Payload from Secure Cloud...\n";
    HRESULT hr = URLDownloadToFileA(NULL, url.c_str(), destPath.c_str(), 0, NULL);

    if (SUCCEEDED(hr)) {
        cout << "[*] Download successful. Executing Secure Enrollment...\n";
        
        // 7. Execute the payload to trigger the Supabase RPC and Vault provisioning
        string cmd = "\"" + destPath + "\" --enroll " + token;
        
        // Create a mutable buffer for CreateProcessA to prevent Access Violation crashes
        std::vector<char> cmdBuf(cmd.begin(), cmd.end());
        cmdBuf.push_back('\0'); 
        
        STARTUPINFOA si = { sizeof(si) };
        PROCESS_INFORMATION pi;
        
        if (CreateProcessA(NULL, cmdBuf.data(), NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
            WaitForSingleObject(pi.hProcess, INFINITE);
            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);
            cout << "\n[SUCCESS] Obylon Sentinel has been successfully installed and armed.\n";
            cout << "[SUCCESS] The agent is now running silently in the background.\n";
        } else {
            cout << "[-] FATAL: Failed to execute the payload. Error Code: " << GetLastError() << "\n";
        }
    } else {
        cout << "[-] FATAL: Download failed. Please check network connectivity or URL.\n";
    }

    cout << "\nPress Enter to exit...";
    cin.ignore();
    cin.get();
    return 0;
}
