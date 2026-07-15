---
skill_id: operator-patching
tier: base
triggers: ["unsupported operator", "0xc26 Op validation failed", "Einsum", "Mod", "Floor", "ScatterND", "GridSample", "dry-run flags op"]
sources: ["references/operator_patching.md", "SKILL.md Step 3"]
---

# Operator Patching (base)

> 🧭 通用诊断骨架（四阶段 + 三铁律 + 反向追溯 + 多层加固）见 [`../_diagnosis-framework.md`](../_diagnosis-framework.md)；本 SKILL 是该总纲在"算子不支持/替换"领域的症状库。

## Responsibility

Replace unsupported operators (`Einsum`, `GridSample`, `ScatterND`, `Mod`, `Floor`, `Ceil`, `Round`)
with QNN/SNPE-compatible equivalents built from supported base ops (`MatMul`, `Reshape`, `Transpose`,
`Concat`, `Div`, `Mul`, `Sub`, `Where`, `Add`), **in-memory only** — never edit library source code.
Patch at whatever stage fails: ONNX export, converter dry-run, FP conversion, context binary, or inference.

## Trigger signals

- Converter/context-binary error mentioning an operator name + `unsupported` / `not implemented`
- Error code `0xc26 Op validation failed` on a specific node
- Dry-run flags an op in its unsupported table (`--dry_run`)
- Context binary compile fails `Failed to compile layer 'Einsum_123'`

## Core knowledge

### RULE 1 — check input TYPES before choosing a pattern

The same op (`Mod`) needs a completely different patch for INT vs FLOAT inputs. Wrong type = #1 failure cause.
Determine types from the **producer node**:

| Producer | Output type |
|----------|-------------|
| TopK (indices) | INT64 |
| Constant dims=[] data_type=7 / =1 | INT64 / FLOAT32 scalar |
| Conv / MatMul / Gemm | FLOAT32 |
| Softmax / Sigmoid / Relu | FLOAT32 |
| Reshape / Transpose | inherits input |

Inspect with Netron or:
```python
import onnx
m = onnx.load("model.onnx")
for n in m.graph.node:
    if n.op_type == "Mod":
        print(n.name, list(n.input), list(n.output))
```

### Approach selection decision tree

```
Can you modify the PyTorch export code?
├─ YES → Approach 1: Custom Symbolic Handlers (register before torch.onnx.export)
│        Best for torch.mod / torch.einsum / custom aten ops. Highest success (clean graph).
└─ NO  → Is the op a known nn.Module?
         ├─ YES → Approach 2: Module Replacement (patch module.forward in-memory). High success.
         └─ NO  → Approach 3: ONNX Surgery (direct graph edit). Last resort; topo-sort / drift risk.
```
Always prefer Approach 1.

### Error -> Action quick table (type-aware)

| Op | Input types | Action | Success |
|----|-------------|--------|---------|
| **Mod** | INT/INT | `Sub(a, Mul(b, Div(a,b)))` — all INT, no Cast (INT div truncates = floor for +) | ★★★★★ |
| **Mod** | FLOAT/FLOAT | `Sub(a, Mul(b, Floor(Div(a,b))))` — ⚠️ Floor may also fail | ★★ |
| **Mod** | FLOAT/CONST(int) | `Div→Cast(INT)→Cast(FLOAT)→Mul(b)→Sub(a)`; add `Add(0.0)` after final Cast to break type chain | ★★ |
| **Floor** | INT | Remove — Floor of int is itself → Identity / rewire | ★★★★★ |
| **Floor** | FLOAT | `Cast(x,INT32)→Cast(FLOAT)` — ⚠️ downstream type issues | ★★ |
| **Ceil** | FLOAT | `Neg(Floor(Neg(x)))` | ★★ |
| **Round** | FLOAT | `Floor(Add(x,0.5))` | ★★ |
| **Cast** | `Only numerical type cast supported` | **WARNING not error** — verify with actual conversion | Warn |
| **Cast** | `Tensor mismatch 0x32 != 0x216` | Add `Add(0.0)` after Cast: `Cast→Add(0.0)→Mul` | — |
| **Einsum** | FLOAT | Decompose to MatMul+Transpose+Reshape (see 5 patterns) | ★★★★ |
| **ScatterND** | non-overlapping idx | `Gather→Where(mask)→Add(updates)` | ★★★★ |
| **ScatterND** | overlapping idx | loop/custom op → escalate **B7** | ★ |
| **GridSample** | bilinear | AffineGrid + Resize(bilinear) | ★★ |
| **GridSample** | nearest/bicubic | complex → consider arch change | ★ |
| **MaxPool** | `dilations: unsupported` / `unsupported version` | **WARNING** — actual conversion succeeds (exit 0). **Do NOT patch.** | ★★★★★ |
| **MaxPool** | dilation>1 | may fail actual conv → `Slice+Stack+ReduceMax` (last resort, +size, FP16 loss) | ★★★ |
| Any other unknown op | no known pattern | escalate **B7** (document op name, types, attempts) | — |

> **MaxPool insight:** PyTorch ONNX export always adds `dilations=[1,1]`/`ceil_mode=0`. Dry-run flags it
> as a warning but FP16 conversion, context binary, and HTP inference all succeed. Don't waste time patching.

### Einsum — 5 decomposition patterns

Einsum = batched MatMul with dim rearrangement. Expose the MatMul by permute+reshape.

- **A. 5D attention** `bmchw,bnmc->bmhwn` (YOLO-World MaxSigmoidAttnBlock): permute embed→`[b*m,h*w,c]`, guide→`[b*m,c,n]`, MatMul→`[b*m,h*w,n]`, reshape→`[b,m,h,w,n]`.
- **B. 4D contrastive head** `bchw,bkc->bkhw` (BNContrastiveHead): x→`[b,h*w,c]`, w.transpose→`[b,c,k]`, MatMul→`[b,h*w,k]`, permute+reshape→`[b,k,h,w]`.
- **C. simple batched** `bij,bjk->bik` → `torch.matmul(A,B)` directly.
- **D. multi-batch** `bhij,bhjk->bhik` → merge `[b*h,i,j]@[b*h,j,k]` then reshape back.
- **General algo:** shared indices = reduced dims; batch indices stay; reshape to merge batch + reduced → MatMul → reshape back to batch structure.

## Validation — Mandatory Gates (run ALL after EACH patch)

| Gate | Check | Pass criteria |
|------|-------|---------------|
| **1 Structural** | `onnx.checker.check_model()` | no exception, well-formed, consistent types |
| **2 Converter** | `qnn-onnx-converter --dry_run` (or `qairt-converter`) | "ops evaluated", no unsupported errors |
| **3 Numerical** | run orig vs patched ONNX on same input (CPUExecutionProvider) | shapes match, cosine ≥ 0.95, no NaN/Inf |
| **4 Full conversion** (final only) | `python qai_convert_fp.py --onnx ...` | "Conversion complete!", `.bin/.cpp/.json` |

**Cosine interpretation (Gate 3):** ≥0.999 correct · 0.99–0.999 minor drift OK · 0.95–0.99 investigate (may be OK for INT8) · <0.95 patch incorrect, try next pattern.

**Decision matrix:** Gate1 fail → check topo order/tensor names. Gate2 fail → more patching (Floor/Cast may add new unsupported ops). Gate3 fail → wrong pattern/type mismatch, try next row. Gate4 fail → add `Add(0.0)` after Cast to break type inference.

> ⚠️ Einsum patches can silently change numerics if dims misalign. Validate **all output channels**,
> not just top-1 (a patch OK for `person` may fail for `bus` in a contrastive head).

## Discipline — NEVER use CPU runtime as workaround

| ❌ Not allowed | ✅ Required |
|---------------|-------------|
| CPU fallback for unsupported ops | Patch ops for HTP/DSP compatibility |
| `QnnCpu.dll` context binary as "solution" | HTP-compatible operator decomposition |
| Skip patching, run on CPU only | Model MUST run on target accelerator (HTP/DSP) |

Target is a Qualcomm AI PC with HTP; CPU-only defeats the purpose. If you can't patch for HTP → escalate B7, do not silently fall back to CPU.

Other discipline: patch in-memory only; validate after every patch (dry-run alone is not enough); don't over-patch (if dry-run passes, stop — extra patches add numerical drift); inspect first, patch only the unsupported ops.

## Escalation path (stop and report to user)

| Condition | Code | Evidence |
|-----------|------|----------|
| No replacement pattern exists for the op | **B7** | op name, input types, literature search |
| Patch changes model semantics | **B4** | describe semantic change, accuracy impact; await approval |
| 7+ iterations, same ops still failing, no progress | **B3** | attempted patches, dry-run logs, ONNX snapshot |

Progress rule (iteration 5+): resolving ops faster than discovering new ones → continue; new ops appearing faster → escalate early.

Full patterns, code templates and per-op surgery → `references/operator_patching.md`.
