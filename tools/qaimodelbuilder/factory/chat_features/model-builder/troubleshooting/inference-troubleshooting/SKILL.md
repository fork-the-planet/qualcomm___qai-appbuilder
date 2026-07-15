---
skill_id: inference-troubleshooting
tier: base
triggers: ["QNNContext exit 1", "0xC0000005", "stale artifact", "异常低 cosine", "Incorrect amount of Input Buffers", "Stub lib id mismatch", "transport 1008", "NCHW", "NHWC"]
sources: ["references/troubleshooting.md", "references/inference.md"]
---

# Inference Troubleshooting (base)

> 🧭 通用诊断骨架（四阶段 + 三铁律 + 反向追溯 + 多层加固）见 [`../_diagnosis-framework.md`](../_diagnosis-framework.md)；本 SKILL 是该总纲在"运行时崩溃/错误结果"领域的症状库。

## Responsibility

Diagnose runtime failures and wrong results when running `.bin`/`.dlc`/`.dll` through
`qai_appbuilder` / `QNNContext`: silent load crashes, stale-artifact low cosine, NCHW/NHWC
input mismatch, multi-model same-process buffer collisions, and Linux HTP transport/version
mismatch. Inference on the NPU MUST go through `qai_appbuilder`/`QNNContext` — never route it
through `onnxruntime` (CPUExecutionProvider is allowed **only** for the CPU baseline comparison,
and that baseline MUST run in a separate process).

## Trigger signals

- `QNNContext(...)` exits on load (exit 1 / `0xC0000005`, no traceback)
- Inference runs but cosine is abnormally low (e.g. 0.83, far below FP16 threshold)
- `Incorrect amount of Input Buffers for graphIdx: 0. Expected: N, received: M`
- `Stub lib id mismatch` / `Failed to create transport ... error: 1008` / `Failed to load skel`
- Wrong predictions (e.g. "window screen" instead of "Samoyed") → suspect NCHW/NHWC

## Core knowledge

### WoS ARM64: QNNContext silent crash / abnormally low cosine

| Symptom | Root cause | Action |
|---------|------------|--------|
| `QNNContext(...)` exits on load (exit 1 / 0xC0000005, no traceback) | ① `QNNConfig.Config()` not called first; ② manually passed SDK `QnnHtp.dll`/`QnnSystem.dll`, conflicting with the package's bundled versions | Call `QNNConfig.Config(Runtime.HTP, LogLevel.WARN, ProfilingLevel.BASIC)` first (qai_appbuilder 2.47 — **no lib-dir arg**, bundled `libs/` used automatically); do **NOT** pass an SDK path |
| Inference runs but cosine abnormally low (e.g. 0.83) | A **stale old artifact** (old `.dll`/`.bin` from a different ONNX / patch / aux branch not disabled) was used by mistake | Confirm loaded artifacts are the ones **freshly generated this run** (compare timestamps/sizes); old artifacts are backed up by `qai_workspace_init.py` — never manually reuse them |

### NCHW vs NHWC — #1 cause of wrong results

Input format depends on whether `--preserve_io` was used at conversion:

| Conversion flag | QNN model input | Required input |
|-----------------|-----------------|----------------|
| `--preserve_io` (default in `qai_convert_fp.py`) | **NCHW** `[1,C,H,W]` — same as ONNX/PyTorch | pass NCHW directly (no transpose) |
| No `--preserve_io` | **NHWC** `[1,H,W,C]` — QNN default | `np.transpose(x,(0,2,3,1))` |

**Always** check `model.getInputShapes()` first: `[1,3,H,W]` → NCHW (pass directly); `[1,H,W,3]` → NHWC (transpose). Passing NHWC to an NCHW model = channel mismatch = completely wrong results. Verify against a PyTorch/ONNX CPU baseline; if Top-1 differs, check input format first.

### Multi-model same-process (sticky worker) rules

When multiple QNN models run in one process, to avoid `Incorrect amount of Input Buffers`:

1. **`model_name` must be globally unique** — `QNNContext` uses it as an internal key; two contexts named `"encoder"` make the second reuse the first's graph. Use `{model_id}_{stem}` (e.g. `whisper-base_encoder`).
2. **`QNNConfig.Config()` exactly once per process** — it sets global state; repeated calls may corrupt loaded graphs. Guard with a module-level flag. Canonical: `QNNConfig.Config(Runtime.HTP, LogLevel.WARN, ProfilingLevel.BASIC)`.
3. **`input_data_type`/`output_data_type` is per-context** — `DataType.NATIVE` (`"native"`) for best perf (must feed the model's native dtype, e.g. `np.float16` mels, `np.int32` tokens — no auto-convert); `DataType.FLOAT` (`"float"`) converts to float32 internally.

### Linux ARM: HTP transport / version mismatch

**Symptoms:** `Stub lib id mismatch: expected(...) detected(...)`, `Failed to create transport ... error: 1008`, `Failed to load skel` / `Transport layer setup failed`, segfault shortly after session creation.
**Cause:** mixed QAIRT/QNN runtime components (version/path mismatch across user-space + DSP-side libs).
**Action:**
1. Single QAIRT root: `export QAIRT_SDK_ROOT=/path/to/qairt/<version>; export QNN_SDK_ROOT="${QNN_SDK_ROOT:-$QAIRT_SDK_ROOT}"`
2. Match SoC + DSP arch: `export PRODUCT_SOC=<id>; export DSP_ARCH=<n>; export ADSP_LIBRARY_PATH="$QNN_SDK_ROOT/lib/hexagon-v${DSP_ARCH}/unsigned"`
3. Loader path: `export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$QNN_SDK_ROOT/lib/aarch64-oe-linux-gcc11.2"`
4. Re-source env, rerun: `python qai_runner.py infer_qnn.py`
5. Still failing → print/verify path precedence of all four env vars.
**Expected after fix:** `stub lib id mismatch` and transport `1008` disappear; non-fatal power-config warnings may remain.

### Correct qai_appbuilder API (QAIRT 2.45 WoS)

| Item | Correct | Wrong |
|------|---------|-------|
| Config call | before `QNNContext(...)` | after / omitted |
| lib-dir arg | not passed (removed in 2.47) | passing `""` or SDK path → `backend library does not exist: Qnn.dll` |
| Config args | `(Runtime.HTP, LogLevel.WARN, ProfilingLevel.BASIC)` (enums) | `("", ...)` or ints/strings |
| Context signature | `QNNContext("name", "model.bin")` | `QNNContext(model_path, config)` |
| Model priority | `.bin` > `.dlc` > `.dll` (all work; `.bin` best perf) | assuming only `.bin` |
| Inference API | `model.Inference([inp])` | `model.Execute([inp])` |
| Perf mode | `PerfProfile.SetPerfProfileGlobal(PerfProfile.BURST)` / `RelPerfProfileGlobal()` | `perf_profile=` in `Inference()` |
| Cleanup | `del model` | leaving in memory |

### Model file resolution & wrong-output checklist

- `qai_runner.py` wrapper: pass the `.onnx` path; it searches for the QNN model in the same dir (`.htp.bin`→`.dll.bin`→`.dll`→`.bin`). Any `*.bin` is treated as a context binary. If needed, copy `esrgan.dll.bin` → `esrgan.onnx.dll.bin` to match.
- QNN may reorder I/O — the wrapper uses an IO-config YAML (auto-generated as `{model}.{runtime}.autogen.yaml`) to remap names/dtypes/layouts. Inspect it if outputs are wrong.
- Wrong output steps: (1) check output shape with `infer_generic.py`; (2) verify NHWC vs NCHW; (3) adapt post-processing; (4) quantized model → `--io_data_type native`.

## 非崩溃 API 错误码诊断骨架（runtime error, non-crash）

> **适用**：QNN/HTP 运行期**非崩溃**失败——DSP 没有 abort/SSR/segfault，而是某个 QNN API 返回非零错误码、推理管线"优雅地"失败。典型根因是不兼容的特性组合、缺失的内部状态、或 API 调用顺序错误。
> **不适用**：有 CDSP 崩溃 dump / SSR（走稳定性排障）；纯精度退化（→ B6/accuracy）。

**核心诊断心法**：在 verbose.log 里追踪完整的 API 调用序列，定位"失败的那个 API 期望什么内部状态"，再回头找"是哪个更早的 API 没能把这个状态填上"。**晚失败的 API，缺的往往是早 API 没有填好的状态。** 只读 ERROR 行不够——根因通常藏在错误之前的 VERBOSE 行里（日志须开到 VERBOSE 级）。

**骨架五步**：
1. **提取错误签名**：定位失败的 API + 错误码 + 错误消息。`grep "\[ ERROR \]\|<E>"` / `grep "err = \|status.*0x"` / `grep "QnnContext_\|QnnGraph_\|QnnMem_"`。通用码：`QNN_GRAPH_ERROR_INVALID_ARGUMENT`（tensor/graph 参数不匹配）、`QNN_CONTEXT_ERROR_MEM_ALLOC`（DMA/RPC 内存不足）、`NO_ERROR(0) 但输出错`（buffer 偏移/注册错误）、`数字码+"failed…null"`（晚 API 读到空的缓存状态 = 早 API 没填）。
2. **绘制特性矩阵**：非崩溃错误码往往来自**特性组合**而非单一 API。用 grep 扫 verbose.log 判断哪些特性激活（回调式 context 创建 / 权重共享 mmap-vs-DMA / 多 context / 选择性图加载 / 多线程反序列化 / 持久化二进制切换），摆成勾选矩阵——不要假设各特性正交（交互常无文档）。
3. **重建完整 API 时序**（反向追溯起点）：`grep "QnnContext_create\|_free\|QnnGraph_retrieve\|_execute\|QnnMem_register\|_deRegister"`。对每个资源记录：创建方法（同步 vs 回调，内存所有权不同）、资源加载（mmap vs DMA 回调、映射到哪些地址）、注册/映射、创建后操作。
4. **正常 vs 异常路径 diff**：若关掉某特性能跑，把两份 verbose.log 并排 diff（`Allocate\|Map\|const pool\|buffer\|register`）。关键对比：正常路径 QNN 内部有没有缓存某地址/状态？异常路径这一步是否被跳过？——**这一步直接对应"晚失败 API 缺早 API 状态"**。
5. **审查调用方代码落到根因**：config 生命周期（警惕栈上分配的 `QnnContext_Config_t` 被 push 进 vector 后指针悬垂）、回调实现（偏移对齐/页边界/返回 offset-size）、缓冲区生命周期（fd 是否保持打开、DMA 是否过早 `munmap`/`close`）、是否检查了**每一个** QNN API 返回值、特性是否有条件启用。

**通用陷阱**：混淆同步式（QNN 管内存）与回调式（caller 管内存）context 创建；只读 ERROR 行不追 VERBOSE 序列；没验证"关掉某特性后能否跑通"隔离变量；栈上 config 悬垂；偏移分析混用十六/十进制。

> 本骨架是 `../_diagnosis-framework.md`（四阶段总纲）在"QNN API 错误码"场景的具体化——先按总纲，再套本五步。

## Related Blocking Conditions

- **B6** — cosine below threshold after quantization → see `accuracy/quantization-accuracy` skill (do NOT auto-apply fixes; diagnose then stop and report).
- **B8** — falling back to `.dlc` direct load is usually a better fallback than `.dll` when `.bin` generation failed (numerically identical, ~21-27% slower p50).

## Escalation path

Stop and report when: silent crash persists after Config-first + fresh-artifact checks; low cosine not explained by stale artifact or NCHW/NHWC (→ likely a quantization-accuracy issue, B6); Linux transport errors persist after env alignment; runtime rejects the graph. Never substitute ONNX/CPU inference for a failed QNN/HTP run.

Full API signatures, templates, and IO-config details → `references/inference.md` and `references/troubleshooting.md`.
