# PyInstaller Boot Time Issue & Warmup Fix

## The Problem
When compiling a large Python application (like Obylon) into a single executable, PyInstaller's --onefile mode creates a massive hidden boot penalty. On execution, the C bootloader silently extracts the entire Python environment, all DLLs, and all bundled files to a temporary folder in %LocalAppData%\Temp\_MEIxxxxxx before running. For a large application, this extraction can take 10-30 seconds or more. 

Additionally, if the application is compiled as a completely new, unsigned binary, **Windows Defender's "Block at First Sight" (BAFS)** kicks in. Defender halts the execution, uploads the unknown payload to the cloud, and analyzes it. This process can pause execution for up to **5 minutes** while the user sees absolutely nothing (no UI, no errors, just a frozen boot).

## The Solution

1. **Use --onedir (Directory Mode):** 
   Never use --onefile for production builds of this agent. Use PyInstaller's --onedir mode. This skips the temporary extraction phase entirely. The files are already unpacked in the dist\obylon folder. This cuts standard boot time down to just ~1.5 - 2.5 seconds.
   
2. **Pre-Cache Defender Analysis during Installation:**
   To prevent the 5-minute BAFS lockup from happening the first time the *user* reboots their machine, we force Defender to analyze it during the InnoSetup installation phase.
   - **The Agent (Obylon.py):** We added a --warmup flag to the absolute top of the Python execution stack (line 2). When called with this flag, the agent simply writes a warmup.lock file next to its executable and instantly exits.
   - **The Installer (obylon-setup.iss):** During the ssPostInstall step, InnoSetup asynchronously executes obylon.exe --warmup. If Defender blocks it for analysis, the installer detects the delay and displays a custom UI progress bar informing the admin that a one-time security analysis is running. Once warmup.lock appears, the installer knows Defender has cleared and cached the executable.

## How to Pack the Agent Correctly
1. Ensure your obylon.spec is configured for directory mode (coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=True, name='obylon')).
2. Run python -m PyInstaller -y obylon.spec to build the dist\obylon directory.
3. Build the installer using InnoSetup: ISCC.exe obylon-setup.iss.
