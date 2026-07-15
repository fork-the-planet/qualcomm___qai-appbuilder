---
skill_id: model-opt
tier: base
triggers: ["模型优化", "模型量化", "推理慢", "提性能", "per-layer 耗时", "bottleneck", "optrace", "cosine < 0.95", "精度掉", "通道全 0", "量化精度", "图优化", "HTP cycles", "加速", "延迟高"]
---

# Model Optimization — 模型优化能力索引（类别索引 SKILL）

> **本类管什么**：一个模型**已经能成功转换并跑起来了**，但你想让它**更准**（精度）或**更快**（性能）。本 SKILL 是索引层——帮你判断该用哪个子能力，然后 `read` 加载那一个。
> **不管什么**（→ 去 `model-builder`）：转换报错、算子不支持、推理崩溃、环境/SDK 故障——那些是"转换还没跑通"，属 `model-builder` 及其 `troubleshooting/`。**本类的前提是转换已成功。**

---

## 🧭 第一步：我到底该用哪个？（决策树）

```
模型已转换成功，我想优化它 —— 我的问题是"精度"还是"速度"？

├─ 【精度问题】结果不对 / cosine < 0.95 / 量化后掉点 / 某通道输出全 0
│     → 用 quantization/accuracy  （量化精度诊断与修复）
│
└─ 【速度问题】跑得慢 / 想降低延迟 / 想提吞吐
      │
      ├─ 我还不知道慢在哪 (没有 per-layer 数据)
      │     → 先用 profiling  （测出每层耗时，定位瓶颈算子）——这是必做的第一步
      │
      └─ 我已经知道瓶颈在哪 (有 optrace/per-layer 数据了)
            → 用 graph  （对瓶颈算子做等价改写，让 HTP 跑更快）[仅内部]
```

**一句话**：**精度问题先走 quantization；速度问题先 profiling 测、再 graph 改**。精度与性能是两条主工作流，入口不同；但并非绝对隔离：`graph/patterns` 是图等价改写的唯一真理源，其中大多数 pattern 服务性能，少数 pattern 服务量化/部署数值正确性修复（如 bias-split 溢出规避）。这类精度问题仍从 `quantization/accuracy` 诊断入口进入，命中特定数值根因后再路由到对应 graph pattern。

---

## 🧭 第二步：路由表（定位到具体子 SKILL 再加载）

> **tier 说明**：`base` 随外部版发布；`advanced` 仅内部版存在。external 版中 advanced 子项**物理不存在**——路由到它时若目录缺失，**静默跳过，不报错、不占位**。

| 我的场景 / 症状 | 用哪个 | 加载路径 | tier |
|---|---|---|---|
| 结果不对 / `cosine < 0.95` / 量化掉点 / 通道全 0 / Large-Dynamic-Range / 不知道用什么校准数据 / 命中 B6 | **quantization/accuracy** | `${APP_ROOT}/factory/chat_features/model-opt/quantization/accuracy/SKILL.md` | base |
| 慢，但**不知道慢在哪**；想采集 per-layer 耗时 / optrace / 看 chrometrace 找瓶颈 | **profiling**（速度优化第 1 步） | `${APP_ROOT}/factory/chat_features/model-opt/profiling/SKILL.md` | base |
| 慢，且**已定位瓶颈算子**；想做图等价改写提速（MHA→SHA、Conv1x1→MatMul 走 HMX、消 5D Slice…） | **graph**（速度优化第 2 步） | `${APP_ROOT}/factory/chat_features/model-opt/graph/SKILL.md` | **advanced**（external 剔除） |

### 精度深度增强子项（tier: advanced，仅内部；external 版目录物理缺失 → 静默跳过）

命中 B6 后若需更深诊断 / 更精细方案，从 `quantization/accuracy` 再下钻到：

| 我的场景 / 症状 | 用哪个 | 加载路径 |
|---|---|---|
| 不确定该不该 clip 离群值 / cosine 掉但 SQNR 好看 | worth-clip-analyzer | `${APP_ROOT}/factory/chat_features/model-opt/quantization/accuracy/worth-clip/SKILL.md` |
| 参考仿真过、设备不过 / worst 层已定位需图拓扑深挖 narrow point | narrow-point-localization | `${APP_ROOT}/factory/chat_features/model-opt/quantization/accuracy/narrow-point/SKILL.md` |
| 想只把敏感几层保 FP16、其余 INT8 / 局部精度回退落地 | mixed-precision | `${APP_ROOT}/factory/chat_features/model-opt/quantization/mixed-precision/SKILL.md` |
| 深层残差网络量化后累积 outlier / weight-only 正常但全量化崩 | residual-outlier | `${APP_ROOT}/factory/chat_features/model-opt/quantization/accuracy/residual-outlier/SKILL.md` |
| 精度掉且某通道输出 cos ≈ −1（符号翻转）= per-channel INT16 bias 溢出 | bias-split pattern | `${APP_ROOT}/factory/chat_features/model-opt/graph/patterns/Extended/Equi_Subst/O_Bias_Split_Overflow_Guard_Skill.md` |

---

## 三个子能力分别是什么、什么时候用

### 1. `quantization/accuracy` — 量化精度诊断与修复  (tier: base)
- **解决什么**：模型量化（INT8/W8A16 等）后精度掉了——cosine 不达标、检测框偏、分类错、某输出通道全 0。
- **输入**：量化后模型的推理结果 vs FP 基线（cosine/输出对比）。
- **它做什么**：先做**零成本诊断**（如查校准数据是否只是单张图的增广——最常见根因），命中 **B6 就停下向用户报告**，给出 5 个修复选项**及各自原理**：① 提升校准数据多样性 ② CLE（跨层均衡）③ 升到 W8A16 ④ 保持 FP16 ⑤ 接受现状。含 **Large-Dynamic-Range 陷阱**（整体 cosine 好看但个别通道崩，需逐通道校验）。
- **什么时候用**：任何"精度不对"的场景。它是精度线的唯一入口；若诊断发现是特定数值/后端实现问题，可继续路由到 graph 中的精度修复型图改写 pattern。
- **不做什么**：不盲目改图、不自动连环尝试修复、不以提速为目标；只有在诊断命中特定数值根因并得到用户确认后，才引用 graph pattern 做等价修复。

### 2. `profiling` — HTP 性能剖析（测量）  (tier: base)
- **解决什么**：模型慢，但你**不知道慢在哪个算子**。这是速度优化的**测量前置**，不测就优化 = 盲目改。
- **它做什么**：`enable_profiling` → `qnn-net-run --profiling_level detailed --profiling_option optrace` → `qnn-profile-viewer` 转 chromeTrace → `chrome://tracing` 看**每层耗时**，找出占 cycles 最多的 top-N 瓶颈算子（覆盖 QNN `.so`/`.dlc`/`.bin` 与 SNPE `.dlc`）。
- **输出**：一份"哪些算子最耗时"的瓶颈清单 → 喂给下一步 `graph`。
- **什么时候用**：速度优化的**第一步，必做**。也可单独用来出性能报告。
- **为什么 base**：测量是通用手段，外部用户也要测自己模型，故随外部版发布。

### 3. `graph` — HTP 图等价优化（改写提速）  (tier: advanced, 仅内部)
- **解决什么**：已知瓶颈算子后，**怎么改让它在 HTP 上跑更快**。这是速度优化的**改写执行**。
- **它做什么**：一套**性能优化迭代方法论**（optrace 找瓶颈 → 根因归类到硬件维度 HVX/HMX/VTCM/5D/动态shape → 设计**数学精确等价**的改写 → onnxruntime 验精度不变 → 上板实测加速比 → 有效则迭代/无效则回退记录）。三块资产：
  - **`patterns/`** — 73 个通用图优化模式库（唯一真理源）：每个是一种等价改写（如 MHA→SHA 省 VTCM、Conv1x1→MatMul 走 HMX 4-8x、消 5D Slice）。含"有哪些招 + 数学原理 + 等价条件"；经实战案例验证过的高频模式还带"何时不要用 / 适用边界"节。
  - **`cases/`** — 4 个实战案例（VITS Flow 1.48x / SuperPoint+LightGlue 6.02x 等）：真实模型上"哪些招有效/无效、几毫秒、为什么"，每个 Pass 反链到对应 pattern。是"照着抄的样板"。
  - **`scripts/qai_recommend_opt.py`** — 输入 ONNX，分析算子分布，自动推荐该用 patterns 里的哪些模式。
- **什么时候用**：速度优化的**第二步**，且**必须先有 profiling 的瓶颈结果**（否则不知道改哪里）。
- **典型用法**：跑 `qai_recommend_opt.py` 拿推荐 → 查 `patterns/` 对应模式的原理 → 在 `cases/` 找最相似案例抄脚本 → 按方法论改写并验证。
- **精度交叉说明**：`graph` 的主用途是性能优化，但 `patterns/` 中也保留少量“精度/数值修复型”的等价图改写（例如 per-channel INT16 bias 溢出导致通道符号翻转时的 bias-split pattern）。这些 pattern 不作为精度问题入口；精度问题仍先走 `quantization/accuracy`，由诊断结果路由到这里。
- **为什么 advanced**：模式库与案例源自内部实战数据，仅内部可用。

---

## 两条工作流一图看清

```
【精度线】(base 为入口，必要时引用 advanced graph pattern)
  量化后精度不对 → quantization/accuracy → 诊断→B6停下报告→选修复方案
                                            └─ 若命中特定数值/溢出根因 → 引用 graph/patterns 中的精度修复型等价改写

【速度线】(两步接力)
  模型慢 → profiling(base, 测量) → 瓶颈算子清单 → graph(advanced, 改写) → 等价优化+实测加速
                                                          └─ patterns(招式库) + cases(样板) + 推荐器
```

- 两条线**入口不同**，按你的问题（准/快）选一条；但精度线在少数数值修复场景会引用 graph pattern。
- 速度线里 **profiling → graph 是顺序接力**：先测后改，profiling 的输出是 graph 的输入。
- external 版：`graph` 被剔除，速度线只剩 profiling（能测出瓶颈但不含内部改写知识库）；精度线完整保留。

---

## 可扩展性

新增优化维度（如未来的 `latency/` 运行时调优、`power/` 功耗、`memory/` 内存）：
1. 在 `model-opt/<新维度>/` 下建子 SKILL，front-matter 标 `tier: base|advanced`，并写清"解决什么/输入输出/什么时候用/和谁配合"（对齐上面三个子能力的描述粒度）。
2. 在本索引的「决策树」+「路由表」+「子能力说明」三处各加一条。
3. advanced 子项登记进 `scripts/release/manifest.toml` 的逐项 exclude 清单。
> 本索引 SKILL 本身 `tier: base`（随外部版发布），但内部按 tier 过滤：external 版只呈现 base 行，advanced 行对应目录物理缺失 → 静默跳过。
