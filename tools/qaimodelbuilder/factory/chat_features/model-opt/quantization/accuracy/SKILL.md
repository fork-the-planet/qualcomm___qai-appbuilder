---
skill_id: quantization-accuracy
tier: base
triggers: ["cosine < 0.95", "cosine < threshold", "精度掉", "通道全 0", "Large-Dynamic-Range", "校准数据", "B6"]
sources: ["SKILL.md B6+Step8", "references/model_quantization.md", "references/inference.md checklist"]
---

# Quantization Accuracy (base)

## Responsibility

Handle the accuracy validation step (ONNX-vs-QNN cosine) and quantization accuracy loss: run the
mandatory baseline comparison, correctly diagnose low cosine (calibration diversity, large-dynamic-range
channel collapse), and — critically — **NOT auto-apply fixes**: diagnose at zero cost, then STOP and
present options to the user (B6). Inference on the NPU goes through `qai_appbuilder`; the ONNX baseline
uses `CPUExecutionProvider` only and MUST run in a **separate process** from QNN.

## Trigger signals

- Cosine (ONNX vs QNN/SNPE) < 0.99 (FP16/FP32) or < 0.95 (INT8/A16W8/W8A8) → **B6**
- Certain output channels are constantly all-zero after W8A8, yet overall cosine looks fine
- Calibration data is a single image / its augmentations
- User reports "accuracy dropped" after quantization

## Core knowledge

### Mandatory baseline comparison (Phase 6)

Must run in batch mode — do NOT stop after inference succeeds.
1. Run ONNX inference on the same input as the QNN run — `onnxruntime` with **`CPUExecutionProvider` only** (never route the baseline onto the NPU; run it in a **separate process** because `qai_runner.py` hot-swaps `sys.modules["onnxruntime"]` process-wide).
2. Reuse the QNN output from the inference step.
3. Compute cosine:
   ```python
   cosine = np.dot(onnx_out.flatten(), qnn_out.flatten()) / (np.linalg.norm(onnx_out) * np.linalg.norm(qnn_out))
   ```
4. Threshold: **≥ 0.99** (FP16/FP32) or **≥ 0.95** (INT8/A16W8).

`REPORT.md` must contain a plain-text line per variant: `Cosine Similarity (ONNX vs FP16): 0.999988` (value a decimal, not `%`; variant one of FP16/FP32/INT8/W8A8/W8A16/W4A16/W4A8/W8A8B8/A16W8; always include the FP16 line). Missing this format triggers a Pack validation warning.

### If cosine < threshold → B6 (do NOT auto-apply fixes)

**(a) Zero-cost diagnosis first:** check whether calibration data came from a single image / its
augmentations — a common root cause (augmentations of ONE image are NOT diverse). **(b) Then STOP and
report to the user:** state measured cosine + diagnosis, present the options **with a one-line principle
each**, and ask which to try. Wait for the choice.

| # | Option | Principle |
|---|--------|-----------|
| 1 | Improve calibration diversity (real multi-class samples) | quantizer estimates each layer's activation range from calibration data; diverse data → accurate ranges |
| 2 | `qairt-quantizer --algorithms cle` | Cross-Layer Equalization rescales weights across adjacent layers so per-channel ranges are more uniform (esp. MobileNet/EfficientNet). **Switches to Flow C** → then context binary via `qai_dev_gen_contextbin.py --model <file>.dlc`, **NOT** `run_pipeline.py`/`qai_convert_int.py` (they only accept ONNX) |
| 3 | Raise to W8A16 (`--precision w8a16`) | 16-bit activations preserve more dynamic range than 8-bit, at some size/latency cost |
| 4 | Keep FP16 (skip quantization) | highest accuracy; no size/speed benefit |
| 5 | Accept current precision | if Top-1/Top-K is already correct for the use case |

### Large-Dynamic-Range trap — cosine can lie

**Symptom:** after W8A8 certain output channels are constantly all-zero (e.g. class-score channels of a
detector), yet overall cosine is still >0.999 — looks fine but is broken.
**Root cause:** QNN uses **one shared scale** per output tensor. When a tensor mixes large-magnitude
channels (bbox coords 0~640) with small-magnitude channels (class score 0~1), the scale is dominated by
the large values; small values fall below quant resolution and truncate to 0. Overall cosine is dominated
by the large-value channels' L2 norm, masking the failure.
**Diagnosis:** do NOT look at overall cosine alone — **verify min/max + cosine per channel / per sub-task**
(compute separately for bbox channels vs class channels).
**Solutions (priority):** ① W8A16 (16-bit acts leave precision for small values); ② more multi-class calibration samples (≥50, all classes); ③ per-channel quantization of the output.

### Tool comparison & CLE

`qairt-quantizer` (ONNX→FP32 DLC→W8A8 DLC→bin) gives marginally higher cosine than `qnn-onnx-converter`
(0.9351 vs 0.9297 on Inception-V3 W8A8; both within acceptable range). If below 0.95, `--algorithms cle`
on `qairt-quantizer` (`--param_quantizer tf --act_quantizer tf --act_bitwidth 8 --weights_bitwidth 8 --algorithms cle`).
Do NOT silently switch to CLE — it's one option among several; check calibration diversity first, then let the user choose (B6).

### 更强量化武器（内部）：GPTQ / SeqMSE + 叠加互斥警示 (tier: advanced)

除 CLE 外，还有更强的**权重量化**武器：

- **GPTQ**：比 CLE 更强的权重量化，直接调整权重数值以补偿量化误差。实测显著降低量化精度损失，且改善会**传导放大到设备端**（host 改善被放大到 device，传导比可 > 1.9）。
- **SeqMSE**：逐层搜索使量化误差 MSE 最小的 weight scale/zp。

**🔴 GPTQ 与 SeqMSE 叠加互斥（核心警示）**：在 GPTQ-tuned 权重上再跑 SeqMSE 会崩。机制：`apply_seq_mse(...)` 假设权重是 raw FP 范围会重搜 scale/zp，但 GPTQ 已改过权重范围 → 重搜出的 encodings 与调整后权重严重不匹配 → 输出 garbage（复读输入 / 死循环 / 乱码）。**正确做法（二选一，不叠加）**：用 GPTQ 时跳过 SeqMSE（默认 compute_encodings 只校准 activation、不动权重 encodings，保持 GPTQ 权重关系）；或只用 SeqMSE（不上 GPTQ）走原始权重路径。

**两类精度杠杆要分清**：针对"权重量化质量"的杠杆（GPTQ / 敏感层升 W8 混精度）→ 有效且传导到设备；针对"激活/累加器精度"的杠杆（激活位宽 / clip 等）→ 对某些"定点累加器固有 gap"无效。先判断你要修的是权重质量还是激活/累加器问题，再选杠杆。

### 更深诊断 & 更精细方案（tier: advanced，仅内部）

B6 的 5 个粗档选项之后，若需更深的诊断或更精细的方案，路由到以下子 SKILL（external 版物理无此目录 → 静默跳过）：

| 场景 / 症状 | 加载子 SKILL | 路径 |
|---|---|---|
| 不确定该不该 clip 离群值 / cosine 掉但 SQNR 好看 | worth-clip-analyzer（C1） | `${APP_ROOT}/factory/chat_features/model-opt/quantization/accuracy/worth-clip/SKILL.md` |
| 参考仿真过、设备不过 / worst 层已定位需图拓扑深挖 narrow point | narrow-point-localization（C3） | `${APP_ROOT}/factory/chat_features/model-opt/quantization/accuracy/narrow-point/SKILL.md` |
| 想只把敏感几层保 FP16、其余 INT8 / 局部精度回退落地 | mixed-precision（C5） | `${APP_ROOT}/factory/chat_features/model-opt/quantization/mixed-precision/SKILL.md` |
| 深层残差网络量化后累积 outlier / weight-only 正常但全量化崩 | residual-outlier（C8） | `${APP_ROOT}/factory/chat_features/model-opt/quantization/accuracy/residual-outlier/SKILL.md` |
| 精度掉且某通道输出 cos ≈ −1（符号翻转）= per-channel INT16 bias 溢出 | bias-split pattern（C2） | `${APP_ROOT}/factory/chat_features/model-opt/graph/patterns/Extended/Equi_Subst/O_Bias_Split_Overflow_Guard_Skill.md` |

### When accuracy diagnosis needs a graph rewrite（精度诊断触发图改写）

`quantization/accuracy` 是所有精度问题的入口，但并不是所有精度问题都只能靠校准数据、CLE、W8A16、FP16 fallback 或混合精度解决。少数问题的根因是**量化/后端执行中的数值正确性风险**，需要用 ONNX 图等价改写来规避。此时不要把 graph 当作新的入口，而是遵循：

```text
精度异常 → quantization/accuracy 诊断 → 命中特定数值根因 → 引用 graph/patterns 中的精度修复型 pattern
```

当前已知的交叉路由：

| 诊断信号 | 判断要点 | 路由到 graph pattern |
|---|---|---|
| 某通道输出 cosine ≈ −1 / 符号翻转 / 设备端与参考仿真明显不一致 | 常见根因是 per-channel INT16 bias 溢出；需要先定位到具体层/通道，确认不是校准数据多样性或 Large-Dynamic-Range 输出量化导致 | `graph/patterns/Extended/Equi_Subst/O_Bias_Split_Overflow_Guard_Skill.md` |

使用原则：

- **单源原则**：完整图改写方法、等价条件和实现细节保留在 `graph/patterns`；本 accuracy SKILL 只负责诊断入口和路由。
- **先诊断再改写**：不要因为 cosine 低就直接套 graph pattern；必须先完成 B6 零成本诊断、per-channel/分任务检查、必要的 worst-layer 定位。
- **仍需用户确认**：命中特定数值根因后，向用户解释“这是数值正确性修复型图改写，不是常规提速优化”，再等待用户选择是否执行。
- **验证标准不变**：图改写后仍需重新做 ONNX/QNN 对齐、per-channel 检查和任务级输出检查；不能只看整体 cosine。

### Calibration Data Acquisition

When calibration data is absent, ask the user via the `question` tool before acting — do NOT silently
download or fabricate. Offer 3 options: (1) user provides real dataset (preferred); (2) Agent auto-prepares
(offline first: project `samples\images\`, then `${WORKSPACE}\`, then user-given path — capped count, early
stop; web download only if too few; **never recursive `**`/whole-disk/home-dir globs** — has caused 30+ min
hangs); (3) synthetic/random (pipeline bring-up only; if cosine < 0.95 re-quantize with real data).

Synthetic recipe (bring-up only): N float32 `.raw` files matching input shape, scale `np.random.normal(0,1,...)` per channel by ImageNet mean/std (`x[c]=x[c]*std[c]+mean[c]`, mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]).

### Acceptable thresholds

| Metric | FP16/FP32 | INT8/A16W8 |
|--------|-----------|------------|
| Cosine | ≥ 0.99 | ≥ 0.95 |
| MSE | < 1e-4 (task-dependent) | task-dependent |

For CV, also compare high-level outputs (bbox/label/score) — if detections match, minor MSE is usually safe.

## Related Blocking Conditions

- **B6** — accuracy drops below threshold after quantization (cosine < 0.95). Run zero-cost diagnosis, then STOP and present options with principles; wait for the user's choice. Never auto-apply fixes in sequence. For detection models with mixed-magnitude outputs, also check per-channel (Large-Dynamic-Range).

## Escalation path

Always stop at B6 — accuracy fixes are user decisions. Also stop if calibration data is absent (ask via `question`) or if per-channel diagnosis reveals channel collapse hidden by a high overall cosine (report it explicitly rather than passing the model as "good").

Full quantization commands, tool comparison, and calibration acquisition detail → `references/model_quantization.md`; validation checklist → `references/inference.md`.
