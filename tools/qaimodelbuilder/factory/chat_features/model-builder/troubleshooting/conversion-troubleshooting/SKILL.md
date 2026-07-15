---
skill_id: conversion-troubleshooting
tier: base
triggers: ["Graph Compose failure", "unable to find graphName", "Wrong number of Parameters 5", "Conv2d failed 3110", "loadRemoteSymbols 4000", "0x80000406", "arm64x", "aarch64", "arch mismatch"]
sources: ["references/context_binary.md", "references/qnn_conversion.md"]
---

# Conversion Troubleshooting (base)

> 🧭 通用诊断骨架（四阶段 + 三铁律 + 反向追溯 + 多层加固）见 [`../_diagnosis-framework.md`](../_diagnosis-framework.md)；本 SKILL 是该总纲在"转换/编译失败"领域的症状库。

## Responsibility

Diagnose and fix failures in the ONNX → C++/bin → DLL → context-binary (`.bin`) chain on WoS ARM64:
graph-name mismatches, missing VS ARM64 environment, missing HTP runtime files, architecture
mismatches, and 0-byte/`bins/` output traps. Root causes here are usually **environment/config**,
not operators — check those first before touching the graph.

## Trigger signals

- `Graph Compose failure` / `unable to find graphName:<x>` / `MODEL_INVALID_ARGUMENT_ERROR`
- `Wrong number of Parameters 5` / `Op specific validation failed` / `Conv2d failed 3110`
- `No CMAKE_C_COMPILER` / `VCTargetsPath.vcxproj` / `BaseOutputPath not set`
- `loadRemoteSymbols failed with err 4000` / `DspTransport.openSession qnn_open failed, 0x80000406`
- `arm64x` vs `aarch64` DLL load errors; host/model architecture mismatch

## Core knowledge

### Structured troubleshooting flow

```
1. Windows ARM → context binary MANDATORY.  Linux ARM → optional (.so works), can skip.
2. Read the error: operator name / code (0xc26) / "unsupported" / "validation failed".
3. If it's an operator → hand off to operator-patching skill.
4. If it's env/config → fix per tables below, re-convert.
5. All patterns exhausted → escalate B7 / B8; consider .dlc or CPU/GPU alternative.
```

### #1 cause of `Graph Compose failure`: graph_names mismatch

`graph_names` in `htp_backend_config_v{73|81}.json` (referenced by `backend_extensions.json`) **must
exactly match** the graph name in the `.dll` (this is a **legacy Flow C** concern; Flow A uses `.dlc` +
`--soc_model` instead of `config_file`, so `graph_names` doesn't apply there). For Flow C: graph name = **stem of `--output_path`** given to
`qnn-onnx-converter` (`output/my_model.cpp` → `"my_model"`).

```
[ERROR] getQnnGraphConfigFromInfo() unable to find graphName:qnn_model ...
[ERROR] ... got MODEL_INVALID_ARGUMENT_ERROR
Graph Compose failure
```
**Fix:** use `--auto-config` (sets graph_names automatically), or set `graph_names` = output_path stem.
Recommendation: use the model name as the output stem for clarity.

### `Wrong number of Parameters 5` / `Conv2d failed 3110` — usually MISSING VS ARM64 ENV

Looks like an operator issue but is almost always the missing ARM64 build environment.
`qnn-context-binary-generator.exe` and `qnn-model-lib-generator` are native ARM64 and need `vcvarsall.bat arm64`.

- **Rule:** run inside a `.bat` that calls `call "%_VCVARSALL%" arm64` at the top. `cmd /c "..."` does **NOT** inherit vcvarsall env.
- For **DLC→bin**, the same error means `QnnHtpV73Stub.dll` or `QnnHtpPrepare.dll` is missing from CWD.
- Only resort to `.cpp` patching if the error persists **after** correct env.

### HTP runtime files must be in the working directory (WoS ARM64)

The generator resolves `.cat` / `Skel.so` relative to its **process CWD**, not PATH. Copy files **and**
run with `cwd=<working_dir>`. `qai_dev_gen_contextbin.py` does both automatically.

- **v73:** `QnnHtp.dll`, `libqnnhtpv73.cat`, `libQnnHtpV73Skel.so`
- **v81:** `QnnHtp.dll`, `QnnHtpV81Stub.dll`, `libqnnhtpv81.cat`, `libQnnHtpV81Skel.so`
- **DLC→bin adds:** `QnnModelDlc.dll`, `QnnHtp*Stub.dll`, `QnnHtpPrepare.dll`, `QnnHtpNetRunExtensions.dll`

**Symptoms when missing:** `loadRemoteSymbols failed with err 4000` / `DspTransport.openSession qnn_open failed, 0x80000406`.
(For DLC→bin, `loadRemoteSymbols 4000` alone is a non-fatal warning, safe to ignore.)

### `arm64x` ≠ `aarch64` (critical DLL rule)

`lib/arm64x-windows-msvc/QnnHtpV81Stub.dll` is an ARM64EC (compat-layer) DLL. The generator is pure
ARM64 and **cannot load arm64x DLLs**. Always copy Stub DLLs from `lib/aarch64-windows-msvc/`.
For v81, `--backend` MUST be `QnnHtp.dll`, NOT `QnnHtpV81Stub.dll` (Stub is a forwarding layer → `Unable to load backend`).

### 0-byte / `bins/` subdirectory trap

Batch-generating multiple models into the **same** `--output_dir` makes the generator create a `bins/`
subdir for the first and leave 0-byte/8-byte placeholders for the rest.
- **Symptom:** `.bin` exists but is 0/8 bytes; real binary is in `bins/`.
- **Fix:** use a dedicated `--output_dir` per model.
- **Always verify** `.bin` size after generation (valid binary is several MB; e.g. Real-ESRGAN x4plus ~30-60 MB).

> ℹ️ `qnn-context-binary-generator.exe` returns non-zero exit code even on success, and emits non-fatal
> `Unknown Key` warnings. Do **not** rely on exit code — check the `.bin` exists and is non-empty.
> `run_pipeline.py`/`qai_dev_gen_contextbin.py` handle this by checking file existence.

### Common Errors Quick Reference (QNN)

| Error | Cause | Fix |
|-------|-------|-----|
| `unable to find graphName` / `MODEL_INVALID_ARGUMENT_ERROR` | graph_names ≠ DLL graph name | `--auto-config`; or graph_names = `--output_path` stem |
| `Graph Compose failure` | config mismatch or unsupported op | check graph_names; check operator support |
| `No CMAKE_C_COMPILER` | VS ARM64 env not initialized | `vcvarsall.bat arm64` in same `.bat` |
| `Unable to load backend: QnnHtp.dll` | DLL not in PATH/working dir | copy `QnnHtp.dll` to working dir |
| `Backend version mismatch` | wrong SDK version's QnnHtp.dll | same SDK version for all steps |
| `Wrong number of Parameters 5` | missing VS ARM64 env (or missing `.cat`/`Skel.so`) | run in `.bat` with vcvarsall arm64; ensure HTP files in CWD; only then patch `.cpp` |
| `VCTargetsPath.vcxproj` / `BaseOutputPath not set` / `Failed to run MSBuild` | `VCTargetsPath` → BuildTools not Community | read `vc_targets_path` from `qairt_env.json`; install VS 2022 **Community**; verify `where.exe MSBuild.exe` |

### Architecture preflight (mandatory, no exceptions)

Do **not** use `platform.machine()` / `$env:PROCESSOR_ARCHITECTURE` (emulation-affected).
Use `(Get-WmiObject Win32_Processor).Architecture` (12=ARM64, 9=x64) or `dumpbin /headers model.dll | find "machine"`.

| OS | Host | Model lib | Action |
|----|------|-----------|--------|
| Linux | x86_64 | aarch64 `.so` | Blocked on host — run on ARM target |
| Linux | aarch64 | aarch64 `.so` | Allowed |
| Windows | ARM64 | ARM64 `.dll` | Allowed |
| Windows | AMD64 | ARM64 `.dll` | Blocked on host — run on ARM target |

Mismatch → **do not run** the generator locally; instruct the user to run on the target device.

### Tool path rules (WoS ARM64, QAIRT 2.45+)

**Legacy Flow C (DLL pipeline) toolchain paths** — the DLC pipeline (Flow A, default) uses `qairt-converter` + `qairt-quantizer` from `bin/<host_arch>/` and skips DLL compilation entirely, so most of this table only matters when the user explicitly runs `run_pipeline_legacy.py`:

| Step | Tool | Arch dir |
|------|------|----------|
| ONNX → C++/bin (Flow C) | `qnn-onnx-converter` | `bin/x86_64-windows-msvc/` (Python, x86 emulation) |
| C++/bin → DLL (Flow C) | `qnn-model-lib-generator` | `bin/aarch64-windows-msvc/` (**NOT x86_64** — most common mistake) |
| DLL/DLC → `.bin` (both flows) | `qnn-context-binary-generator.exe` | `bin/aarch64-windows-msvc/` (native ARM64) |

Prefer wrappers (`run_pipeline.py` for the default DLC path, `run_pipeline_legacy.py` for the DLL path, `qai_dev_gen_contextbin.py --auto-config` for hand-crafted context binaries) — they handle env init, HTP file copy, and arch dirs automatically.

## HTP 硬约束失败根因表（芯片无关子集）

> **用途**：识别哪些 ONNX 构造会在 HTP 编译/上板阶段**硬失败**，提前规避或改写。以下均为芯片无关约束（算子表达 / 图拓扑 / 编译器约束），根植于 HTP 架构与 QAIRT 算子支持，跨芯片可迁移；具体错误码文案可能随 SDK 版本变化。**失败 ≠ 绝对不可转**——多数可经图切分/算子改写/降规模/混合精度绕过。

| 症状（转换/编译日志） | 根因 | 应对 / 规避 |
|---|---|---|
| **`qnn-context-binary-generator failed on HTP`**（转换与量化都过，卡在生成 context binary） | 图整体超出 HTP 编译器可处理规模：某子图无法降到 HTP 指令、或图过大/张量过宽 | ①切分图，把无法编译的子图（常是大后处理头/大注意力块）移出 HTP 放 CPU；②降输入分辨率/序列长度；③排查是否含下方 int32/5D Gather 后针对性改写 |
| **HTP 拒绝 int32 Gather**（转换阶段报错，常见于 embedding lookup / MLM head） | HTP 不接受 int32 索引的 Gather | **上游模型改写**：把 int32-index Gather 改为 HTP 可接受形式（改索引 dtype、one-hot×MatMul 等价、或把 embedding 查表留 CPU 前处理）；改写后重新导出 ONNX 再转 |
| **5D Gather 低效 / 拖垮编译**（不一定报错，但生成极慢或失败） | HTP 对 5D scalar-index Gather 效率极低 | ONNX 侧把 5D scalar-index Gather → **Slice + Squeeze** 等价改写；验 cosine≈1 且编译通过 |
| **`ONNX export: unsupported operator`** | 含 QAIRT/HTP 不支持的算子（常见于 ViT 特殊 attention 原语、动态构造算子） | ①等价可支持算子重写子图；②不支持子图切出放 CPU；③调整 opset 让算子以标准形式表达 |
| **`qairt-converter error`**（图无法转成 DLC） | ONNX 图结构/属性不被接受（非标准子图、动态 shape 依赖、SSD 特殊 anchor 构造） | 规范化 ONNX（固定 shape、shape_inference、消除动态构造）；无法转的后处理子图切出 |
| **`qnn-net-run failed on device`**（转换编译都过，上板运行时失败） | 编译产物在设备上执行失败（运行时资源/算子实现缺陷或图对设备不友好） | ①按 State-Truth-First 从 `.bin` 元数据反查真实 I/O 契约再核对输入；②切分图定位崩溃子图；③降规模复现 |
| **`Export/convert timeout or hang`** | 图规模过大 / 动态循环 / 巨型注意力或分割解码，导出/转换不收敛 | ①降输入尺寸/序列长度；②切分为多子图分别转换；③固定动态 shape 消除动态展开；④分割/SAM 类大解码头考虑只转编码器 |

### 转换前 HTP 友好改写规则（预处理，从源头避免上表失败）

每条改写后**必须验证输出 cosine≈1.0**（数学恒等改写），否则回退：

| 改写 | 内容 | 规避的硬约束 |
|---|---|---|
| **5D Gather → Slice + Squeeze** | 5D scalar-index Gather 等价替换 | 直接规避"5D Gather 低效" |
| **Slice(step=-1) → 固定索引 Gather** | 反向切片改为固定索引 Gather | HTP 对固定索引 Gather 更高效 |
| **Slice 常量折叠** | `Shape→Gather→Div` 动态 ends 在输入 shape 固定时折叠为常量 | 消除动态 shape，减少 converter 报错/超时诱因 |
| **Where→Add**（attention mask） | `Where(Equal(mask,0),-1e4,s)` → `(s+1e4)*mask-1e4` | 消除 HTP 上昂贵/易失败的 Where，降低大注意力图编译失败风险 |

> **配套纪律**（防"改写反而变差"）：①不要改写 qairt 已能内部融合的模式；②减少算子数 ≠ 更易编译；③MHA→SHA 拆分引入的 Slice/Concat 开销常超收益；④只 patch 共享权重的部分 MatMul 会破坏数值正确性。每次改写以"cosine≈1 且编译/上板通过"为唯一验收标准。

### 转换前硬约束自检清单

1. **有 int32-index 的 Gather（embedding/词表查表）吗？** → HTP 会拒，上游改写或把查表留 CPU。
2. **有 5D scalar-index Gather 吗？** → 预先改成 Slice+Squeeze。
3. **有动态 shape（Shape→Gather→Div 算 ends）吗？** → 固定输入 shape + 常量折叠。
4. **图很大 / 含巨型注意力或分割解码 / SAM 类大解码头吗？** → 预判 context-binary 失败或超时，提前规划切图。
5. **有检测/分割后处理头（NMS/anchor decode/grid/mask 组装）吗？** → 切出放 CPU（也是精度必需，见 `${APP_ROOT}/factory/chat_features/model-builder/references/quantization-sensitivity.md`）。
6. **有非标准 attention 原语或 SSD 特殊 anchor 构造吗？** → 预判 unsupported-op / converter error，等价重写或切出。

> **一句话记忆**：*int32 Gather 必被拒→上游改写；5D Gather 先拆 Slice+Squeeze；动态 shape 先固定；大图/大解码头先切图防 context-binary 失败与超时；检测/分割后处理一律切出 CPU。*

## Related Blocking Conditions

- **B8** — context binary generation fails on Windows ARM. Return to operator patching; do not silently degrade to `.dll`; do not retry x86_64 generator on an ARM64 DLL. (See `sdk-integrity-recovery` skill for 0-byte generator self-heal.)
- **B5** — target device unavailable for generation/testing → stop, ask user.

## Escalation path

Escalate when: same failure persists after env fix + patch + retry; converter fails on a required op with no rewrite; runtime rejects the graph post-conversion. Bundle: original + patched ONNX, conversion command, dry-run log, conversion log, minimal repro steps.

Full commands, backend config JSON, and `--soc_model` table → `references/context_binary.md` and `references/qnn_conversion.md`.
