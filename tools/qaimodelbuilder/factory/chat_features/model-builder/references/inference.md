# Inference Reference

`onnxwrapper.py` is a drop-in replacement for `onnxruntime` that routes inference through Qualcomm QAI AppBuilder (`QNNContext`). The `qai_runner.py` launcher injects it so existing `onnxruntime`-based scripts run unchanged.

For direct `qai_appbuilder` inference (WoS ARM64), use the scripts in `scripts/inference/`.

> ## 🚨 Rules for using `onnxruntime` in this skill (MANDATORY)
>
> | Scenario | Allowed EP | Note |
> |------|-----------|------|
> | Accuracy comparison (ONNX vs QNN) | `CPUExecutionProvider` ✅ | The only allowed use of `onnxruntime` in this skill |
> | Performance benchmark comparison | `CPUExecutionProvider` ✅ | Same as above |
> | NPU inference (this skill's models) | `qai_appbuilder` / `QNNContext` ✅ | The standard inference tool of this skill |
> | Running a model on the NPU | using `onnxruntime` ❌ | **Forbidden** — NPU inference always goes through `qai_appbuilder` / `QNNContext` |
>
> **General principle**: in this skill, `onnxruntime` is used ONLY for **CPU baseline comparison** (accuracy validation, numerical comparison before/after a patch).
> NPU inference MUST go through `qai_appbuilder` / `QNNContext`; never use `onnxruntime` to run a model on the NPU.
>
> 🚨 **The ONNX CPU baseline MUST run in a separate process from the QNN inference.** `qai_runner.py` uses `onnxwrapper.py` to do a **process-level** hot-swap of `sys.modules["onnxruntime"]` — any `import onnxruntime` later in the same process gets the QNN wrapper, which would route the baseline into QNN too (loading the `.onnx` as a QNN model → failure). Standard approach: **Process A** (x64, or not via qai_runner) runs the ONNX CPU baseline and saves `.npy`; **Process B** (ARM64 + qai_runner) runs QNN and saves `.npy`; **Process C** reads both sets of `.npy` and computes the cosine.

## ⚠️ CRITICAL: Model File Format and Context Binary

**qai_appbuilder supports three model formats (in priority order):**

| Format | Platform | Notes |
|--------|----------|-------|
| `.bin` (context binary) | ARM Windows / ARM Linux | **Best performance on the same target HW** — HTP-optimized, pre-compiled offline. **NOT cross-platform** (locked to one HTP version + host arch). |
| `.dlc` | ARM Windows / ARM Linux | SNPE/DLC format; **supported directly** — QNNContext compiles the graph on first load (slower cold start vs `.bin`). **Portable** across HTP versions / target devices. |
| `.dll` / `.so` | ARM Windows / ARM Linux | Compiled model lib; works but no HTP optimization cache |

> ℹ️ **DLC direct load behavior (verified on QAIRT 2.45 WoS):** `QNNContext` loading
> a `.dlc` file does on-the-fly graph compilation (equivalent to running
> `qnn-context-binary-generator` internally). Inference results are **numerically
> identical** to the corresponding `.bin` (cosine ≈ 1.000000); `.bin` is ~21-27%
> faster at p50 (Inception-V3 W8A8 measured) because it skips compilation.
>
> Cold-start may print these non-fatal warnings (safe to ignore):
> ```
> input_data_type: float, output_data_type: float
> warmup_parallel_stl
> ```

### Format selection (`.bin` vs `.dlc`) — when which

**Decision priority** (apply top-down):

1. **User explicitly asks for `.bin` or `.dlc`** → honor the user's choice. No further decision needed.
2. **Same machine: ARM64 Windows host == inference target** (the common case for local validation / development) → **prefer `.bin`** for best p50 latency.
3. **Cross-target deployment** (build on one machine, ship to another / many devices, possibly with different HTP versions) → **prefer `.dlc`**:
   - `.bin` is **locked to one HTP version + host arch** — a `.bin` built against `htp_v73` will not load on a `htp_v81` device, and vice-versa
   - `.dlc` is **portable**: the target device compiles `.dlc` → context-on-device at first load (one-time cold-start cost), then caches it
   - For ship-once / run-many-devices scenarios, `.dlc` is the correct artifact
4. **Linux / x64 Windows targets** (not yet supported by this skill, but on the roadmap) → format choice is **not yet finalized**. Until guidance is added, ask the user before assuming.

> 💡 **Quick validation / debugging**: `.dlc` direct load is also handy when you don't
> want to wait for `.bin` generation — same numerical result, just slower first run.

**Platform notes:**
- **ARM Windows (current focus)**: both `.bin` and `.dlc` work; pick per the decision above.
- **ARM Linux**: `.so` works directly; `.so.bin` improves load time (optional).
- **x86 Linux**: CPU-only, use x86 wrapper.

**If context binary generation failed:**
- **Windows**: → **Blocking Condition B8** — cannot generate `.bin`. Falling back to `.dll` is technically possible but not recommended; **using `.dlc` directly is usually the better fallback** (especially if cross-target portability is also desired).
- **Linux**: → Can proceed with `.so` library directly
- **Alternative**: Try SNPE flow (`.dlc`) if QNN HTP is incompatible

Linux: if generation fails, skip and run inference with `.so`. Record skip reason.

> **⚠️ IMPORTANT** (qai_runner.py wrapper): Pass the `.onnx` file path to `InferenceSession`. The wrapper searches for a matching QAIRT model file **in the same directory**. See [Model File Resolution](#model-file-resolution) below.

**Debugging**: run with `python qai_runner.py script.py` (QAIRT) or `python script.py` (ONNX baseline) to compare outputs.

---

## ⚠️ CRITICAL: Input Format — NCHW vs NHWC (--preserve_io Effect)

**This is the most common cause of wrong inference results with QNN HTP.**

The input format required by the QNN model depends on whether `--preserve_io` was used during conversion:

| Conversion flag | QNN model input format | Required inference input |
|----------------|----------------------|--------------------------|
| `--preserve_io` (used by `qai_convert_fp.py`) | **NCHW** `[1, C, H, W]` — same as ONNX/PyTorch | Pass NCHW directly (no transpose needed) |
| No `--preserve_io` | **NHWC** `[1, H, W, C]` — QNN default | Transpose: `np.transpose(x, (0,2,3,1))` |

> ⚠️ **`qai_convert_fp.py` uses `--preserve_io` by default** — the QNN model keeps the ONNX input format (NCHW for PyTorch models).
> Passing NHWC to a NCHW model causes channel dimension mismatch → completely wrong results (e.g., predicting "window screen" instead of "Samoyed").

**How to determine the correct input format:**
```python
# Step 1: Always check model I/O first
model = MyModel("model", "model.bin")
print(f"Input shapes: {model.getInputShapes()}")
# [1, 3, 299, 299] → NCHW (C=3 is second dim) → pass NCHW directly
# [1, 299, 299, 3] → NHWC (C=3 is last dim) → pass NHWC

# Step 2: Prepare input accordingly
if input_shape[1] == channels:  # NCHW: [N, C, H, W]
    inp = image_nchw.astype(np.float32)          # no transpose needed
else:                            # NHWC: [N, H, W, C]
    inp = np.transpose(image_nchw, (0,2,3,1)).astype(np.float32)
```

**Verification**: Always compare QNN output with PyTorch CPU baseline — if Top-1 differs significantly, check input format first.

---

## WoS ARM64 Direct Inference (QAIRT 2.45)

> ⚠️ **Python environment**: Use ARM64 Python 3.13 (`python_arm64_venv` from `${APP_ROOT}\data\config\qairt_env.json`).
> Read the actual path from `${APP_ROOT}\data\config\qairt_env.json` — do not hardcode.
> If this fails → run `Setup.bat` from the QAIModelBuilder project directory.

For Windows on Snapdragon ARM64, use `qai_appbuilder` directly.
The `scripts/inference/` directory contains **reference templates** for common model types.

> ⚠️ **IMPORTANT: Inference scripts are templates, not final scripts.**
> The scripts in `scripts/inference/` are starting-point templates. They may not work
> out-of-the-box for every model. When a user's model has different I/O shapes, data types,
> or pre/post-processing requirements, **you must customize the script** for that specific model.
>
> **Decision flow:**
> 1. Check model I/O with `infer_generic.py --model model.bin` (prints shapes and dtypes)
> 2. Select the closest template: classify / detect / segment / sr / generic
> 3. If the template doesn't match the model's output format → adapt the post-processing
> 4. Test with random input first, then with real data

### Inference Script Templates

| Script | Best for | Key customization points |
|--------|---------|--------------------------|
| `inference/infer_generic.py` | Any model, quick verification | Output format, reshape logic |
| `inference/infer_classify.py` | Classification (softmax output) | Input normalization, label mapping |
| `inference/infer_detect.py` | YOLO/SSD detection | Output tensor format, NMS params |
| `inference/infer_segment.py` | Semantic segmentation | Output channels, color palette |
| `inference/infer_sr.py` | Super-resolution | Input/output size, scale factor |

### How to Customize an Inference Script

When the template doesn't match the model:

```bash
# Step 1: Always start with infer_generic.py to inspect model I/O
python inference/infer_generic.py --model model.bin
# → Prints: input shapes, dtypes, output shapes, dtypes
```

```python
# Step 2: Identify mismatches
# Common issues:
#   - Output shape doesn't match template expectation
#   - Model uses NCHW but template expects NHWC
#   - Quantized model needs io_data_type=native
#   - Custom pre/post-processing required

# Step 3: Adapt the template
# Example: model outputs [1, 1000] logits (not softmax)
# → Add softmax in post-processing
# (inside your QNNContext subclass Inference method or after calling it)
logits = np.array(output).flatten()
probs = np.exp(logits - logits.max()) / np.exp(logits - logits.max()).sum()  # stable softmax
```

Write your own inference script following this pattern:

```python
from qai_appbuilder import (
    QNNContext, QNNConfig, Runtime, LogLevel, ProfilingLevel, PerfProfile
)
import numpy as np

# Step 1: Global QNN config — MUST be called BEFORE QNNContext
# qai_appbuilder 2.47 signature: (runtime, log_level, profiling_level, log_path)
# ⚠️ The old leading `qnn_lib_path` arg was REMOVED in 2.47 — do NOT pass "".
#    The package's bundled QNN libs are used automatically (no SDK path).
QNNConfig.Config(
    Runtime.HTP,           # runtime: Runtime.HTP or Runtime.CPU (enum, NOT string)
    LogLevel.WARN,         # log_level: LogLevel enum (ERROR/WARN/INFO/VERBOSE/DEBUG)
    ProfilingLevel.BASIC   # profiling_level: ProfilingLevel enum (OFF/BASIC/DETAILED)
)

# Step 2: Define model class (recommended: inherit QNNContext)
class MyModel(QNNContext):
    def Inference(self, input_data):
        output_data = super().Inference([input_data])[0]
        return output_data

# Step 3: Load model
# ⚠️ Signature: QNNContext(model_name: str, model_path: str)
# - model_name: arbitrary string identifier (e.g., "inception_v3")
# - model_path: supported formats: .bin (best) | .dlc | .dll
#   → .bin (context binary) = best performance, target format for deployment
#   → .dlc = SNPE format, also supported
#   → .dll = compiled model lib, works but slower (no HTP optimization cache)
# ❌ WRONG: QNNContext(model_path, config)
# ✅ CORRECT: QNNContext("name", "model.bin")  ← always prefer .bin
model = MyModel("my_model", r"C:\path\to\model.bin")

# Step 4: Inspect I/O (optional but recommended)
print(f"Input  shapes: {model.getInputShapes()}")
print(f"Output shapes: {model.getOutputShapes()}")
print(f"Input  dtypes: {model.getInputDataType()}")
print(f"Output dtypes: {model.getOutputDataType()}")

# Step 5: Prepare input — format depends on --preserve_io flag used during conversion
# ALWAYS check model input shape first: model.getInputShapes()
#   [1, C, H, W] → NCHW (qai_convert_fp.py uses --preserve_io by default) → pass NCHW directly
#   [1, H, W, C] → NHWC (no --preserve_io) → transpose from NCHW
input_shape = model.getInputShapes()[0]
if input_shape[1] == channels:  # NCHW: channel is dim 1
    inp = image_nchw.astype(np.float32)                          # no transpose needed
else:                            # NHWC: channel is last dim
    inp = np.transpose(image_nchw, (0, 2, 3, 1)).astype(np.float32)

# Step 6: Run inference with BURST performance mode
# CRITICAL: SetPerfProfileGlobal MUST be called AFTER at least one QNNContext
# model is loaded in the current process. If called before any model is loaded,
# the call silently does nothing and inference runs at default (non-BURST) speed.
# Correct lifecycle:
#   1. Load model(s): QNNContext(...)
#   2. Set BURST:     PerfProfile.SetPerfProfileGlobal(PerfProfile.BURST)
#   3. Run inference: model.Inference(...)
#   4. Release BURST: PerfProfile.RelPerfProfileGlobal()
#   5. Release model: del model
# If multiple models cooperate in one task, set BURST once before ALL inference
# and release once after ALL inference (not per-model).
PerfProfile.SetPerfProfileGlobal(PerfProfile.BURST)
output = model.Inference([inp_nhwc])   # inputs must be a LIST (see Key Notes)
PerfProfile.RelPerfProfileGlobal()

# Step 7: Process outputs
print(f"Output shape: {output.shape}")

# Step 8: Release resources
del model
```

### Key QAIRT 2.45 WoS Notes

| Item | Correct | Wrong |
|------|---------|-------|
| `QNNConfig.Config` call | Before `QNNContext(...)` | After or omitted |
| lib-dir arg | **Not passed** — removed in qai_appbuilder 2.47 (built-in libs used automatically) | Passing a leading `""` or SDK path (2.47 treats it as `runtime`) |
| `QNNConfig.Config` args | `(Runtime.HTP, LogLevel.WARN, ProfilingLevel.BASIC)` | `("", Runtime.HTP, ...)` (old 2.46 lib-dir form) |
| `runtime` param type | `Runtime.HTP` (enum) | `"Htp"` (string) |
| `log_level` param type | `LogLevel.WARN` (enum) | `1` (int) |
| `QNNContext` signature | `QNNContext("name", "model.bin")` | `QNNContext(model_path, config)` |
| Model file priority | `.bin` > `.dlc` > `.dll` (all supported; `.bin` = best perf) | Assuming only `.bin` works |
| Inference API | `model.Inference([inp])` | `model.Execute([inp])` |
| Input format | Depends on `--preserve_io`: NCHW if used (default), NHWC if not. **Always check `model.getInputShapes()` first.** | Assuming always NHWC |
| NCHW→NHWC conversion | Only needed when model input is NHWC: `np.transpose(x, (0,2,3,1))` | Always transposing |
| Performance mode | `PerfProfile.SetPerfProfileGlobal(PerfProfile.BURST)` — **must be called AFTER at least one model is loaded** (otherwise silently ineffective) | `perf_profile=PerfProfile.BURST` in `Inference()` |
| Performance lifecycle | Set BURST once before all inference → run all models → release once after all done | Setting/releasing per model call (stack imbalance) |
| Resource cleanup | `del model` | Leaving model in memory |

### 🚀 HTP BURST performance lifecycle (session / streaming workloads)

`PerfProfile.SetPerfProfileGlobal(PerfProfile.BURST)` raises the HTP to its
highest clock. For **streaming / session-based** inference (voice input / ASR,
TTS, or any task that runs many inferences over one logical session), the
lifecycle matters as much as the call itself:

1. **BURST only works AFTER ≥1 model (QNNContext) is loaded** in the process.
   Calling it with no context loaded silently does nothing (`setPowerConfig
   error 0x32c9`).
2. **Set BURST ONCE when the session/task begins, hold it for the WHOLE
   session, release ONCE when the task finishes.** Never Set/Rel per inference
   call — doing so makes the HTP ramp its clock up/down every call, giving slow
   and jittery latency (the first NPU call of each run pays the ramp-up cost).
   - **Voice input / streaming ASR**: raise HTP to BURST the moment recording
     starts (model begins working), hold it across **all** interim + final
     inference chunks, release only after the **entire** voice session ends
     (voice output finished). Not per audio chunk.
   - **TTS / multi-model pipeline**: Set once before the first NPU stage, hold
     across all cooperating models (BERT/encoder/flow/decoder…), release once
     after the last stage.
   - **One-shot single inference**: Set → infer → Release is fine (one call).
3. **Release BEFORE destroying contexts** (`RelPerfProfileGlobal()` while models
   are still loaded), else `You should set perf profile before you release it!`.

```python
# Session-scoped BURST (correct for streaming/ASR/TTS)
enc = QNNContext("encoder", "encoder.bin")      # 1. load model(s) first
PerfProfile.SetPerfProfileGlobal(PerfProfile.BURST)   # 2. session start: set ONCE
try:
    for chunk in session:                       # 3. many inferences, BURST held
        run_inference(enc, chunk)
finally:
    PerfProfile.RelPerfProfileGlobal()          # 4. session end: release ONCE
del enc                                          # 5. then destroy contexts
```

### QNNConfig.Config — Full Signature (qai_appbuilder 2.47)

```python
QNNConfig.Config(
    runtime: str = Runtime.HTP,          # Runtime.HTP or Runtime.CPU (use enum)
    log_level: int = LogLevel.ERROR,     # LogLevel.ERROR/WARN/INFO/VERBOSE/DEBUG (use enum)
    profiling_level: int = ProfilingLevel.OFF,  # ProfilingLevel.OFF/BASIC/DETAILED (use enum)
    log_path: str = "None"               # log file path; "None" = console output
) -> None
# NOTE: 2.47 removed the old leading `qnn_lib_path` arg. The package's bundled
# libs/ is used automatically — do NOT pass a lib dir (passing "" makes 2.47
# treat it as the runtime and fail with "backend library does not exist: Qnn.dll").
```

### QNNContext — Full Constructor Signature

```python
QNNContext(
    model_name: str = "None",            # unique model identifier string
    model_path: str = "None",            # model file path — supported: .bin | .dlc | .dll
                                         # .bin (context binary) = best performance, preferred
                                         # .dlc = SNPE format
                                         # .dll = compiled model lib (no HTP cache)
    backend_lib_path: str = "None",      # QnnHtp.dll path; "None" = built-in (v2.0.0+)
    system_lib_path: str = "None",       # QnnSystem.dll path; "None" = built-in (v2.0.0+)
    is_async: bool = False,              # async inference mode
    input_data_type: str = DataType.FLOAT,   # DataType.FLOAT or DataType.NATIVE
    output_data_type: str = DataType.FLOAT   # DataType.FLOAT or DataType.NATIVE
)
```

### Using Inference Templates (`scripts/inference/`)

> 💡 **These are reference templates.** Always verify model I/O first with `infer_generic.py`,
> then select and customize the appropriate template for your model.

#### Common arguments (all 5 templates)

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--model` | Yes | — | Path to QNN context binary (`.bin`) |
| `--input` | No* | — | Path to a single input image (not in `infer_generic.py`) |
| `--input_dir` | No* | — | Directory of images for batch mode (not in `infer_generic.py`) |
| `--runtime` | No | `Htp` | `Htp` or `Cpu` |
| `--log_level` | No | `1` | `0`=ERROR `1`=WARN `2`=INFO `3`=VERBOSE |

*For `infer_classify/detect/segment/sr.py`: one of `--input` or `--input_dir` is required.

#### `infer_generic.py` — extra arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--raw_paths` | — | One or more `.raw` float32 input files (alternative to `--input`) |
| `--output_dir` | — | Directory to save raw output files |
| `--io_data_type` | `float` | `float` or `native` (use `native` for quantized models) |

#### `infer_classify.py` — extra arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--labels` | — | Labels file: `.json` list or `.txt` one-per-line |
| `--topk` | `5` | Number of top predictions to display |
| `--input_size` | auto from model | Resize shorter edge to this size, then center-crop |
| `--normalize` | False | Apply ImageNet normalization (mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]) |

**Auto-detects NCHW/NHWC** from `model.getInputShapes()`: if `shape[1] in (1,3,4)` and `shape[1] < shape[2]` → NCHW, else NHWC. Transposes input automatically — no manual transpose needed.

**Preprocessing pipeline** (inside script, not configurable via CLI):
1. `Image.open().convert("RGB")`
2. Resize: scale shortest edge to `input_size`, then center-crop to `input_size × input_size`
3. Normalize to `[0, 1]` (divide by 255)
4. If `--normalize`: apply ImageNet mean/std
5. Add batch dim → `(1, H, W, C)` NHWC, then transpose to NCHW if model expects it

**Output**: softmax probabilities, Top-K `(label, score, class_idx)` printed to stdout.

#### `infer_detect.py` / `infer_segment.py` / `infer_sr.py` — extra arguments

| Script | Argument | Default | Description |
|--------|----------|---------|-------------|
| `infer_detect.py` | `--conf` | `0.45` | Confidence threshold for detections |
| `infer_detect.py` | `--iou` | `0.7` | IoU threshold for NMS |
| `infer_segment.py` | `--output_dir` | — | Directory to save output mask images |
| `infer_segment.py` | `--alpha` | `0.5` | Blend alpha for mask overlay on original image |
| `infer_sr.py` | `--output_dir` | — | Directory to save upscaled output images |
| `infer_sr.py` | `--scale` | `4` | Upscale factor (e.g., `2`, `4`) |

`infer_sr.py` and `infer_classify.py` both auto-detect NCHW/NHWC I/O.

> ⚠️ **For detection, prefer using the `infer_detect.py` template directly — do not hand-write NMS.** Hand-written NMS very easily hits `IndexError` when a class has only 1 candidate box left (still doing `cls_boxes[0]` after the candidate array has been emptied); if you must write your own, add `if len(cls_boxes)==0: break` before extracting results.

---

```bat
REM Step 1: Inspect model I/O (always do this first)
python scripts\inference\infer_generic.py --model model.bin
REM -> Prints input/output shapes and dtypes

REM Step 2a: Super-resolution model
python scripts\inference\infer_sr.py --model model_fp16.bin --input image.png --scale 4

REM Step 2b: Image classification model (with ImageNet labels + normalization)
python scripts\inference\infer_classify.py --model model.bin --input image.jpg ^
  --labels imagenet_labels.json --topk 5 --normalize

REM Step 2b (minimal, no labels file)
python scripts\inference\infer_classify.py --model model.bin --input image.jpg --topk 5

REM Step 2c: Object detection model (YOLO-style)
python scripts\inference\infer_detect.py --model model.bin --input image.jpg ^
  --conf 0.45 --iou 0.7

REM Step 2d: Semantic segmentation model
python scripts\inference\infer_segment.py --model model.bin --input image.jpg ^
  --alpha 0.5

REM Step 2e: Any other model (generic, raw I/O)
python scripts\inference\infer_generic.py --model model.bin ^
  --raw_paths input.raw --output_dir outputs\

REM Batch processing (all templates support --input_dir)
python scripts\inference\infer_classify.py --model model.bin ^
  --input_dir images\ --labels labels.json
```

> ⚠️ **If the template output doesn't look correct:**
> 1. Check output tensor shape with `infer_generic.py`
> 2. Verify input format (NHWC vs NCHW) — check `model.getInputShapes()`: NCHW if `--preserve_io` was used (default), NHWC otherwise
> 3. Adapt post-processing in the template to match your model's output format
> 4. For quantized models, add `--io_data_type native` to `infer_generic.py`

---

## qai_runner.py Wrapper Usage

```bash
# Copy wrapper scripts into the working folder, then run:
python qai_runner.py path/to/inference_script.py
```

### Target Device Inference over SSH

Inference can also be run directly on the target device over SSH. Before launching inference, you **must** source the QAIRT setup script on the target device.

This setup script path is **user-provided** (it is environment-specific) and typically performs tasks such as:
- Exporting required environment variables (e.g., `PATH`, `LD_LIBRARY_PATH`, `PYTHONPATH`, `QNN_SDK_ROOT`, etc.)
- Activating a Python virtual environment (if your workflow uses one)
- Initializing QAIRT/QNN runtime environment

Example:

```bash
ssh ubuntu@<target-ip>
. /home/ubuntu/aienv.sh
python qai_runner.py path/to/inference_script.py
```

### Linux ARM HTP Environment (manual export only)

If HTP initialization fails on Linux ARM, you need to set `QAIRT_SDK_ROOT` /
`QNN_SDK_ROOT` / `PRODUCT_SOC` / `DSP_ARCH` / `ADSP_LIBRARY_PATH` /
`LD_LIBRARY_PATH` in the shell before running. **Full setup, error symptoms
(`Stub lib id mismatch`, `Failed to create transport ... error: 1008`),
diagnostic checklist, and SSH-one-liner pattern → [troubleshooting.md § HTP transport/version mismatch (Linux ARM)](troubleshooting.md).**

### x86 Host Inference (ONNX Wrapper Variant)

For x86 inference, use the x86-specific wrapper source file and place it in your project as `onnxwrapper.py`:

```bash
# From skill scripts folder to project folder:
cp ${APP_ROOT}/factory/chat_features/model-builder/scripts/onnxwrapper_x86.py ./onnxwrapper.py
cp ${APP_ROOT}/factory/chat_features/model-builder/scripts/qai_runner.py ./
python qai_runner.py path/to/inference_script.py
```

This keeps your inference script unchanged (`import onnxruntime as ort`) while routing execution through the x86-compatible QAIRT wrapper.

Note for x86 wrapper behavior:
- `onnxwrapper_x86.py` is CPU-only by design for stable host execution.
- Runtime selection like `QAI_QNN_RUNTIME=HTP` is ignored by this wrapper.
- Recommended usage remains simply:
```bash
python qai_runner.py path/to/inference_script.py
```

Inference script uses standard `onnxruntime` API — pass the `.onnx` path; the wrapper resolves the QNN model automatically:

```python
# ✅ CPUExecutionProvider: for ONNX CPU baseline comparison (the allowed use within this skill)
import onnxruntime as ort
sess = ort.InferenceSession("model.onnx")  # defaults to CPUExecutionProvider
outputs = sess.run(None, {"input_name": input_tensor})

# ❌ Forbidden: do NOT use onnxruntime to run the model on the NPU
# NPU inference always goes through qai_appbuilder / QNNContext (loading .bin / .dlc)
```

---

## Model File Resolution

Given an `.onnx` path, the wrapper searches for the QNN model in this order:

**Linux**: `model.htp.bin`→ `model.so.bin` → `model.so` → `libmodel.htp.bin`  → `libmodel.so.bin` → `libmodel.so` → `model.bin` → `libmodel.bin`

**Windows**: `model.htp.bin`→ `model.dll.bin` → `libmodel.htp.bin` → `libmodel.dll.bin` → `libmodel.dll` → `model.bin`  → `libmodel.bin`

Any file ending in `.bin` (including `.so.bin`, `.dll.bin`) is treated as a context binary (`--retrieve_context`).

### Practical Example

If your script loads `esrgan.onnx`, copy the context binary to match:

```powershell
# After conversion produces qairt_output\esrgan.dll.bin
# Copy to match ONNX naming:
Copy-Item qairt_output\esrgan.dll.bin .\esrgan.onnx.dll.bin
# OR
Copy-Item qairt_output\esrgan.dll.bin .\esrgan.dll.bin

# Now qai_runner.py can find the QNN model:
python qai_runner.py inference.py
```

---

## IO Config YAML

QNN may reorder I/O relative to the original ONNX. The wrapper uses a YAML to remap names, dtypes, and layouts so outputs are returned in the correct ONNX order.

Search order (first found wins): `QAI_IO_CONFIG` env → `{model_wo_ext}.yaml` → `{model_wo_ext}.autogen.yaml` → `{model_name}.{runtime}.autogen.yaml` → `{model_name}.yaml`

If no YAML is found, one is auto-generated from `QNNContext` IO specs and saved as `{model_name}.{runtime}.autogen.yaml`. Inspect it if outputs are wrong.

```yaml
inputs:
  - name: images
    dtype: float32
    layout: NCHW      # triggers NCHW→NHWC before inference
    add_batch: true
outputs:
  - name: output0
    dtype: float32
    layout: NCHW      # triggers NHWC→NCHW after inference
```

---

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `QAI_QNN_RUNTIME` | `HTP` | `HTP` or `CPU` |
| `QAI_IO_CONFIG` | — | Explicit path to IO YAML |
| `QAI_IO_AUTOGEN_SAVE` | `1` | Save auto-generated YAML (`0` to disable) |

---

## Validation Checklist

- [ ] Input tensor name/shape matches model
- [ ] Preprocessing matches training/export assumptions
- [ ] **Input format verified**: check `model.getInputShapes()` — NCHW if `--preserve_io` used (default with `qai_convert_fp.py`), NHWC otherwise. Wrong format → completely wrong results.
- [ ] Output tensor mapping is correct (check autogen YAML if wrong)
- [ ] Cosine similarity vs ONNX CPU baseline ≥ 0.99 (FP) / ≥ 0.95 (INT8)
  > ⚠️ **If below threshold: do NOT auto-apply fixes.** First run a zero-cost diagnosis (e.g. is calibration data a single image / its augmentations?), then STOP and report to the user — present the accuracy-fix options **with a one-line principle each** and ask which to try: (1) improve calibration diversity (real multi-class data) — *quantizer estimates activation ranges from calibration data*; (2) `run_pipeline.py --cle --per_channel` (built into Flow A) — *CLE equalizes per-channel weight ranges across layers*; (3) raise to W8A16 (`--precision w8a16`) — *16-bit activations keep more dynamic range*; (4) keep FP16 or try `--precision bf16` — *no quant loss; bf16 gives wider dynamic range than FP16*; (5) accept current precision if Top-K is correct. Same policy as SKILL.md B6 / inference-validation step 6.
- [ ] Latency / FPS collected on target runtime

---

## See Also

- `scripts/inference/infer_generic.py` — Generic inference script for WoS ARM64 (qai_appbuilder)(auto-detects NCHW/NHWC I/O)
- `references/context_binary.md` — Context binary generation guide
- `references/win_qairt_setup.md` — WoS ARM64 environment setup
