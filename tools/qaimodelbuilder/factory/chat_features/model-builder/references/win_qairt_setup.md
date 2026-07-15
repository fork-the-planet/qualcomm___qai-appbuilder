# Task: Setup QAIRT Environment on Windows (WoS ARM64)

## Overview

This reference covers environment setup for **Windows on Snapdragon (WoS) ARM64** devices
(e.g., Snapdragon X Elite) using **QAIRT SDK `<QAIRT SDK version>`** (the installed version is recorded in `${APP_ROOT}\data\config\qairt_env.json`).

> ℹ️ **Environment is pre-configured by `Setup.bat`.**
> All paths are recorded in `${APP_ROOT}\data\config\qairt_env.json`. Scripts read it automatically.
> This file is the troubleshooting and reference guide — no manual setup needed for normal use.

---

## What `Setup.bat` Configures

Runs once. Creates:
- `venv\.venv_x64_310` — x86_64 Python 3.10 (conversion env, key: `python_x64_venv`)
- `venv\.venv_arm64_313` — ARM64 Python 3.13 (inference env, key: `python_arm64_venv`)
- `${APP_ROOT}\data\config\qairt_env.json` — records all paths (SDK root, venv paths, VS paths)
- QAIRT SDK installed to `C:\Qualcomm\AIStack\QAIRT\<version>\` (default, configurable)

`${APP_ROOT}\data\config\qairt_env.json` structure:
```json
{
  "qairt_sdk_root":    "<path to QAIRT SDK>",
  "python_x64_venv":  "<path to x86_64 Python 3.10 venv>",
  "python_arm64_venv": "<path to ARM64 Python 3.13 venv>",
  "vs_vcvarsall":     "<path to vcvarsall.bat>",
  "vc_targets_path":  "<path to VS MSBuild VC v170>"
}
```

> ⚠️ Both Python environments are managed by `uv` inside the QAIModelBuilder project.
> Actual paths are recorded in `${APP_ROOT}\data\config\qairt_env.json` after running `Setup.bat`.
> See SKILL.md § "Python Environment Management" for the full environment management policy.

> ℹ️ **Package versions are managed by `Setup.bat`** → `scripts/setup/setup_qairt_env.py`.
> The install scripts pin all validated versions. Do NOT manually install different versions.

> ⚠️ **`onnx` and `tensorflow` have conflicting `protobuf` requirements** — the install scripts pin compatible versions.
> If you manually install packages outside the install scripts, you may break this compatibility.
>
> **Symptom when protobuf version is wrong**:
> ```
> ImportError: cannot import name 'builder' from 'google.protobuf.internal'
> ```
> **Fix**: Re-run `Setup.bat` to restore pinned versions.

### PyTorch / torchvision — `--index-url` Rules

> ⚠️ **CRITICAL**: The `--index-url` rule differs between the two Python environments.
> Using `--index-url` when not needed will break other package installations.

| Environment | Python | torch/torchvision | All other packages |
|-------------|--------|-------------------|--------------------|
| `python_x64_venv` | x86_64 3.10 | Standard PyPI (no `--index-url`) — `win_amd64` wheels available | Standard PyPI |
| `python_arm64_venv` | ARM64 3.13 | **MUST use** `--index-url https://download.pytorch.org/whl` — no ARM64 Windows wheels on PyPI | Standard PyPI (no `--index-url`) |

**x86_64 python_x64_venv (conversion env):**
```bat
REM No --index-url needed — PyPI has win_amd64 wheels for torch/torchvision
<python_x64_venv>\Scripts\python.exe -m pip install torch torchvision
```

**ARM64 python_arm64_venv (inference env) — torch/torchvision ONLY:**
```bat
REM ARM64 Windows wheels NOT on PyPI — must use PyTorch index
data\bin\uv\uv.exe pip install torch torchvision --index-url https://download.pytorch.org/whl

REM All other packages: standard PyPI, no --index-url
data\bin\uv\uv.exe pip install Pillow numpy scipy matplotlib
```

> 💡 **Note**: If model weight download fails with `SSLCertVerificationError`, use PowerShell to download:
> ```powershell
> Invoke-WebRequest -Uri "https://download.pytorch.org/models/model.pth" -OutFile "model.pth" -UseBasicParsing
> ```
> Then re-run the export script (torchvision will find the cached file automatically).

> 💡 **Note**: PyTorch 2.x exports ONNX with opset 18 (not 13). This is fine for QAIRT 2.45.
> The ONNX file may use external data format (`.onnx` + `.onnx.data`) for large models — pass the `.onnx` path to the converter, it will find the `.data` file automatically.

---

## QAIRT 2.45 WoS ARM64 Tool Path Rules

> ⚠️ **CRITICAL**: These paths differ from older QAIRT versions and from Linux.

| Step | Tool | Arch Directory | Notes |
|------|------|---------------|-------|
| ONNX → C++/bin | `qnn-onnx-converter` | `bin/x86_64-windows-msvc/` | Python script, runs under x86 emulation |
| C++/bin → DLL | `qnn-model-lib-generator` | `bin/aarch64-windows-msvc/` | **NOT x86_64** — compiles native ARM64 DLL |
| DLL → Context Binary | `qnn-context-binary-generator.exe` | `bin/aarch64-windows-msvc/` | Native ARM64 executable |
| Inference | `qai_appbuilder` | ARM64 Python 3.13 (`python_arm64_venv`) | `model.Inference([inp])` |

### Why Two Different Arch Dirs?

- `qnn-onnx-converter` is a **Python script** that runs under x86 emulation on WoS.
  It lives in `x86_64-windows-msvc/` and is invoked with `python <path>`.
- `qnn-model-lib-generator` is also a Python script but **invokes the ARM64 MSVC compiler**
  to build a native ARM64 DLL. It lives in `aarch64-windows-msvc/`.
- `qnn-context-binary-generator.exe` is a **native ARM64 executable** in `aarch64-windows-msvc/`.

---

## VS ARM64 Environment Requirement

`qnn-model-lib-generator` and `qnn-context-binary-generator.exe` require VS ARM64 build env.

**Key rules:**
- `vcvarsall.bat arm64` must be called in the **same `.bat` file process** — it does NOT propagate across `cmd /c "..."` subprocess calls
- `VCTargetsPath` must point to **VS 2022 Community** (NOT BuildTools)
  - ✅ `C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Microsoft\VC\v170\`
  - ❌ `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\...` ← will FAIL
- `run_pipeline.bat` handles this automatically from `${APP_ROOT}\data\config\qairt_env.json` — use it

**Template for custom `.bat` files** (read all values from `${APP_ROOT}\data\config\qairt_env.json`):
```bat
@echo off
REM Read from ${APP_ROOT}\data\config\qairt_env.json -- do NOT hardcode paths
for /f "delims=" %%V in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).vs_vcvarsall"') do set _VCVARSALL=%%V
for /f "delims=" %%T in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).vc_targets_path"') do set VCTargetsPath=%%T
for /f "delims=" %%S in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).qairt_sdk_root"') do set QAIRT_SDK_ROOT=%%S
for /f "delims=" %%P in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).python_x64_venv"') do set PYTHON_X64=%%P\Scripts\python.exe

call "%_VCVARSALL%" arm64
set PYTHONPATH=%QAIRT_SDK_ROOT%\lib\python;%PYTHONPATH%
set PATH=%QAIRT_SDK_ROOT%\lib\aarch64-windows-msvc;%QAIRT_SDK_ROOT%\bin\aarch64-windows-msvc;%QAIRT_SDK_ROOT%\bin\x86_64-windows-msvc;%PATH%
```

---

## HTP Runtime Files (Context Binary Generation)

`run_pipeline.bat` copies these automatically. For manual runs, copy to working dir first:
```bat
copy %QAIRT_SDK_ROOT%\lib\aarch64-windows-msvc\QnnHtp.dll          <working_dir>\
copy %QAIRT_SDK_ROOT%\lib\hexagon-v73\unsigned\libqnnhtpv73.cat     <working_dir>\
copy %QAIRT_SDK_ROOT%\lib\hexagon-v73\unsigned\libQnnHtpV73Skel.so  <working_dir>\
```

Missing these causes: `loadRemoteSymbols failed` / `DspTransport.openSession qnn_open failed`.

---

## Verification Checklist

```powershell
# Read qairt_env.json to get paths
$cfg = Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json

# 1. Check converter exists (x86_64)
Test-Path "$($cfg.qairt_sdk_root)\bin\x86_64-windows-msvc\qnn-onnx-converter"

# 2. Check lib generator exists (aarch64 — QAIRT 2.45 WoS)
Test-Path "$($cfg.qairt_sdk_root)\bin\aarch64-windows-msvc\qnn-model-lib-generator"

# 3. Check context binary generator exists (aarch64)
Test-Path "$($cfg.qairt_sdk_root)\bin\aarch64-windows-msvc\qnn-context-binary-generator.exe"

# 4. Check VCTargetsPath points to Community (not BuildTools)
echo $cfg.vc_targets_path
# Should contain: Microsoft Visual Studio\2022\Community

# 5. Check MSBuild is from Community
where.exe MSBuild.exe
# Should show: C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\...
# NOT: C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\...

# 6. Check Python envs
& "$($cfg.python_x64_venv)\Scripts\python.exe" -c "import onnx; print('conversion env OK')"
& "$($cfg.python_arm64_venv)\Scripts\python.exe" -c "import qai_appbuilder; print('inference env OK')"
```

> ℹ️ The import check above is the correct way to verify the inference env.

---

## Common Issues

### Issue: `qnn-model-lib-generator` fails with CMake error

**Symptom**: `CMake Error: CMAKE_C_COMPILER not found`

**Cause**: `vcvarsall.bat arm64` was not called, or `VCTargetsPath` points to BuildTools.

**Fix**: Use `run_pipeline.bat` (handles automatically), or in custom `.bat` files read `vs_vcvarsall` and `vc_targets_path` from `${APP_ROOT}\data\config\qairt_env.json` (see template above).

### Issue: `qnn-model-lib-generator` fails with `VCTargetsPath.vcxproj` / `BaseOutputPath not set`

**Symptom**:
```
MSBUILD : error MSB1009: Project file does not exist.
C:\...\Microsoft.Common.CurrentVersion.targets: error : The BaseOutputPath/OutputPath property is not set
Configuration='Debug'  Platform='ARM64'
```

**Cause**: `VCTargetsPath` points to **VS 2022 BuildTools** instead of **VS 2022 Community**.
BuildTools MSBuild cannot compile ARM64 DLLs for QNN model library generation.

**Fix**: `vc_targets_path` in `${APP_ROOT}\data\config\qairt_env.json` already points to Community. Ensure it is read correctly:
```bat
for /f "delims=" %%T in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).vc_targets_path"') do set VCTargetsPath=%%T
```

**Verification**: Check which MSBuild is being used:
```bat
where MSBuild.exe
REM Should show: C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\...
REM NOT: C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\...
```

### Issue: `Unknown Key` warnings during context binary generation

**Symptom**: Warnings like `[WARNING] Unknown Key: ...` in generator output.

**Cause**: Non-fatal warnings from HTP backend config parsing.

**Fix**: These are **non-fatal**. Check if the `.bin` file was created — if yes, proceed normally.

---

## run_pipeline.bat

Known issues (QAIRT_SDK_ROOT not read from `qairt_env.json`, DLL search picking `QnnHtp.dll`, context binary exit code false failure) are all fixed in the current version. Use `run_pipeline.bat` directly — no manual workarounds needed.

### Issue: `qai_appbuilder` import error

**Symptom**: `ModuleNotFoundError: No module named 'qai_appbuilder'`

**Fix**: Use ARM64 Python from `python_arm64_venv` in `${APP_ROOT}\data\config\qairt_env.json`:
```bat
for /f "delims=" %%P in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).python_arm64_venv"') do set PYTHON_ARM64=%%P\Scripts\python.exe
%PYTHON_ARM64% -c "import qai_appbuilder; print('OK')"
```
If this fails → run `Setup.bat` from the QAIModelBuilder project directory.

### Issue: Architecture detection unreliable

**Do NOT use** `$env:PROCESSOR_ARCHITECTURE` or Python's `platform.machine()` on WoS —
both can be affected by x86 emulation.

**Use instead**:
```powershell
# Reliable: WMI Win32_Processor.Architecture
(Get-WmiObject Win32_Processor).Architecture
# 0 = x86, 5 = ARM, 9 = x64 (AMD64), 12 = ARM64

# Or check DLL architecture:
dumpbin /headers C:\path\to\model.dll | find "machine"
```

---

## Platform SoC Identification (HTP Version Detection)

Run this command to identify the SoC and determine the correct `--htp_version`:

```powershell
Get-ChildItem "HKLM:\SYSTEM\CurrentControlSet\Services" |
  Where-Object { $_.PSChildName -like "qcadsp*" } |
  Get-ItemProperty | Select-Object PSChildName, ImagePath
```

Read the 4-digit code from the INF filename in `ImagePath`:

| INF code | Device | `--htp_version` | `--soc_model` |
|:--------:|--------|:---------------:|:-------------:|
| `8380` | Snapdragon X Elite (X1E-80-100 etc.) | `v73` | `60` |
| `8480` | Snapdragon X2 Elite (XG102006 etc.) | `v73` | `88` |

> ⚠️ **Never use `Get-PnpDeviceProperty`** for this purpose — it wakes the DSP subsystem
> and can block for 300-400 seconds on Snapdragon platforms.
> ⚠️ **Never use `Get-WmiObject Win32_SystemDriver`** — WMI provider throttling causes this query
> to hang indefinitely on busy systems (verified: hangs even with 120s timeout).

---

## QAIRT 2.45 Specific Notes

### Context Binary Generation (Windows-specific)

- **`Wrong number of Parameters 5` / `Conv2d failed 3110`**: Root cause is **missing VS ARM64 environment**, NOT an operator patching issue. Fix: run `qnn-context-binary-generator.exe` inside a `.bat` file that calls `vcvarsall.bat arm64` at the top. Only resort to `.cpp` patching if the error persists after correct env setup.
- **HTP runtime files required in working dir**: Copy these before running `qnn-context-binary-generator.exe`:
  - `QnnHtp.dll` (from `%QAIRT_SDK_ROOT%\lib\aarch64-windows-msvc\`)
  - `libqnnhtpv73.cat` (from `%QAIRT_SDK_ROOT%\lib\hexagon-v73\unsigned\`)
  - `libQnnHtpV73Skel.so` (from `%QAIRT_SDK_ROOT%\lib\hexagon-v73\unsigned\`)
  - Missing these causes: `loadRemoteSymbols failed` / `DspTransport.openSession qnn_open failed`
- **VS ARM64 env scope**: `vcvarsall.bat arm64` only takes effect in the same process — always use a `.bat` file, never `cmd /c "..."` from a separate terminal
- **`--no_simplification`**: Use with `qnn-onnx-converter` on WoS to avoid simplification issues

### Inference API (qai_appbuilder)

For full API reference → see `references/inference.md`. Quick summary:
- `QNNConfig.Config(Runtime.HTP, LogLevel.WARN, ProfilingLevel.BASIC)` — call before `QNNContext`; qai_appbuilder 2.47 dropped the old leading lib-dir arg (internal `libs/` used automatically)
- `QNNContext("model_name", "model.bin")` — supports `.bin` / `.dlc` / `.dll`; `.bin` is preferred
- Subclass `QNNContext`, override `Inference(self, input_data)`
- Input format: check `model.getInputShapes()` — NCHW if `--preserve_io` used (default), NHWC otherwise. See `references/inference.md` for details.
- Wrap with `PerfProfile.SetPerfProfileGlobal(PerfProfile.BURST)` / `RelPerfProfileGlobal()`
- Always `del model` after use
