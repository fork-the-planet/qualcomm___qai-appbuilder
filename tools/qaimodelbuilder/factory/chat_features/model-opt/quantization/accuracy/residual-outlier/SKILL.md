---
skill_id: residual-outlier-diagnosis
tier: advanced
triggers:
  - "深层残差网络量化后精度崩 / 累积 outlier"
  - "weight-only 量化正常但权重+激活全量化灾难性崩"
  - "残差路径激活幅值极大 / INT16 步长被摧毁"
  - "多次量化实验想加速 / deepcopy quantsim 崩 RecursionError"
sources: ["内部 QNN/HTP 工程实践整理"]
---

# Residual-Path Outlier Diagnosis（残差路径累积 outlier 诊断 + 实验纪律）

> **知识定位**：深层残差网络在低比特激活量化下的具名根因——残差 Add 输出沿网络累积到极大幅值 → INT16 步长崩坏 → 沿残差路径关激活量化器；外加多次量化实验的 state_dict 缓存纪律。
> **抽取内核**：① 残差累积 outlier 的现象签名 + 机制 + "沿残差路径关激活量化器（4 类一起关）"修复；② 多次量化实验用 state_dict 缓存、**不要 deepcopy(quantsim)** 的纪律。
> **剥离外壳**：某 LLM 优化流水线的 PPL/KV-cache/具体层号剥掉或泛化——原机制明确"applies to ANY transformer with residual connections"，且残差累积对任意有残差连接的网络（深 ResNet、深 U-Net 部分）机制相同。
> **适用小模型的理由**：深残差网络（深 ResNet、U-Net、任意深 transformer）在低比特激活量化下都可能撞残差流 outlier；state_dict 缓存是任何用 AIMET 类工具做 PTQ 实验的通用工程纪律。

---

## 1. 现象签名

低比特量化后：

| 指标 | 值 |
|---|---|
| FP baseline 精度 | 正常 |
| Adapted/Prepared 精度 | 与 FP 一致 |
| **仅权重量化（weight-only）精度** | 正常（Δ 很小） |
| **权重+激活全量化精度** | **灾难性崩坏**（可差 1000×+） |

签名：**权重量化没问题，是激活量化炸了**。标准 clip / 混精度配置修不好。

## 2. 机制

含残差连接的网络里，每层输出是 `Add(prev_residual, layer_output)`。N 层后残差流累积。深层残差幅值可达 ±3×10⁵ 量级：

```
浅层  Add 输出范围:  ±60      → INT16 步长 ~ 0.002  ✓
中层  Add 输出范围:  ±150000  → INT16 步长 ~ 4.6    ✗ 被摧毁
深层  Add 输出范围:  ±305000  → INT16 步长 ~ 9.3    ✗ 被摧毁
```

INT16 只有 65536 级。幅值 ±305000 时最小可表达差是 9.3，把上游层辛苦保留的精度全毁了。浅/小网络（残差幅值 < ±150，步长 ~0.005）不触发；**深/宽网络（层数多 或 hidden 大）必触发**。

## 3. 修复：沿残差路径关激活量化器

**关掉残差流上所有边界的激活量化器**（applies to ANY residual network）。要关的 4 类 × N 层 + 1 个末端 norm：

| 关哪个 | 是什么 | 为什么 |
|---|---|---|
| 每层 post-attn 残差 Add 输出 | 新的残差 | 输出就是残差 |
| 每层 post-MLP 残差 Add 输出 | 新的残差 | 输出就是残差 |
| attn 输出投影（o_proj）输出 | 汇入 Add | feeds Add |
| MLP 输出投影（down_proj）输出 | 汇入 Add | feeds Add |
| 每层第一个 norm 的**输入** | 读残差 | reads residual |
| 每层中段 norm 的**输入** | 读残差 | reads residual |
| 末端 norm 的**输入** | 读残差 | reads residual |

> CNN/ResNet 类比：残差 block 的 `Add` 输出、汇入 Add 的投影 conv 输出、以及读残差的归一化层输入——同一套"边界都关"原则。

### 3.1 为什么部分关无效（关键教训）

必须 **4 类一起关**。实测阶梯（深 transformer，FP 基线正常）：

| 迭代 | 关掉的集合 | 全量化精度 | 结论 |
|---|---|---|---|
| 0 | 无 | 灾难（~1600× 差） | ❌ |
| 1 | + 残差 Add 输出 | 仍差很多 | ❌ |
| 2 | + o_proj + down_proj 输出 | 仍不够 | ❌ |
| 3 | + norm 输入量化器 | **可接受** | ✅ |
| 4 | + per-layer clamp + 权重武器 | 最佳 | ✅ |

**最常被漏的是 norm 的输入量化器**——它是"Add 输出（残差）"与"下一层投影"之间的边界。只关 Add 不关下一个 norm 输入，残差会在边界被重新量化，同样的精度损失又回来。

### 3.2 校验计数

关掉的 quantizer 数应满足结构关系（按你模型的命名 regex 定位）：
- 残差 Add 输出 = 2 × num_layers（post-attn + post-MLP）；
- 投影输出 = 2 × num_layers（o_proj + down_proj，各 1/层）；
- norm 输入 = 2 × num_layers + 1（每层两个 norm + 1 个末端 norm）。

计数不对 → 你模型的图命名与预期 regex 不符，打印节点名核对。**注意排除**注意力块内部的 masked-softmax Add（不在残差路径上，别误关）。

## 4. 多次量化实验加速纪律（state_dict 缓存，不要 deepcopy）

做"扫多超参 → 跑量化仿真 → 测精度"循环时：

**🔴 不要用 `copy.deepcopy(quantsim)`。**

- 量化仿真框架（如 AIMET v2）的 ConnectedGraph 有深层循环引用，deepcopy 在深层模型上**必崩 `RecursionError`**；
- 正确做法：第一阶段（SeqMSE/GPTQ 等权重量化）结束后，用 `torch.save(quantsim.model.state_dict(), cache_path)` 缓存；每次实验 **reload state_dict + 手动 `allow_overwrite(False)` 重新冻结权重量化器**；
- 第一次跑省不了，但后续重跑（换层、换候选、换阈值）直接 skip 权重量化阶段，节省 10–100 分钟；
- 推理侧重建量化仿真后、load encodings 前，也要调用同一个"关残差路径量化器"的函数，保持与量化时一致。

## 5. 与现有 accuracy SKILL 的关系

- 现有 `accuracy/SKILL.md` 覆盖校准多样性、Large-Dynamic-Range、CLE / W8A16 粗档，**缺**：① 深层残差流 outlier 的具名诊断（weight-only 正常但全量化崩）与"沿残差路径关激活量化器（4 类一起关）"的修复；② 多次实验的 state_dict 缓存纪律。本 SKILL 是**新增补充**，不与 B6 / Large-Dynamic-Range 现有条目重复（那两条讲通道级 scale 共享与校准，本 SKILL 讲残差路径累积与实验工作流纪律）。
- 更强的**权重量化武器**（GPTQ/SeqMSE）及其叠加互斥警示见 `accuracy/SKILL.md` 的「更强量化武器」小节。
