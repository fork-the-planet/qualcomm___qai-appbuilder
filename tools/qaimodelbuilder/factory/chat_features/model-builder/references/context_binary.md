# Context Binary Generation Reference

Generate hardware-specific HTP context binaries for on-device deployment.
Use absolute paths for all model file arguments.

> 🚦 **Two input types are supported**: `.dlc` (**default**, from Flow A / `run_pipeline.py`) and `.dll` (**legacy**, from Flow C / `run_pipeline_legacy.py`). Both are consumed by `qai_dev_gen_contextbin.py` — pass `--model <file>.dlc` or `--model <file>.dll` and the script picks the right branch (for DLC it uses `QnnModelDlc.dll + --dlc_path + --soc_model`, for DLL it uses `--model <file>.dll + --config_file`).
>
> The **DLC path is the default** since it needs neither VS ARM64 env nor DLL compilation. Reserve the DLL path for cases where the user explicitly asks for the legacy pipeline.

> ℹ️ `qnn-context-binary-generator.exe` returns non-zero exit code even on success. `qai_dev_gen_contextbin.py` and `run_pipeline.bat` both handle this by checking file existence — no manual workaround needed.

## Troubleshooting Flow

If context binary generation fails, follow this structured flow:

```
Step 1: Is this Windows ARM or Linux ARM?
  ├─ Windows ARM → Context binary is MANDATORY → Continue to Step 2
  └─ Linux ARM   → Optional (.so works directly) → Can skip

Step 2: What does the error say?
  Look for: operator name, error code (e.g., 0xc26), "unsupported", "validation failed"
  └─→ Match the error in the Error → Action table in operator_patching.md

Step 3: For each failing operator
  3a. Identify the operator name and input types from the error log
  3b. Check input types: TopK output = INT64, Conv output = FLOAT, Constant dtype in Netron
  3c. Follow the Error → Action table in operator_patching.md to patch
  3d. Validate: onnx.checker.check_model(patched.onnx)

Step 4: Re-convert the patched model
   4a. python qai_convert_fp.py --onnx patched.onnx ...
  4b. Re-generate context binary

Step 5: If all patterns exhausted
  → Escalate as Blocking Condition B7
  → Consider: SNPE/DLC flow or CPU/GPU backend alternative
```

---

## ⚠️ CRITICAL: Context Binary Requirements

**Context binary requirements vary by platform AND by deployment scenario:**

| Target Platform | Context Binary | Notes |
|-----------------|----------------|-------|
| **ARM Windows (same-machine: build host == inference target)** | **Recommended** | best p50 latency; HTP-optimized cache |
| **ARM Windows (cross-target: ship to other devices, esp. different HTP versions)** | **Use `.dlc` instead** | `.bin` is **locked to one HTP version + host arch** — not portable; `.dlc` compiles to context on-device at first load |
| **ARM Linux** | **Optional** | `.so` works directly; `.so.bin` improves load time |
| x86 Linux       | N/A (CPU-only) | Use x86 wrapper |

> **`.bin` vs `.dlc` decision** (full version): see
> [`inference.md` § "Format selection"](inference.md#format-selection-bin-vs-dlc--when-which).
> Quick rule: same-machine → `.bin`; cross-target deployment → `.dlc`;
> user explicitly asks → honor user's choice.

> **Note on naming**: The context binary output file is named `<binary_file>.bin` (e.g., `my_model.bin`).
> The older `{model}.dll.bin` naming convention refers to the qai_runner.py wrapper's file search order — when using qai_appbuilder directly, just use the `.bin` file produced by `qnn-context-binary-generator`.

> ⚠️ **Batch generation — use separate `--output_dir` per model to avoid file conflicts**:
> When generating context binaries for multiple models in one script, if all models share the same
> `--output_dir`, `qnn-context-binary-generator` may create a `bins/` subdirectory for the first model
> and leave 0-byte placeholder files in the root directory for subsequent models.
>
> **Symptom**: `.bin` files exist but are 0 bytes (or 8 bytes) — the real binary is in a `bins/` subdirectory.
>
> **Fix**: Use a dedicated subdirectory per model:
> ```bat
> REM ✅ CORRECT — separate output_dir per model
> qnn-context-binary-generator.exe --output_dir "%WORK_DIR%\fp16"  --binary_file model_fp16
> qnn-context-binary-generator.exe --output_dir "%WORK_DIR%\w8a16" --binary_file model_w8a16
> qnn-context-binary-generator.exe --output_dir "%WORK_DIR%\w8a8"  --binary_file model_w8a8
>
> REM ❌ WRONG — shared output_dir causes file conflicts
> qnn-context-binary-generator.exe --output_dir "%WORK_DIR%" --binary_file model_fp16
> qnn-context-binary-generator.exe --output_dir "%WORK_DIR%" --binary_file model_w8a16
> ```
>
> **Verification**: Always check `.bin` file size after generation — a valid context binary for
> Real-ESRGAN x4plus is ~30-60 MB. A 0-byte or 8-byte file indicates the real binary is elsewhere.

**If context binary generation fails:**
- **Windows**: → First verify VS ARM64 env (`vcvarsall.bat arm64`) and HTP runtime files are in working dir; if still fails → **Blocking Condition B8** — fallback to `.dll` is possible but not recommended
- **Linux**: → Can proceed with `.so` library directly
- **Alternative**: Consider SNPE flow (`.dlc`) if QNN HTP is incompatible

Linux cross-host rule:
- When host and Linux target architectures differ, context-binary generation may not be possible directly on the host.
- If generation fails, skip context-binary step, log failure reason, and continue inference with `.so`.
- Only escalate if inference/validation fails afterward.

---

## ⚠️ CRITICAL: `graph_names` Must Match DLL Graph Name

**This is the #1 cause of `Graph Compose failure` on WoS ARM64.**

The `graph_names` field in `htp_backend_config_{version}.json` (e.g. `htp_backend_config_v73.json` or `htp_backend_config_v81.json`, referenced by `backend_extensions.json`) **must exactly match** the graph name embedded in the `.dll`.

**How the graph name is determined:**
- The graph name = **stem of `--output_path`** passed to `qnn-onnx-converter`
- Example: `--output_path output/qnn_model.cpp` → graph name = `"qnn_model"`
- Example: `--output_path output/my_model.cpp` → graph name = `"my_model"`

**Recommendation: Use the model name as the output stem** for clarity:
```bat
qnn-onnx-converter --output_path output\<model>.cpp ...
```
Then set `graph_names` to `["<model>"]` in the config (matching the stem).

**Error when graph_names is wrong:**
```
[ ERROR ] getQnnGraphConfigFromInfo() unable to find graphName:qnn_model in provided graphsConfigInfo object.
[ ERROR ] getQnnGraphConfigFromInfo(...) expected MODEL_NO_ERROR, got MODEL_INVALID_ARGUMENT_ERROR
Graph Compose failure
```

**Fix:** Update `graph_names` in `htp_backend_config_v73.json` to match the actual graph name.

---

## ⚠️ CRITICAL: HTP Runtime Files Required in Working Directory (WoS ARM64)

Before running `qnn-context-binary-generator.exe` on WoS ARM64, copy the required files to the **working directory**. Files differ by HTP version:

### v73 (default)
```bat
copy %QNN_SDK_ROOT%lib\aarch64-windows-msvc\QnnHtp.dll          <working_dir>\
copy %QNN_SDK_ROOT%lib\hexagon-v73\unsigned\libqnnhtpv73.cat     <working_dir>\
copy %QNN_SDK_ROOT%lib\hexagon-v73\unsigned\libQnnHtpV73Skel.so  <working_dir>\
```

### v81
```bat
copy %QNN_SDK_ROOT%lib\aarch64-windows-msvc\QnnHtp.dll           <working_dir>\
copy %QNN_SDK_ROOT%lib\aarch64-windows-msvc\QnnHtpV81Stub.dll    <working_dir>\
copy %QNN_SDK_ROOT%lib\hexagon-v81\unsigned\libqnnhtpv81.cat      <working_dir>\
copy %QNN_SDK_ROOT%lib\hexagon-v81\unsigned\libQnnHtpV81Skel.so   <working_dir>\
```

> ⚠️ **CRITICAL — v81 backend loading rule:**
> For v81, the `--backend` argument to `qnn-context-binary-generator` MUST be `QnnHtp.dll`,
> NOT `QnnHtpV81Stub.dll`. The Stub DLL is a forwarding layer that cannot be loaded standalone;
> it must be referenced only via `backend_extensions.json` → `shared_library_path`.
> Passing `QnnHtpV81Stub.dll` as `--backend` causes:
> ```
> Unable to load backend. dlerror(): load library failed
> ```

> ⚠️ **CRITICAL — `arm64x` ≠ `aarch64`:**
> `lib/arm64x-windows-msvc/QnnHtpV81Stub.dll` is an ARM64EC (compatibility layer) DLL.
> `qnn-context-binary-generator.exe` is a pure ARM64 binary and CANNOT load `arm64x` DLLs.
> Always copy `QnnHtpV81Stub.dll` from `lib/aarch64-windows-msvc/`, not `arm64x-windows-msvc/`.

**Why these files matter:**
- `QnnHtp.dll` — main HTP backend library, used as `--backend` argument
- `QnnHtpV81Stub.dll` (v81 only) — v81 stub, loaded by `QnnHtp.dll` via `backend_extensions.json`
- `libqnnhtpv*.cat` — HTP catalog, required for DSP transport initialization
- `libQnnHtpV*Skel.so` — HTP skeleton, required for DSP session

> ⚠️ **CRITICAL: The generator MUST be run with `cwd=<working_dir>`** (the directory containing these files).
> `qnn-context-binary-generator.exe` resolves `libqnnhtpv73.cat` and `libQnnHtpV73Skel.so` relative to
> its **process working directory**, NOT via `PATH`. Copying the files to the output dir is necessary
> but not sufficient — the generator must also be launched with `cwd` set to that same directory.
>
> `qai_dev_gen_contextbin.py` handles both steps automatically: it copies the files to `gen_output_dir`
> and passes `cwd=gen_output_dir` to `subprocess.run()`.

**Symptoms when missing:**
```
loadRemoteSymbols failed with err 4000
DspTransport.openSession qnn_open failed, 0x80000406
```

> ⚠️ These files are **not** automatically found via `PATH`. They must be physically present in the working directory.

---

## ⚠️ CRITICAL: VS ARM64 Environment Required for Context Binary Generation

`qnn-context-binary-generator.exe` is a native ARM64 executable that requires the VS ARM64 build environment.

**Rule: Always run inside a `.bat` file that calls `vcvarsall.bat arm64` at the top.**

```bat
@echo off
REM Read paths from ${APP_ROOT}\data\config\qairt_env.json (generated by Setup.bat)
REM Do NOT hardcode SDK or VS paths -- they vary per machine

REM Get vs_vcvarsall and vc_targets_path from ${APP_ROOT}\data\config\qairt_env.json:
for /f "delims=" %%V in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).vs_vcvarsall"') do set _VCVARSALL=%%V
for /f "delims=" %%T in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).vc_targets_path"') do set VCTargetsPath=%%T
for /f "delims=" %%S in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).qairt_sdk_root"') do set QNN_SDK_ROOT=%%S
for /f "delims=" %%P in ('powershell -NoProfile -Command "(Get-Content ${APP_ROOT}\data\config\qairt_env.json | ConvertFrom-Json).python_x64_venv"') do set PYTHON_X64=%%P\Scripts\python.exe

REM Initialize VS ARM64 environment (REQUIRED)
call "%_VCVARSALL%" arm64

set PATH=%QNN_SDK_ROOT%\lib\aarch64-windows-msvc;%QNN_SDK_ROOT%\bin\aarch64-windows-msvc;%PATH%

REM Recommended: use qai_dev_gen_contextbin.py (handles HTP file copy + auto-config)
"%PYTHON_X64%" scripts\qai_dev_gen_contextbin.py ^
    --model C:\absolute\path\to\model.dll ^
    --output_dir output ^
    --binary_file my_model ^
    --auto-config
```

**Why `cmd /c` does NOT work:**
```bat
REM ❌ WRONG — vcvarsall.bat env is NOT inherited by cmd /c subprocess
cmd /c "set QNN_SDK_ROOT=... && qnn-context-binary-generator.exe ..."

REM ✅ CORRECT — run as a .bat file where vcvarsall.bat was already called
my_gen_contextbin.bat
```

**Symptom when VS ARM64 env is missing:**
```
Wrong number of Parameters 5
Op specific validation failed
validateNativeOps ... Conv2d failed 3110
```
This error looks like an operator patching issue but is actually caused by missing ARM64 environment.

---

## QNN Context Binary Generation

Use `scripts/qai_dev_gen_contextbin.py` to generate a QNN context binary from a compiled model library (`.so` on Linux / `.dll` on Windows).

### Mandatory preflight — architecture check (no exceptions)

Before running, verify that the native host architecture matches the model library architecture.

> **Note**: Context binary compilation failures (e.g., `Failed to compile layer 'Einsum_123'`) often trace back to unsupported operators in the ONNX graph. See [In-Memory Operator Patching](operator_patching.md) §Stage 4 for resolution.

**Linux:**
```bash
uname -m
file /absolute/path/to/libmodel.so
```

**Windows** (do not use Python `platform.machine()` or `$env:PROCESSOR_ARCHITECTURE` — both can be affected by emulation):
```powershell
# Reliable: WMI Win32_Processor.Architecture
(Get-WmiObject Win32_Processor).Architecture
# 0 = x86, 5 = ARM, 9 = x64 (AMD64), 12 = ARM64

# Or use dumpbin to check DLL architecture:
dumpbin /headers C:\path\to\model.dll | find "machine"
```

| OS | Host arch | Model lib | Action |
|----|-----------|-----------|--------|
| Linux | `x86_64` | `aarch64` (`.so`) | ❌ Blocked on host — run on ARM target device |
| Linux | `aarch64` | `aarch64` (`.so`) | ✅ Allowed |
| Windows | `ARM64` | `ARM64` (`.dll`) | ✅ Allowed |
| Windows | `AMD64` | `ARM64` (`.dll`) | ❌ Blocked on host — run on ARM target device |

If architectures do not match, **do not run** `qnn-context-binary-generator` locally. Stop and instruct the user to run on the target device.
If target-side generation still fails for Linux, context binary remains optional; proceed with `.so`.

---

## Usage

### Linux:
```bash
python ${APP_ROOT}/factory/chat_features/model-builder/scripts/qai_dev_gen_contextbin.py \
  --model /absolute/path/to/libmodel.so \
  --output model_context.bin
```

### Windows (basic):
```powershell
python ${APP_ROOT}/factory/chat_features/model-builder/scripts/qai_dev_gen_contextbin.py \
  --model C:\absolute\path\to\model.dll \
  --output model_context.dll.bin
```

### Windows WoS ARM64 with backend config (QAIRT 2.45 V73):
```bat
python ${APP_ROOT}\factory\chat_features\model-builder\scripts\qai_dev_gen_contextbin.py ^
  --model C:\absolute\path\to\model.dll ^
  --output_dir output ^
  --binary_file my_model ^
  --auto-config
```

This mirrors the direct CLI call:
```bat
%QAIRT_SDK_ROOT%\bin\aarch64-windows-msvc\qnn-context-binary-generator.exe ^
  --backend QnnHtp.dll ^
  --model C:\absolute\path\to\model.dll ^
  --output_dir output ^
  --binary_file my_model ^
  --config_file backend_extensions.json
```

---

## Backend Config Files (QAIRT 2.45 WoS)

> ⚠️ **Each model project MUST have its own `backend_extensions.json` and `htp_backend_config_*.json`.**
> Never reuse config files from another project — the `config_file_path` inside `backend_extensions.json`
> is an absolute path that must point to the correct file for the current project.
> Place both files under `${WORKSPACE}\<model_name>\output\`.

### v73 config

**`backend_extensions.json`**
```json
{
  "backend_extensions": {
    "shared_library_path": "<QAIRT_SDK_ROOT>\\lib\\aarch64-windows-msvc\\QnnHtpNetRunExtensions.dll",
    "config_file_path": "${WORKSPACE}\\<model_name>\\output\\htp_backend_config_v73.json"
  }
}
```

**`htp_backend_config_v73.json`**
```json
{
  "graphs": [{"graph_names": ["<model_stem>"], "vtcm_mb": 8, "O": 3}],
  "devices": [{"cores": [{"rpc_control_latency": 100, "perf_profile": "burst"}]}]
}
```

> ℹ️ The `"devices"` section may also include `"htp_arch"` to specify the target HTP architecture
> (e.g. `"htp_arch": "v73"` or `"htp_arch": "v68"`). This is optional on WoS ARM64 where the
> HTP version is auto-detected:
> ```json
> {
>   "graphs": [{"graph_names": ["<model_stem>"], "vtcm_mb": 2}],
>   "devices": [{"htp_arch": "v73"}]
> }
> ```

### v81 config

**`backend_extensions.json`** (v81)
```json
{
  "backend_extensions": {
    "shared_library_path": "<QAIRT_SDK_ROOT>\\lib\\aarch64-windows-msvc\\QnnHtpNetRunExtensions.dll",
    "config_file_path": "${WORKSPACE}\\<model_name>\\output\\htp_backend_config_v81.json"
  }
}
```

> ⚠️ **v81 `shared_library_path` must be `QnnHtpNetRunExtensions.dll`**, NOT `QnnHtpV81Stub.dll`.
> The extensions loader (`QnnHtpNetRunExtensions.dll`) is the correct value for both v73 and v81.
> Using `QnnHtpV81Stub.dll` here causes `Unable to initialize backend extensions`.

**`htp_backend_config_v81.json`**
```json
{
  "graphs": [{"graph_names": ["<model_stem>"], "vtcm_mb": 8, "O": 3}],
  "devices": [{"cores": [{"rpc_control_latency": 100, "perf_profile": "burst"}]}]
}
```

Both v73 and v81 use the same `htp_backend_config` structure. The HTP version is selected at runtime
based on which `.cat`/`.so` files are present in the CWD and the Stub DLL referenced by the driver.

> **Note**: `"Unknown Key"` warnings during generation are **non-fatal**. Check if the `.bin` file was created — if yes, proceed normally.
>
> ⚠️ **`qnn-context-binary-generator.exe` may return a non-zero exit code even on success** (observed on QAIRT 2.45 WoS). Do **not** rely solely on the exit code to determine success. Always verify that the `.bin` output file exists and is non-empty (a valid context binary is typically several MB). `run_pipeline.bat` already handles this correctly.

---

## Options

| Option | Description |
|--------|-------------|
| `--model` | Absolute path to compiled model library (`.so` on Linux, `.dll` on Windows) |
| `--output` | Output path for the context binary (`.bin`) |
| `--output_dir` | Output directory (used with `--binary_file`, mirrors tool's `--output_dir`) |
| `--binary_file` | Output binary name without `.bin` extension |
| `--config_file` | Path to `backend_extensions.json` for HTP configuration (QAIRT 2.45 WoS V73) |
| `--profiling` | Enable HTP optrace profiling (`--profiling_level detailed --profiling_option optrace`) |

---

## x86 Host Support (QNN)

When generating a QNN context binary on an x86 host, use `qai_dev_gen_contextbin_x86.py`.
This script resolves the host SDK `bin/lib` arch directory automatically and invokes `qnn-context-binary-generator`.

**Linux x86_64:**
```bash
python qai_dev_gen_contextbin_x86.py \
  --model /absolute/path/to/libmodel.so \
  --output /absolute/path/to/model_context.bin \
  --backend htp
```

**Windows x86_64:**
```powershell
python qai_dev_gen_contextbin_x86.py `
  --model C:\absolute\path\to\model.dll `
  --output C:\absolute\path\to\model_context.bin `
  --backend htp
```

**DLC input (Linux/Windows):**
```bash
python qai_dev_gen_contextbin_x86.py \
  --dlc /absolute/path/to/model.dlc \
  --output /absolute/path/to/model.dlc.bin \
  --backend htp
```

Notes:
- `QAIRT_SDK_ROOT` must be set before running.
- `--backend` supports `htp` and `cpu` (default: `htp`).
- Input is mutually exclusive: use exactly one of `--model` or `--dlc`.
- If `--output` is omitted, output is created under `./output/<binary_name>.bin`.
- Use `--profiling` to enable `optrace` profiling flags.

---

## SNPE/DLC Context Binary Generation

> ✅ **Preferred: just pass the `.dlc` to the wrapper** — `qai_dev_gen_contextbin.py`
> auto-detects `.dlc` input and handles everything below (extra DLLs, `--model
> QnnModelDlc.dll --dlc_path`, `--soc_model` from htp_version) automatically:
> ```bat
> <python_x64_venv>\Scripts\python.exe ${APP_ROOT}\factory\chat_features\model-builder\scripts\qai_dev_gen_contextbin.py ^
>   --model ${WORKSPACE}\<model>\output_dlc\<model>.dlc ^
>   --output_dir ${WORKSPACE}\<model>\output ^
>   --binary_file <model>_w8a8 ^
>   --htp_version v73 --auto-config
> ```
> The manual command below is the underlying invocation (for reference / debugging).
> **Never** pass a `.dlc` to the generator's `--model` directly — it tries to
> `LoadLibrary` the `.dlc` as a DLL and fails with `load library failed` /
> Windows "bad image 0xc000012f". The wrapper maps htp_version→soc_model
> (v73→60, v81→88) and **skips `--config_file`** for DLC (a config_file would
> require a predictable `graph_names`, which DLC inputs do not have → "Valid
> 'graph_names' must be specified" failure); it uses `--soc_model` instead.

Generate an HTP context binary from a `.dlc` file using `qnn-context-binary-generator` directly.
Use **absolute paths** for `--dlc_path` and `--binary_file`.

### Windows on Snapdragon (WoS ARM64) — Full Working Command

> ⚠️ **DLC mode requires additional DLL files** beyond the standard `.bin`-from-`.dll` flow.
> The following files must ALL be present in the working directory (CWD).
> **File list differs by HTP version:**

**v73 (default — Snapdragon X Elite SC8380XP):**

| File | Source in SDK |
|------|---------------|
| `QnnHtp.dll` | `lib\aarch64-windows-msvc\` |
| `QnnModelDlc.dll` | `lib\aarch64-windows-msvc\` |
| `QnnHtpV73Stub.dll` | `lib\aarch64-windows-msvc\` |
| `QnnHtpPrepare.dll` | `lib\aarch64-windows-msvc\` |
| `QnnHtpNetRunExtensions.dll` | `lib\aarch64-windows-msvc\` |
| `libqnnhtpv73.cat` | `lib\hexagon-v73\unsigned\` |
| `libQnnHtpV73Skel.so` | `lib\hexagon-v73\unsigned\` |

**v81 (Snapdragon X2 Elite SC8480XP):**

| File | Source in SDK |
|------|---------------|
| `QnnHtp.dll` | `lib\aarch64-windows-msvc\` |
| `QnnModelDlc.dll` | `lib\aarch64-windows-msvc\` |
| `QnnHtpV81Stub.dll` | `lib\aarch64-windows-msvc\` (**NOT** `arm64x-windows-msvc`) |
| `QnnHtpPrepare.dll` | `lib\aarch64-windows-msvc\` |
| `QnnHtpNetRunExtensions.dll` | `lib\aarch64-windows-msvc\` |
| `libqnnhtpv81.cat` | `lib\hexagon-v81\unsigned\` |
| `libQnnHtpV81Skel.so` | `lib\hexagon-v81\unsigned\` |

> ⚠️ **Error diagnosis for DLC→bin on WoS:**
> - `Wrong number of Parameters 5` / `Conv2d failed 3110` → `QnnHtpV73Stub.dll` or `QnnHtpPrepare.dll` missing from CWD
> - `PrepareLibLoader Failed loading QnnHtpPrepare.dll` → `QnnHtpPrepare.dll` not in CWD
> - `loadRemoteSymbols failed with err 4000` → non-fatal warning, safe to ignore

```bat
REM %QAIRT_SDK_ROOT% is set by Setup.bat (or read from data\config\qairt_env.json
REM "qairt_sdk_root"). Do NOT hardcode a versioned path here — it goes stale on
REM SDK upgrade.
set QAIRT=%QAIRT_SDK_ROOT%
set OUT=${WORKSPACE}\<model>\output_dlc

REM Copy ALL required runtime files to output directory
copy %QAIRT%\lib\aarch64-windows-msvc\QnnHtp.dll                 %OUT%\
copy %QAIRT%\lib\aarch64-windows-msvc\QnnModelDlc.dll            %OUT%\
copy %QAIRT%\lib\aarch64-windows-msvc\QnnHtpV73Stub.dll          %OUT%\
copy %QAIRT%\lib\aarch64-windows-msvc\QnnHtpPrepare.dll          %OUT%\
copy %QAIRT%\lib\aarch64-windows-msvc\QnnHtpNetRunExtensions.dll %OUT%\
copy %QAIRT%\lib\hexagon-v73\unsigned\libqnnhtpv73.cat            %OUT%\
copy %QAIRT%\lib\hexagon-v73\unsigned\libQnnHtpV73Skel.so         %OUT%\

cd /d %OUT%

%QAIRT%\bin\aarch64-windows-msvc\qnn-context-binary-generator.exe ^
  --model QnnModelDlc.dll ^
  --backend QnnHtp.dll ^
  --dlc_path %OUT%\<model>.dlc ^
  --binary_file <model>_fp16 ^
  --output_dir %OUT% ^
  --config_file %OUT%\backend_extensions.json ^
  --soc_model 60
```

> ℹ️ **`--config_file` is OPTIONAL for DLC->bin conversion (verified on QAIRT 2.45 WoS).**
> The minimal working command only needs `--soc_model` -- no `backend_extensions.json` or
> `htp_backend_config_v73.json` required. The generated `.bin` is identical in size and content.
>
> Use `--config_file` only when you need HTP performance tuning (vtcm_mb, perf_profile, etc.).
> When used, `htp_backend_config_v73.json` referenced inside it should **omit** `graph_names`
> (DLC graph names differ from ONNX->dll graph names and may not be predictable):
> ```json
> {
>   "devices": [{"cores": [{"rpc_control_latency": 100, "perf_profile": "burst"}]}]
> }
> ```

### Linux (aarch64)

```bash
${QAIRT_SDK_ROOT}/bin/aarch64-oe-linux-gcc11.2/qnn-context-binary-generator \
  --backend libQnnHtp.so \
  --model libQnnModelDlc.so \
  --dlc_path /absolute/path/to/model.dlc \
  --binary_file model \
  --soc_model <soc_model_id>
```

Output is written to an `output/` folder; the binary will be `output/model.bin`.

### soc_model Reference (Qnn_SocModel_t)

The `--soc_model` value selects the target SoC for offline compilation.
Source: `QnnTypes.h` enum `Qnn_SocModel_t` (QAIRT 2.45, deprecated but still valid).

> ⚠️ This enum is marked **Deprecated** — no new values will be added, but existing values remain valid.

**Common values for WoS / mobile targets:**

| `--soc_model` | Enum name | Snapdragon / Device | Common keywords |
|:------------:|-----------|---------------------|-----------------|
| `0` | `QNN_SOC_MODEL_UNKNOWN` | Auto-detect | default, unknown |
| `12` | `QNN_SOC_MODEL_SDM855` | Snapdragon 855 | sdm855, 855 |
| `21` | `QNN_SOC_MODEL_SDM865` | Snapdragon 865 | sdm865, 865 |
| `30` | `QNN_SOC_MODEL_SM8350` | Snapdragon 888 | sm8350, 888 |
| `36` | `QNN_SOC_MODEL_SM8450` | Snapdragon 8 Gen 1 | sm8450, 8gen1 |
| `37` | `QNN_SOC_MODEL_SC8280X` | Snapdragon 8cx Gen 3 | sc8280x, 8cx |
| `42` | `QNN_SOC_MODEL_SM8475` | Snapdragon 8+ Gen 1 | sm8475, 8plus |
| `43` | `QNN_SOC_MODEL_SM8550` | **Snapdragon 8 Gen 2** | sm8550, 8gen2 |
| `57` | `QNN_SOC_MODEL_SM8650` | **Snapdragon 8 Gen 3** | sm8650, 8gen3 |
| `60` | `QNN_SOC_MODEL_SC8380XP` | **Snapdragon X Elite (WoS ARM64 PC)** | sc8380, sc8380xp, 8380, x elite |
| `69` | `QNN_SOC_MODEL_SM8750` | **Snapdragon 8 Elite** | sm8750, 8elite |
| `85` | `QNN_SOC_MODEL_SM8735` | Snapdragon 8s Gen 4 | sm8735 |
| `87` | `QNN_SOC_MODEL_SM8850` | Snapdragon 8 Elite Gen 2 | sm8850 |
| `88` | `QNN_SOC_MODEL_SC8480XP` | **Snapdragon X2 Elite (WoS ARM64 PC)** | sc8480, sc8480xp, 8480, x2 elite |

> ⚠️ **Common mistake:** SM8650 (Snapdragon 8 Gen 3) = **57**, NOT 43.
> 43 = SM8550 (Snapdragon 8 Gen 2). Always verify using the table above.

> ℹ️ **When to use `--soc_model 0`**: If the target SoC is not in the table or is unknown,
> omit `--soc_model` or pass `0` to let the HTP backend decide.

**Full enum list (88 entries, snapshot from QAIRT 2.45 official SDK docs):**

| Value | Enum | Value | Enum | Value | Enum |
|------:|------|------:|------|------:|------|
| 1 | SDM845 | 30 | SM8350 | 57 | SM8650 |
| 2 | SDM835 | 31 | SM4350 | 58 | SSG2125P |
| 3 | SDM821 | 32 | SM7350 | 59 | SM4450 |
| 4 | SDM820 | 33 | QCS410 | **60** | **SC8380XP** |
| 5 | SDM801 | 34 | SM8325 | 61 | SM7435 |
| 6 | SDM670 | 35 | SM7325 | 62 | SA8540 |
| 7 | SDM660 | 36 | SM8450 | 63 | AIC100 |
| 8 | SDM652 | 37 | SC8280X | 64 | SM7550 |
| 9 | SDM636 | 38 | SM7315 | 65 | SM6450Q |
| 10 | SDM630 | 39 | SA8295 | 66 | QCS8550 |
| 11 | SDM625 | 40 | SM6225 | 67 | SA8620P |
| 12 | SDM855 | 41 | SM7450 | 68 | SM8635 |
| 13 | SDM710 | 42 | SM8475 | **69** | **SM8750** |
| 15 | SDM632 | **43** | **SM8550** | 70 | SM7675 |
| 16 | SM6150 | 45 | SXR1230P | 71 | SM4635 |
| 17 | SM7150 | 46 | SSG2115P | 72 | SA8797 |
| 18 | QCS405 | 47 | STP6225P | 73 | SM7635 |
| 19 | SM6125 | 48 | QCS6125 | 74 | SM6650 |
| 20 | QCS403 | 49 | QRB4210 | 75 | SXR2330P |
| 21 | SDM865 | 50 | SM6450 | 76 | SM6475 |
| 23 | IPQ6018 | 51 | QCS7230 | 77 | QCS9100 |
| 24 | IPQ6028 | 52 | SA8255 | 78 | QCM6690 |
| 25 | SM7250 | 53 | SXR2230P | 79 | IPQ9574 |
| 26 | SA8195 | 54 | SM7475 | 80 | IPQ5404 |
| 27 | SM6250 | 55 | SM4375 | 81 | IPQ5424 |
| 28 | SM4250 | 56 | QCM4325 | 82 | QCS8300 |
| 29 | SM6350 | **57** | **SM8650** | 83 | QCS2290 |
| | | | | 84 | SA525M |
| | | | | 85 | SM8735 |
| | | | | 86 | SM7750 |
| | | | | 87 | SM8850 |
| | | | | **88** | **SC8480XP** |

> ℹ️ Value `0` (`QNN_SOC_MODEL_UNKNOWN`) — pass `0` or omit `--soc_model` to let the backend auto-detect.
> For newer SoCs not in the table above, check `<QAIRT_SDK_ROOT>\include\QNN\QnnTypes.h` (`Qnn_SocModel_t` enum) — the C header is version-stable.

---

## Verification checklist

- [ ] Host arch matches model lib arch (or running on target device)
- [ ] Absolute paths used for all model file arguments
- [ ] Context binary (`.bin`) exists and is **non-zero size** (valid binary is typically several MB; 0-byte or 8-byte files indicate the real binary is in a `bins/` subdirectory)
- [ ] Binary loads correctly on `{TARGET_DEVICE}`
- [ ] `backend_extensions.json` and `htp_backend_config_v73.json` exist (WoS V73 only)


## See Also

- `scripts/qai_dev_gen_contextbin.py` — Wrapper script that handles both `.so` (Linux) and `.dll` (Windows) model libraries, supports `--config_file` for QAIRT 2.45 WoS V73
- `qai_dev_gen_contextbin_x86.py` — Host-arch-aware wrapper for generating QNN context binaries on x86/ARM hosts
- `scripts/model_config.json` — Template with `backend_extensions_template` and `htp_config_v73_template`
