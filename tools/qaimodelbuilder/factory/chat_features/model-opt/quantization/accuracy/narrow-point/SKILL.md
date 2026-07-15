---
skill_id: narrow-point-localization
tier: advanced
triggers:
  - "参考仿真 cosine 高但设备 HTP cosine 低"
  - "worst-cosine 层已定位需图拓扑深挖 / narrow point"
  - "分不清根因层 vs 下游受害层"
  - "FP16 回退打了反而 regress / 崩"
sources: ["内部 QNN/HTP 工程实践整理"]
---

# Narrow-Point Layer-wise Localization（图拓扑感知的塌缩点定位）

> **知识定位**：当"CPU/参考仿真 cosine 高、但设备 HTP cosine 低"时，用**图拓扑感知**的 6 步法精准定位是哪个 tensor 塌缩（不是笼统按 MSE 排名），只在 narrow point 做最小 FP16 回退。
> **抽取内核**：worst-N cosine 排序 → ONNX 反向 trace producer 链 → unique-value 塌缩比 < 0.3 判定 **narrow point** → 最小 FP16 回退；含 **Step 0.5 encoding 一致性对拍**（先排除工具链静默改写 scale/bitwidth，再谈 HTP 算子融合）。
> **剥离外壳**：某 LLM 优化流水线的具体融合链/KV-cache/模型层号移除；融合表里非 LLM 专属的 GELU/LayerNorm/SiLU/Softmax 行保留为通用算子融合参考。
> **适用小模型的理由**："参考过、设备不过"是任意量化模型上板的通用现象，根因常是 HTP O3 把一串 ONNX 算子融成一个 kernel、中间某 tensor 被压成 INT16 narrow。方法对任何含 LayerNorm/Softmax/GELU/Sigmoid 融合链的 CNN/小 transformer 都适用。

---

## 1. 何时用

- 参考仿真（PyTorch QSIM 或 CPU `qnn-net-run`）cosine ≥ 0.97，但 **HTP 设备 cosine ≤ 0.95**（同一输入）；
- 已有 worst-layer 排名但分不清"根因层 vs 下游受害层"；
- 之前的 FP16 回退尝试反而 regress 或崩溃（回退打在了错误的 tensor 上）。

**不适用**：HTP 完全跑不起来（走 runtime error 分析）；最终 cosine 已 > 0.99；模型没有任何融合链候选（纯单算子网络如无 LayerNorm 的 ResNet）。

## 2. 前置产物（缺则先补齐）

| 产物 | 用途 |
|---|---|
| `<model>.onnx`（量化前） | Step 2 拓扑 trace |
| `<model>.encodings` | 知道哪些 tensor 是 INT16 vs FP |
| 参考仿真中间 dump（一个输入） | 参考值 |
| HTP 设备 debug dump（同一输入） | 测试值 |

## 3. 六步法

### Step 0：对齐性检查

参考 dump 与 HTP dump 文件名必须一致（同输入、同 tensor 名）。

```bash
ls ref_dump/Result_0/ | sort > /tmp/ref_names.txt
ls htp_dump/Result_0/ | sort > /tmp/htp_names.txt
diff /tmp/ref_names.txt /tmp/htp_names.txt | head -20   # 期望为空
```

名字不一致常见于 HTP 把 `/x/y/z_output_0` 重命名为 `_x_y_z_output_0`，比对前先归一化。

### Step 0.5：Encoding 一致性对拍（先排除工具链静默改写）——关键

**为什么这步存在**：在假设"HTP 融合是元凶"之前，必须排除更简单的假设——"Step2 工具链（converter/quantizer）在生成 DLC 时静默改了某些 tensor 的 scale/offset/bitwidth。"如果 Step1（量化仿真产出的 encodings）与 Step2（DLC 实际消费的 encodings）不一致，再多融合分析也解释不了 gap，因为**设备跑的模型和仿真评估的模型在数学上就不是同一个**。这是**标准的替代假设检验，在 Step 1 之前做。**

**0.5a — 把 Step2 DLC dump 回 JSON**（拿到 HTP backend 实际消费的每个 tensor 量化参数）：

```bash
qairt-dlc-to-json --input_dlc model_quantized.dlc --output_json dlc_dump.json
# 某些 SDK 版本等价命令是 qairt-dlc-info --dump-encodings，查你的 SDK release notes
```

**0.5b — diff Step1 encodings vs Step2 DLC encodings**：

```python
import json, sys
step1 = json.load(open(sys.argv[1]))   # Step1 <model>.encodings
step2 = json.load(open(sys.argv[2]))   # qairt-dlc-to-json 输出

def normalize(enc):
    out = {}
    ae = enc.get("activation_encodings", {})
    for name, lst in ae.items():
        if not isinstance(lst, list) or not lst: continue
        e = lst[0]
        out[name] = {"bw": e.get("bitwidth"),
                     "scale": round(float(e.get("scale", 0)), 8),
                     "offset": int(e.get("offset", 0)),
                     "is_sym": bool(e.get("is_symmetric", False)),
                     "dtype": e.get("dtype", "int")}
    return out

a, b = normalize(step1), normalize(step2)
common = sorted(set(a) & set(b))
mismatch = [(n, a[n], b[n]) for n in common if a[n] != b[n]]
print(f"Step1 only: {len(set(a)-set(b))}  Step2 only: {len(set(b)-set(a))}  "
      f"common: {len(common)}  mismatched: {len(mismatch)}")
for name, av, bv in mismatch[:20]:
    print(f"  {name}\n    Step1: {av}\n    Step2: {bv}")
```

**0.5c — 判定规则**：

| 不一致数 | 结论 | 下一步 |
|---|---|---|
| 0（bit-perfect） | 工具链忠实 → 根因在 HTP runtime 侧（融合/近似） | 进入 Step 1 |
| 1–10，且全在 `bias_encodings` | 某些 SDK 版本 bias requant 正常 | 进入 Step 1（记一笔） |
| 任何 activation 的 `bw`/`is_sym`/`dtype` 不同 | **工具链改写了量化** → **停止融合分析** | 走 0.5d 分诊 |
| 多个 activation 的 `scale` 略不同（< 1%） | JSON 序列化浮点往返 | 忽略，继续 |
| `scale` 差 > 1% | 工具链重新校准了 | 停止，分诊 |

**0.5d — 工具链改写分诊**（若 0.5c 判 STOP）：

| mismatch 里的模式 | 可能原因 | 修法 |
|---|---|---|
| `is_sym` True↔False 翻转（在 norm 类 tensor 上） | converter 对 unsigned-friendly 算子的 sym→asym 提升 | 用 `--quantization_overrides` 锁 encoding |
| `bw` 16→8（activation 上） | Step1/Step2 的 `--act_bitwidth` 不一致 | 对齐 flag，核对 Step2 命令 |
| `dtype` float→int | Step1 标了 FP16 但 Step2 忽略 override | 确认 override JSON 正确传入 |
| `offset` 0→非 0（权重上） | per-channel/LPBQ block 被静默禁用 | 检查 `--use_per_channel_quantization`（offset 必须保持 0） |
| tensor 在 Step1 有、Step2 无 | converter 层 fold/fuse（Clip→Relu、BN→Conv） | 数学无损则接受，否则报 SDK bug |
| tensor 在 Step2 有、Step1 无 | converter 插了 Convert/Reshape/Transpose | 可接受，忽略 |

确认真有改写就**先修 Step2**（改对 flag 或 override 重跑），重做 0.5 直到 0 mismatch，再进 Step 1。

> **即使 0.5 全清也要记一笔**"工具链已排除"，让后来者知道这个假设已被否掉。

### Step 1：Worst-N cosine 排序

```python
import os, numpy as np, json
REF_DIR, HTP_DIR, TOP_N = "ref_dump/Result_0", "htp_dump/Result_0", 10

def cos(a, b):
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a.dot(b) / n) if n > 1e-10 else float("nan")

results = []
for fn in sorted(set(os.listdir(REF_DIR)) & set(os.listdir(HTP_DIR))):
    if not fn.endswith(".raw"): continue
    a = np.fromfile(f"{REF_DIR}/{fn}", dtype=np.float32).flatten()
    b = np.fromfile(f"{HTP_DIR}/{fn}",  dtype=np.float32).flatten()
    if a.size != b.size or a.size == 0: continue
    results.append((fn, cos(a, b), a.size))
results.sort(key=lambda r: r[1])           # 升序 = 最差在前
for fn, c, sz in results[:TOP_N]:
    print(f"{fn:<60} {c:>10.4f} {sz:>10}")
json.dump([{"tensor": r[0], "cosine": r[1]} for r in results[:TOP_N]],
          open("/tmp/worst_layers.json", "w"), indent=2)
```

解读：worst 层聚在同一深度 → 那条链是元凶；分散在多类型算子（Cast/Mul/Add）→ 可能一个融合 pattern 多个实例；毫无规律的随机散布 → 不是融合，去查量化范围/clip。

### Step 2：ONNX 反向 trace producer 链

```python
import onnx, json, sys
model = onnx.load(sys.argv[1]); worst = json.load(open(sys.argv[2])); DEPTH = 12
producer = {out: n for n in model.graph.node for out in n.output}

def trace(start, depth=DEPTH):
    chain, cur = [], start
    for _ in range(depth):
        n = producer.get(cur)
        if n is None: break
        chain.append((n.op_type, n.name, list(n.input)))
        cur = n.input[0] if n.input else None
        if not cur: break
    return chain

for w in worst:
    name = w["tensor"].replace(".raw", "").replace("_output_0", "")
    print(f"\n=== {name} (cosine {w['cosine']:.4f}) ===")
    for op_type, op_name, ins in trace(name):
        print(f"  {op_type:<14} {op_name}")
```

链长告诉你融合深度。**任何 ≥ 6 个算子且混有 Cast/Mul/Reduce/Sqrt/Div 的链，就是 HTP 融合领域。**

### Step 3：对照已知融合 pattern（通用算子融合表）

HTP O3 已知会融合的 pattern（narrow point = 融合 kernel 把 INT16 写回 DDR 的那个 tensor）：

| Pattern | 算子签名（前→后） | 融合长度 | narrow point | 备注 |
|---|---|---|---|---|
| **LayerNorm** | `ReduceMean→Sub→Mul→ReduceMean→Add→Sqrt→Div→Mul→Add` | 9 | 末 `Add` 或后随 `Cast` | Sqrt+Div 查表近似 |
| **RMSNorm** | `Cast→Mul→ReduceMean→Add→Sqrt→Div→Mul→Add→Cast` | 9 | 末 `Cast` | Sqrt+Div 查表近似 |
| **GELU (tanh)** | `Mul→Mul→Add→Mul→Tanh→Add→Mul→Mul` | 8 | 末 `Mul` | Tanh 查表 |
| **GELU (erf)** | `Div→Erf→Add→Mul→Mul` | 5 | 末 `Mul` | Erf 查表 |
| **SiLU/Swish** | `Sigmoid→Mul` | 2 | `Mul` | 风险低 |
| **Softmax** | `Sub→Exp→ReduceSum→Div` | 4 | `Div` | Exp/Div 近似 |
| **Attention QK** | `Transpose→MatMul→Mul(×scale)→Add(mask)` | 4 | `Add` | 有时与后随 Softmax 融合 |

判定是否融合：① 签名对表；② 链长 ≥ 6 且匹配已知 pattern → 假定 HTP 上融合；③ 链含 Sqrt/Div/Erf/Exp/Tanh（超越函数）→ 融合概率极高。

### Step 4：unique-value 塌缩比验证 narrow point

确认可疑 narrow point 确实被 HTP 压缩。经典指纹：**unique-value 塌缩**——参考仿真产出上千个不同 INT16 值，HTP 只有几百个。

```python
import numpy as np, sys
ref = np.fromfile(sys.argv[1], dtype=np.int16)   # 必须用 INT16 raw dump，不是 FP32
htp = np.fromfile(sys.argv[2], dtype=np.int16)
print(f"REF unique: {np.unique(ref).size}")
print(f"HTP unique: {np.unique(htp).size}")
print(f"Ratio     : {np.unique(htp).size / max(np.unique(ref).size,1):.3f}")
```

**判定规则**：

| unique 比 (HTP/REF) | 结论 |
|---|---|
| > 0.8 | 不是 narrow point —— 继续往链上游走 |
| 0.3 – 0.8 | 疑似 narrow point —— 回退候选 |
| **< 0.3** | **确认 narrow point** —— HTP 融合把值压得很重 |

多个候选都 < 0.3 时，链上**最早的**那个是根因，后面的是下游受害者。

### Step 5：生成最小范围 FP16 回退 override

只把确认的 narrow point 提到 FP16（不是整条链）：

```python
import json
NARROW_TENSORS = ["/norm_X/Cast_1_output_0", "..."]   # 用 ONNX tensor 名，非文件名
base = json.load(open("model.encodings"))
ae = base.setdefault("activation_encodings", {})
for t in NARROW_TENSORS:
    ae[t] = [{"bitwidth": 16, "dtype": "float"}]
json.dump(base, open("model_fp16_fallback.encodings", "w"), indent=2)
```

**关键规则（来自真实失败教训）**：
1. **不要**在 converter 跑完后手改 encodings——必须在 converter 输入端用 `--quantization_overrides` 喂，否则不插 Convert 节点，导致类型边界崩溃（`0x232 != 0x508` 之类）。
2. **不要**把 per-channel/LPBQ 量化的权重提到 FP16——LPBQ 要求 `is_sym=True, offset=0`；标 Conv/MatMul 权重 FP16 会使该 block 失效、HTP 塌成常量输出。
3. **只提 activation**，权重保持原量化，HTP 插的 Convert 处理边界。
4. **提在 narrow point，不是整条链**——提上游只是把 narrow point 推到下游。修复必须恰好打在压缩 unique 值的那个 tensor。
5. **从 converter 重跑，不是从 context-binary-generator**——override 必须经 converter 传播才能插正确的 Convert 节点。

### Step 6：验证

重跑设备 + 重做 Step 1 排名：

| 结果 | 解读 |
|---|---|
| cosine ↑ 且 worst-N 变了 | 修好，可能别处还有 narrow point → 迭代 |
| cosine ↑ 且 worst-N 相同但 cosine 更高 | 部分修好，同链还有 narrow point → 加进 override |
| cosine 不变 | narrow point 选错 → 用更严的比阈值重做 Step 4 |
| cosine ↓ 或常量输出 | override 破了类型边界 → 重读关键规则 1/2 |

## 4. 常见陷阱

| 陷阱 | 症状 | 修法 |
|---|---|---|
| 拿 FP32 dump 比 INT16 dump | 所有 cosine 都差 | 确保两边都是 FP32（HTP 经 `--set_output_tensors` 写出时已反量化） |
| tensor 名不匹配 | Step 1 报 0 个公共 tensor | HTP 重命名 `/x/y/z` → `_x_y_z`，比对前归一化 |
| 布局不匹配（NCHW vs NHWC） | 所有 conv 输出 cos ~0.5 | HTP 默认 NHWC，reshape 参考 dump 或按 flat 比 |
| 忘了残差路径 | norm 的 Cast 看着差但它是受害者 | 每个 Add 两个分支都要走——残差伙伴可能才是真源 |
| narrow point 选成末端 Mul | FP16 回退反而 regress | narrow point 是上游的 norm Cast，不是末端 Mul 本身 |

## 5. 与现有 SKILL 的关系

- 现有 `accuracy/SKILL.md` 只做到"整体/per-channel cosine 诊断 → B6 给选项"，**缺"为什么这层差 + 精准修哪个 tensor"的图拓扑深度定位**。本 SKILL 把诊断从通道级升级到"图感知的 narrow-point 级"；Step 0.5 的 encoding 对拍是现有体系没有的"工具链静默改写"排查环节。
- 与 `mixed-precision`（C5）配套：本 SKILL 负责**定位**该把哪个 tensor 回退，C5 负责**落地**那份 override JSON（残差 dtype 对称、双端 float_bitwidth 等契约）。
