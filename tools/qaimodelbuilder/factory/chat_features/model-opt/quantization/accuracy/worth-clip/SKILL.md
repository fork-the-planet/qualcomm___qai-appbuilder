---
skill_id: worth-clip-quant-analyzer
tier: advanced
triggers:
  - "不确定该不该 clip 离群值 / 长尾"
  - "量化精度掉但不知道值不值得裁离群值"
  - "cosine 掉但 SQNR 看着好 / SQNR 悖论"
  - "宽动态范围通道，想量化决策是否 clip"
sources: ["内部 QNN/HTP 工程实践整理"]
---

# Worth-Clip Quantitative Classifier（该不该 clip 离群值的定量判据）

> **知识定位**：给"某待量化张量该不该 clip 掉长尾离群值 / clip 收益有多大"一个**可计算的定量判据**，而非拍脑袋。
> **抽取内核**：纯 FP、tensor-agnostic 的 `granularity_gain = full_FP_range / (2×abs_p99)` 四级判定（CRITICAL/WORTH/MARGINAL/NOT_WORTH）+「用下游任务指标/输出 cosine 选阈值，绝不用 SQNR」的方法论。
> **剥离外壳**：某 LLM 优化流水线里的 Q/K 激活、RoPE、PPL eval、attention-KL 等 LLM 专属外壳全部剥掉——分类器本身与张量语义无关。
> **适用小模型的理由**：判定"某张量在给定位宽下值不值得 clip"是任意张量的通用问题；CNN 宽动态范围 conv 激活、超分尾部 conv、任何有离群通道的权重/激活都可用同一公式。

---

## 1. 核心问题

一个待量化张量，其 FP 分布带长尾离群值。是否应该在量化前把离群值 **clip** 到某个更紧的范围？clip 会牺牲少数离群值的表达，换取绝大多数"主体"值的量化分辨率。判据不该拍脑袋，而是可计算的。

## 2. 定量公式

设某张量的 FP 观测 min/max 为 `fp_min`、`fp_max`，量化位宽 `bw`，`abs_p99` = `|x|` 的第 99 百分位（长尾裁掉后仍保留 99% 质量的紧范围代理）。

```
granularity_gain = step_no_clip / step_with_clip
                 = full_FP_range / clip_range
                 = full_FP_range / (2 × abs_p99)
```

其中：

```
full_FP_range = 2 × max(|fp_min|, |fp_max|)      if symmetric
              = fp_max - fp_min                   if asymmetric
clip_range    = 2 × abs_p99          (裁掉 p99 以上离群值后主体的范围)
levels        = 2^bw - 1             if symmetric and bw <= 8
              = 2^bw                 otherwise
step_no_clip   = full_FP_range / levels
step_with_clip = clip_range      / levels
```

`granularity_gain` 的物理意义：clip 后量化步长相对不 clip 缩小的倍数——即"主体值的量化分辨率提升倍数"。

## 3. 四级判定表

| Tier | 阈值 | 含义 | 处置 |
|---|---|---|---|
| `CRITICAL`  | `gain >= 20×`     | 离群值主导，不 clip 量化必崩 | clip 是强制的 |
| `WORTH`     | `5× <= gain < 20×` | clip 有明确、可观的精度收益 | 建议 clip |
| `MARGINAL`  | `2× <= gain < 5×`  | 收益可能被校准噪声淹没 | 需实测再决定 |
| `NOT_WORTH` | `gain < 2×`        | INT 分辨率相对 FP 范围已足够 | 不必 clip |

经验佐证（把该分类器换成通用输出指标同样成立）：某层 gain=50.7× 判 CRITICAL，clip 后指标改善巨大；gain=1.94× 判 NOT_WORTH，Δ指标为噪声级；gain=2.21× 判 MARGINAL，边界，与直觉一致。

**该分类器能在纯 FP 分析阶段（不跑任何量化实验）独立复现出需要数十分钟量化实验才能确认的结论。先跑它，再决定要不要烧算力做 clip 搜索。**

## 4. 为什么用 `abs_p99` 而不是硬编码 ±10 / ±20

固定 `target_clip_abs` 会把"纯 FP 范围分析"耦合到"量化侧决策"，违背该步骤的定位（"我们在看 FP 模型，还没选任何 clip 阈值"）。`abs_p99` 是**只依赖 FP 分布本身**的最小代理，回答"如果裁掉长尾，主体能收多紧"，不预判实际生产 clip 值。任何百分位（p99.5 / p99.9）都可用，只要它是分布自身的属性。

## 5. 🔴 阈值选择：用下游任务指标 / 输出 cosine，**绝不用 SQNR**

**这是本方法论最重要的一条：SQNR（信噪比）会骗人。**

- **SQNR 悖论**：no-clip（离群值全保留）的 SQNR 往往看起来最优（例 25.77 dB），因为 SQNR 由离群值的大 L2 范数主导；但同样的 no-clip 在真实任务指标上是灾难。
- **实证**：某层 no-clip 任务一致率仅 22%，clip 到主体范围后一致率 82%+，但 SQNR 反而从 25.77 dB 掉到 0.58 dB。**信任任务指标，不信 SQNR。**

**正确的阈值筛选指标**：
1. **主指标**：量化输出 vs FP 参考输出的 **cosine 相似度**（或任务级 KL 散度），越高越好。
2. **次指标（tiebreaker）**：**下游任务指标**——分类 top-K 一致率、检测框 IoU、超分 PSNR、任意端到端质量分。
3. **过滤器**：任务一致率过低（< 50%）或输出偏离过大的候选直接淘汰，即使其 SQNR 好看。

原理：SQNR 是张量级的平均误差，被大幅值分量的 L2 范数主导，掩盖了小幅值分量（往往才是任务关键，如检测 class score、语义 logits）被摧毁的事实。

> 与 `accuracy/SKILL.md` 的 **Large-Dynamic-Range trap** 同源互补：那里讲"整体 cosine 被大幅值通道掩盖，须 per-channel 看"；这里讲"SQNR 被离群值掩盖，选 clip 阈值须用任务指标"。两者都是"平均指标会骗人，要看对的粒度/对的指标"。

## 6. 独立可跑分析脚本

见同目录 `worth_clip_analyzer.py`：

```bash
# 单张量快速判定（命令行）
python worth_clip_analyzer.py --fp-min -507.7 --fp-max 478.9 --bw 8 --symmetric --abs-p99 57.6

# 从 .npy 张量文件批量判定（自动算 abs_p99）
python worth_clip_analyzer.py --npy activation.npy --bw 8 --symmetric
```

作为库复用：

```python
from worth_clip_analyzer import worth_clipping, abs_percentile_from_array
# tensor-agnostic：传任意 (fp_range, quant_scheme, abs_p99) 三元组
decision = worth_clipping(fp_min=-507.7, fp_max=478.9, bw=8, symmetric=True,
                          target_clip_abs=57.6)
# -> {'granularity_gain': 8.81, 'decision': 'WORTH', 'reason': '...'}
```

## 7. 与现有 accuracy SKILL 的关系

- 现有 `accuracy/SKILL.md` 只会"发现宽动态范围通道"（B6、Large-Dynamic-Range trap），缺"**该不该 clip + clip 到多少**"的定量决策。本 SKILL 补齐该缺口（`granularity_gain` 分级 + SQNR 会骗人的阈值选择），是**新增补充**而非重复。
- 落地时可作为 accuracy 诊断的一个前置零成本步骤：拿到宽范围张量的 FP min/max 与 p99，先跑分类器判 tier，再决定是否进入 clip 阈值搜索。
