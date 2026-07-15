---
skill_id: export-troubleshooting
tier: base
triggers: ["ModuleNotFoundError functional_tensor", "basicsr", "ReshapeOp::calculateShape", "aux 分支", "training-only 分支"]
sources: ["references/model_export_validation.md"]
---

# Export Troubleshooting (base)

> 🧭 通用诊断骨架（四阶段 + 三铁律 + 反向追溯 + 多层加固）见 [`../_diagnosis-framework.md`](../_diagnosis-framework.md)；本 SKILL 是该总纲在"ONNX 导出期兼容"领域的症状库。

## Responsibility

Fix failures that occur while exporting a PyTorch model to ONNX (before QNN conversion): the
`basicsr` / `functional_tensor` import error, and conversion failures caused by training-only
branches (auxiliary classifiers) that emit dynamic-shape operators QAIRT 2.45 cannot convert
(`ReshapeOp::calculateShape`). Fixes are in-memory / source-adjacent only — never break reproducibility.

## Trigger signals

- `ModuleNotFoundError: No module named 'torchvision.transforms.functional_tensor'` (common with `basicsr`-dependent models, e.g. Real-ESRGAN)
- `ValueError: modeltools::ops::ReshapeOp::calculateShape: Unable to calculate ReshapeOp output shape ... shape params dont result in same cumulative total sum` with a garbage value (e.g. `89401 != -1104974904`)
- A model has aux / training-only branches

## Core knowledge

### `basicsr` → `torchvision.transforms.functional_tensor` import error

`basicsr/data/degradations.py:8` hard-imports `functional_tensor`, removed in torchvision ≥0.16.
Patch that one line to support both paths:
```python
try:
    from torchvision.transforms.functional_tensor import rgb_to_grayscale
except ImportError:
    from torchvision.transforms.functional import rgb_to_grayscale
```

### Auxiliary / training-only branches → `ReshapeOp::calculateShape`

Some models have aux classifier branches used only in training. They often contain ops (`Gather`,
`Reshape` with dynamic shapes) that QAIRT 2.45 `qnn-onnx-converter` cannot handle. The garbage value
(e.g. `-1104974904`) indicates an unresolved dynamic shape.

**Fix — disable training-only branches before export:**
```python
model = SomeModel(weights=SomeModel_Weights.DEFAULT)
if hasattr(model, 'aux_logits'):
    model.aux_logits = False   # disable aux branch flag
if hasattr(model, 'AuxLogits'):
    model.AuxLogits = None     # remove aux classifier module
model.eval()
torch.onnx.export(model, dummy_input, "model.onnx", opset_version=18)
```
> ⚠️ Some constructors enforce `aux_logits=True` when loading pretrained weights — set the attribute
> **after** loading, not via the constructor argument.

**Other training-only branches to check:** always call `model.eval()` before export (disables Dropout, freezes BatchNorm running stats); verify the eval path of any custom `forward()` with `if self.training:` branches.

### Related export hygiene (avoids downstream conversion failures)

- **Always export FP32** (never FP16) — `qnn-onnx-converter` expects FP32; PyTorch CPU has no FP16 `Conv2d`. FP16 is applied later via `--precision 16` in QAIRT.
- **Always `opset_version=18`** for torch 2.x (lower auto-upgrades; downgrade fails on `Resize` etc.). Also `pip install onnxscript`.
- `do_constant_folding=False` — the converter does its own folding; True can add 15-30 min / OOM on large models.
- torch 2.x splits large models into `<model>.onnx` + `<model>.onnx.data` — **both must stay in the same dir**; pass the `.onnx` path (converter finds `.data`). A small `.onnx` is normal — check for the sibling `.onnx.data` before running diagnostics.

### Validation after export (mandatory, especially after patching)

Compare the ONNX output against the original PyTorch output on the same preprocessed input (`onnxruntime` with **`CPUExecutionProvider` only** — allowed as a CPU baseline). Small numerical differences are common; confirm acceptability with the user. For CV tasks also do a task-specific check (annotated-image visual compare + bbox/label/score compare) — patches can introduce off-by-one / axis errors that raw numerics miss.

## Related Blocking Conditions

- **B4** — if disabling a branch or applying an operator patch changes model semantics, stop and ask the user to approve.
- Unsupported operators surfaced during export/conversion → hand off to the `operator-patching` skill (B3/B4/B7 apply there).

## Escalation path

If disabling training-only branches does not resolve `ReshapeOp::calculateShape` and the offending op cannot be patched to supported ops, or the export-vs-original validation fails and the numerical difference is not clearly acceptable → stop and report to the user (B4 / hand off to operator-patching for B7).

Full export performance rules, optimized template, and validation workflow → `references/model_export_validation.md`.
