# Troubleshooting Reference

## Conversion failures
1. Run dry-run first and capture logs.
2. Identify first blocking op/error.
3. Patch model graph/export path.
4. Re-export ONNX and retry conversion.

## Common blocker: unsupported Einsum
- Symptom: converter error with specific `Einsum` equation.
- Action:
  - patch/rewrite unsupported einsum path to primitive ops
  - validate patched ONNX
  - rerun dry-run and conversion
- **Full guide**: See [In-Memory Operator Patching](operator_patching.md) for detailed patching templates and validation steps.

## Dynamic input errors (SNPE)
- Symptom: `Missing command line inputs for dynamic inputs [...]`
- Action: pass input dims using:
  - wrapper: `--source-model-input-shape <name> <dims>`
  - direct: `--source_model_input_shape <name> <dims>`

## Inference runtime validation failures
- Check runtime/backend compatibility for generated DLC/lib.
- Re-check I/O layout, data type, and pre/post-processing consistency.
- Test with minimal input list and known-good sample.

## WoS ARM64: QNNContext silent crash / abnormally low cosine

| Symptom | Root cause | Action |
|------|------|------|
| `QNNContext(...)` exits on load (exit 1 / 0xC0000005, no traceback) | ① `QNNConfig.Config()` was not called first; ② **`QnnHtp.dll`/`QnnSystem.dll` from the QAIRT SDK directory were specified manually**, conflicting with the package's bundled versions | Call `QNNConfig.Config(Runtime.HTP, ...)` first (qai_appbuilder 2.47 signature — no lib-dir arg; the package's bundled `libs/` is used automatically), and do **NOT** pass an SDK path |
| Inference runs but cosine is abnormally low (e.g. 0.83, far below the FP16 threshold) | A **stale old artifact** left in the workspace was used by mistake (old `.dll`/`.bin` from a different ONNX / different patch / aux branch not disabled) | Confirm the loaded artifacts are the ones **freshly generated this run** (compare timestamps/sizes); old artifacts should be isolated as a backup by `qai_workspace_init.py` — do not manually reuse them |

## HTP transport/version mismatch (Linux ARM)

**Symptoms**:
- `Stub lib id mismatch: expected (...), detected (...)`
- `Failed to create transport for device, error: 1008`
- `Failed to load skel` / `Transport layer setup failed`
- Segmentation fault shortly after QNN session creation

**Likely cause**:
- Mixed QAIRT/QNN runtime components are being loaded on target (version/path mismatch across user-space libs and DSP-side libs).

**Action**:
1. Ensure target env uses a single QAIRT SDK root:
   ```bash
   export QAIRT_SDK_ROOT=/path/to/qairt/<version>
   export QNN_SDK_ROOT="${QNN_SDK_ROOT:-$QAIRT_SDK_ROOT}"
   ```
2. Set SoC + DSP arch and DSP library path:
   ```bash
   # Replace with your target values (examples only).
   export PRODUCT_SOC=<your_soc_id>        # e.g., 9075, 8650, ...
   export DSP_ARCH=<your_dsp_arch>         # e.g., 73, 75, ...
   export ADSP_LIBRARY_PATH="$QNN_SDK_ROOT/lib/hexagon-v${DSP_ARCH}/unsigned"
   ```
   If unsure, use the target's known platform config and keep `PRODUCT_SOC` and `DSP_ARCH` matched.
3. Ensure ARM64 runtime libs are on loader path:
   ```bash
   export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$QNN_SDK_ROOT/lib/aarch64-oe-linux-gcc11.2"
   ```
4. Re-source env and rerun inference via wrapper:
   ```bash
   . /home/ubuntu/aienv.sh
   python qai_runner.py infer_qnn.py
   ```
5. If still failing, print and verify path precedence:
   - `echo $QAIRT_SDK_ROOT`
   - `echo $QNN_SDK_ROOT`
   - `echo $ADSP_LIBRARY_PATH`
   - `echo $LD_LIBRARY_PATH`

**Expected result after fix**:
- `stub lib id mismatch` and transport `1008` errors disappear.
- HTP inference proceeds; non-fatal power-config warnings may remain.

## Escalate when
- same failure persists after patch + retry
- converter fails on required op with no feasible rewrite
- runtime rejects graph post-conversion

Escalation bundle:
- ONNX (original + patched)
- conversion command
- dry-run log
- conversion log
- minimal reproduce steps

## run_pipeline.bat

Known issues (QAIRT_SDK_ROOT not read, DLL search picking QnnHtp.dll, context binary exit code false failure) are all fixed in the current `run_pipeline.bat`. Use the latest version from the project.

## PowerShell Variable Expansion (Windows)

**Symptom**: Commands fail with errors like:
- `:PATH is not recognized...`
- `/usr/bin/bash.PSIsContainer is not recognized...`
- Variables silently expanded to wrong values

**Cause**: Bash interprets PowerShell variables (`$_`, `$env:`, `!`) before PowerShell receives them.

**Solutions** (in order of preference):

1. **Use Python instead of shell** (recommended):
   ```python
   import glob
   files = glob.glob("output/**/*.dll", recursive=True)
   ```

2. **Write PowerShell to temp file**:
   ```python
   import tempfile, subprocess, os
   with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False) as f:
       f.write("Get-ChildItem -Recurse | Where-Object {!$_.PSIsContainer}")
       ps1 = f.name
   subprocess.run(["powershell", "-File", ps1])
   os.unlink(ps1)
   ```

3. **Single-quote the command** (fragile, not recommended for complex scripts):
    ```bash
    powershell -Command 'Get-ChildItem | ForEach-Object { $_.FullName }'
    ```

## QNN Multi-Model Same-Process (Sticky Worker) Rules

When multiple QNN models run **in the same process** (e.g. sticky worker with
whisper-base + zipformer-zh + melotts-zh), the following rules MUST be observed
to avoid `Incorrect amount of Input Buffers` / graph binding errors:

### Rule 1: `model_name` must be globally unique

`QNNContext(model_name, model_path, ...)` uses `model_name` as an internal key.
If two models share the same name (e.g. both have `encoder.bin`), the QNN runtime
will **reuse the first-loaded graph** for any subsequent context with the same name.

**Symptom**: `Incorrect amount of Input Buffers for graphIdx: 0. Expected: N, received: M`
where N belongs to a *different* model's graph.

**Fix**: Use a unique name per context, e.g. `{model_id}_{filename_stem}`:
```python
# BAD  — name collision across models
QNNContext("encoder", "models/whisper-base/encoder.bin", ...)
QNNContext("encoder", "models/zipformer-zh/encoder.bin", ...)  # reuses whisper graph!

# GOOD — globally unique names
QNNContext("whisper-base_encoder", "models/whisper-base/encoder.bin", ...)
QNNContext("zipformer-zh_encoder", "models/zipformer-zh/encoder.bin", ...)
```

### Rule 2: `QNNConfig.Config()` must be called exactly once per process

`QNNConfig.Config` sets global runtime state (backend lib path, log level,
profiling level). Calling it multiple times may corrupt loaded graph state.

**Canonical call** (matches reference samples):
```python
QNNConfig.Config(Runtime.HTP, LogLevel.WARN, ProfilingLevel.BASIC)
```

- First argument `""` (empty string) — lib path auto-resolves to package `libs/` dir.
- All positional, no keyword args.
- Guard with a module-level flag to prevent repeated calls.

### Rule 3: `input_data_type` / `output_data_type` is per-context

Each `QNNContext` can use a different data type independently:
```python
# NATIVE mode — pass tensors in model's native dtype (int32, float16, etc.)
# Better performance, no type conversion overhead.
QNNContext("whisper-base_encoder", path, input_data_type=DataType.NATIVE, output_data_type=DataType.NATIVE)

# FLOAT mode — all tensors converted to float32 internally (default)
QNNContext("melotts_bert", path, input_data_type=DataType.FLOAT, output_data_type=DataType.FLOAT)
```

`DataType.NATIVE` = `"native"` (string), `DataType.FLOAT` = `"float"` (string).

When using NATIVE mode, ensure input tensors match the model's expected dtype
(e.g. `np.float16` for mel spectrograms, `np.int32` for token indices). The
model will NOT auto-convert types in NATIVE mode.

### Rule 4: Reference sample pattern

The canonical multi-model setup (from `whisper_base_en.py`):
```python
from qai_appbuilder import QNNContext, QNNConfig, Runtime, LogLevel, ProfilingLevel, DataType

# 1. Config once
QNNConfig.Config(Runtime.HTP, LogLevel.WARN, ProfilingLevel.BASIC)

# 2. Load contexts with unique names + NATIVE for best performance
encoder = QNNContext("whisper_encoder", encoder_path,
                     input_data_type=DataType.NATIVE, output_data_type=DataType.NATIVE)
decoder = QNNContext("whisper_decoder", decoder_path,
                     input_data_type=DataType.NATIVE, output_data_type=DataType.NATIVE)

# 3. Inference — pass list of numpy arrays matching native dtypes
output = encoder.Inference([mel_input])  # mel_input: np.float16
```
