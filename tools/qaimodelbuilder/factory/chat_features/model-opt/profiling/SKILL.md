---
skill_id: profiling
tier: base
triggers: ["性能剖析", "profiling", "per-layer 耗时", "optrace", "chrometrace", "qnn-profile-viewer", "采集 trace", "找瓶颈", "benchmark 延迟"]
sources: ["migrated-from: model-builder references (原性能剖析文档，已移入本目录)"]
---

# HTP Profiling Guide

> **定位**：本 SKILL 是"性能剖析"维度（`model-opt/profiling/`，tier:base）——**如何采集并可视化模型在 HTP 上的 per-layer 性能数据、找出瓶颈**。它是性能优化的**测量前置**：先用本 SKILL profile 定位瓶颈，再（内部版）用 `model-opt/graph/` 的图优化知识改写。采集方法对外部用户同样有用，故 tier:base。

## Overview
Collect and visualize per-layer profiling data for QNN and SNPE models running on the HTP backend.

## Prerequisites
- QAIRT SDK or SNPE SDK environment
- A compiled model (`.so` / `.dlc` / `.bin`)
- Google Chrome (for trace visualization, optional )

## QNN Profiling

When using the ONNX wrapper inference (`onnxwrapper`), the profiling path depends on the model format:

| Model format | Pre-step required |
|---|---|
| `.so` / `.dlc` (model library) | None — set `enable_profiling=True` directly |
| `.bin` (context binary) | Regenerate the context binary with `--profiling` first |

#### QNN model library (`.so` / `.dll`)

**Step 1: Enable profiling in the session**

```python
import onnxruntime as ort  # resolved to onnxwrapper by the skill (routes through qai_appbuilder / QNNContext)

sess_options = ort.SessionOptions()
sess_options.enable_profiling = True          # routes inference through qnn-net-run
sess = ort.InferenceSession("model.onnx", sess_options)
```

When `enable_profiling=True`, the wrapper bypasses `QNNContext.Inference()` and calls `qnn-net-run` directly with `--profiling_level=detailed --profiling_option=optrace`.

**Step 2: Run inference**

Run inference as normal. Profiling logs are written automatically to `qairt_profile_output/` in the current working directory.

**Step 3: Collect profiling logs**

```
qairt_profile_output/qnn-profiling-data_0.log
```

**Step 4: Convert logs to Chrome Trace format**

```bash
${QAIRT_SDK_ROOT}/bin/x86_64-linux-clang/qnn-profile-viewer \
    --reader ${QAIRT_SDK_ROOT}/lib/x86_64-linux-clang/libQnnChrometraceProfilingReader.so \
    --input_log qairt_profile_output/qnn-profiling-data_0.log \
    --output chromeTrace.json
```

**Step 5: Visualize in Chrome**

Open `chrome://tracing` in Google Chrome and load `chromeTrace.json` to inspect per-layer execution times and identify bottlenecks.

#### QNN context binary (`.bin`)

The context binary must be regenerated with optrace instrumentation before profiling data can be collected.

**Step 1: Regenerate context binary with profiling enabled**

```bash
python scripts/qai_dev_gen_contextbin.py --model /path/to/libmodel.so --profiling
```

This passes `--profiling_level detailed --profiling_option optrace` to `qnn-context-binary-generator`, embedding optrace instrumentation in the output `.bin`.

**Steps 2–5**: Same as the model library path above, using the generated `.bin` as the model path.

## SNPE Profiling

When `enable_profiling=True` and the model is a `.dlc` file, the wrapper routes inference through `snpe-net-run` with profiling flags forwarded — equivalent to the direct invocation shown in Step 1 below.

**Step 1: Run snpe-net-run with profiling**

```bash
${SNPE_ROOT}/bin/x86_64-linux-clang/snpe-net-run \
    --container model.dlc \
    --input_list input_list.txt \
    --output_dir snpe_output \
    --perf_profile burst \
    --profiling_level detailed
```

This writes `SNPEDiag_0.log` (and optionally `SNPEDiag_1.log`, …) to `snpe_output/`.

**Step 2: Convert to CSV**

```bash
${SNPE_ROOT}/bin/x86_64-linux-clang/snpe-diagview \
    --input_log snpe_output/SNPEDiag_0.log \
    --output snpe_profile.csv
```

**Step 3: Convert to Chrome Trace**

```bash
${SNPE_ROOT}/bin/x86_64-linux-clang/snpe-diagview \
    --input_log snpe_output/SNPEDiag_0.log \
    --output chromeTrace.json \
    --output_format chrometrace
```

**Step 4: Visualize in Chrome**

Open `chrome://tracing` in Google Chrome and load `chromeTrace.json`.

## Key Points
- **QNN `.so`/`.dlc`:** Set `enable_profiling=True` directly — no pre-step needed
- **QNN `.bin`:** Must regenerate context binary with `--profiling` before collecting data
- **SNPE `.dlc`:** `enable_profiling=True` routes through `snpe-net-run` automatically
- **Output format:** All paths produce a `chromeTrace.json` viewable in `chrome://tracing`

## Common Issues
- **No profiling output:** Verify the output directory (`qairt_profile_output/` or `snpe_output/`) exists after inference
- **Context binary missing optrace:** Regenerate with `--profiling` flag; existing `.bin` files without instrumentation will not produce profiling data

---

## 进阶诊断维度（超越 host per-layer 时间线）

> 上面的 chromeTrace 只回答"哪个算子花了多少时间"（host 侧 per-layer）。下面四节补的是"**为什么慢、卡在哪个物理单元、测得准不准、内存在哪一侧**"——它们是 per-layer 时间线之上/之外缺失的诊断维度。

### 硬件计数器诊断（症状 → 硬件指标）⚠️ 片上计数器工具多限 Android

**性能瓶颈的真值在片上硬件计数器里，不在墙钟时间里。** 墙钟只告诉你"慢"，硬件计数器告诉你"卡在 HMX / HVX / VTCM / DDR / 时钟档 / 热降频 哪一环"。

| 症状 | 查这些硬件指标 | 判读方向 |
|---|---|---|
| HMX 吞吐低 / 矩阵算子慢 | HMX Util %、HMX active MCPS、HMX Clock MHz | Util 低=没喂满（图/tile 问题）；Clock 低=档位没上去（DCVS/热） |
| DSP 时钟被压 | DSP Core Clock、热降频阈值频率 | 阈值频率 < 实际=热降频；否则 DCVS 没投够 |
| 内存带宽瓶颈 | DDR 读/写带宽、SLC/NSP 带宽、roofline | 带宽接近峰值=memory-bound，应减少数据搬运而非加算力 |
| HVX 利用不足 | HVX Util %、HVX 寄存器 interlock | Util 低+interlock 高=向量流水被相关性阻塞 |
| uDMA 停顿 | UDMA active、描述符 fetch stall | 搬运 stall 主导=数据供给跟不上计算 |
| 算子被错误归类到 HVX/HMX | 该算子活跃期 HMX Util vs HVX Util | 与 graph pattern 声称的单元对不上 = 归类需修正 |

**roofline 最有价值**：算 FLOPs/字节 的算术强度对比硬件峰值算力/峰值带宽——点落在斜坡=memory-bound、落在平顶=compute-bound，决定优化方向。这套分析范式平台无关，WoS PC 上无片上计数器工具时仍可手工套用；它也正是**验证 graph pattern 的 HVX/HMX 归类是否成立**的硬件真值来源（声称走 HMX 的算子活跃期 HMX Util 应显著 >0）。

**🔴 防静默失败纪律**：硬件计数器工具里，用一个该设备/该版本并不支持的 metric ID，工具往往**不报错只静默忽略**——你以为在测 HMX 利用率，实际那列根本没数据。铁律：**先查能力清单（capabilities）→ 再查该能力下真实可用的 metric ID → 只用"确认存在"的 ID 采集**，绝不凭记忆写 ID。（与 AGENTS.md §5 State-Truth-First 一致：先探"这计数器在这台设备/这版工具上到底存不存在"。）

> ⚠️ **工具限制**：片上计数器 CLI（如 `adb shell qprof`）是 Android 设备预装工具，WoS PC 无。本节吸收的是**诊断知识**（每个症状看哪些计数器、意味什么），不是工具操作步骤。

### 端到端耗时分解归因

**一次调用慢，不能只报"58ms"，必须报"58ms，其中 99.9% 花在设备执行上"。** 把往返总时间拆成"上层封送开销"与"纯设备计算"，**占比决定往哪追**：

```
设备执行时间 ≈ 往返总时间 − 上层封送各阶段之和（map/unmap 缓冲、取/送参数、缓存维护）
```

| 观测 | 结论 | 去哪追根因 |
|---|---|---|
| 设备执行占比 > 95% | 瓶颈在**设备计算端**，不在 RPC/传输 | 模型/图、时钟档、热降频（转硬件计数器） |
| 慢集中在 1–2 秒窗口内 | 瞬时过载 / 排队，非稳态慢 | 那窗口同时在跑什么；并发、DCVS 升频延迟 |
| 上层封送阶段占比大 | 封送/内存管理开销 | 缓冲区大小、缓存操作、合并小缓冲区 |

**🔴 铁律：DSP% > 95% 则别追 RPC/传输**——map/unmap/cache 都是微秒级，一次几十毫秒调用里它们绝不可能是主因，此时唯一正确动作是转设备计算端诊断。**不要用平均值把长尾抹平**：用户感受到的是 p99/max，逐条排出最慢的几次，而非只看均值。

### 性能测量纪律 + 资源争用归因

**测量方法本身会骗你**，下面每条都是"测出来的数不是你以为的那个数"：

1. **冷态 Run1 弃用，取 Run2+ 稳态**——第一次调用总偏慢（冷唤醒/缓存未热/频率未 ramp），报单次冷态数字是错误的；每配置跑 3+ 次比 Run2+ 平均。
2. **DCVS 需提前 ramp，"投晚了=没投"**——升频请求响应有 10–50ms 延迟；把功耗投票放在会话开始处（`open()`/首次初始化），不要放在每次推理调用里，否则测到的是"没投上票"的假低性能。
3. **静息频率 ≠ 运行频率**——空闲时采样的时钟频率不代表计算期真实频率；必须在计算真正执行的窗口内采样。
4. **微优化可能相互破坏**——"看起来该更快"的微优化（如 `:nt` 非临时 store 与 `l2fetch` 预取冲突反而变慢）必须实测。
5. **一次只扫一个变量**——线程数/频率档/输入尺寸交互影响最优点，测性能时固定其余才能归因。

**资源争用归因（多客户端并发）——崩溃/超时的线程是受害者，不是元凶**：一个 client 持满共享资源节点（如 VTCM，`bFree:0`），第二个线程请求同资源超时→分配失败→崩溃。诊断顺序：先按失败时间戳找**资源的持有者**（进程/线程标识+分配大小），再下结论，绝不一看到"谁崩了"就怪谁。处置：让持有者空闲时释放/去缓存、按需切分份额或串行化、受害者路径容忍获取超时。**与 §2.5 VTCM 判据区分**：BadVA/容量类（自己就装不下）→ graph 的 VTCM 定量判据；acquire 超时 + 节点被他人占满 → 本节持有者-受害者归因。

### 内存测量维度 ⚠️ dumpsys 限 Android

**测内存前先问：我这个工具测的是哪一侧？** ARM 进程内存工具（如 `dumpsys meminfo`）**只测 ARM 侧**；模型权重通过 FastRPC ION 分配在 **DSP 侧，根本不计入 ARM 进程 PSS**——不搞清这点会得出"模型只占几 MB"的严重误判。

**通用推论（含 WoS PC）**：NPU/DSP 加速器上的权重内存通常不体现在宿主 CPU 进程的内存统计里；报告"模型内存占用"必须**分侧列出** CPU 侧与加速器侧，绝不能只报 CPU 进程 PSS。

**抓峰值纪律**：初始化/加载阶段常是内存峰值，要抓到必须**在进程还没起来之前就先开始采集**（采集器等进程出现、最多等 ~60s），否则加载峰值已过、永久漏测。

VSS/PSS/RSS/USS 语义：对比实际占用用 **PSS**（最公允）；看私有泄漏用 **USS**；看地址空间/加载上限用 **VSS**；RSS 把共享库整份算给每进程偏大。这四件套全是 ARM/CPU 进程层面，仍测不到 DSP 侧权重。

> ⚠️ **工具限制**：`dumpsys meminfo` / `/sys/kernel/debug/ion/` 等是 Android 专属通道，WoS PC 无。本节吸收的是**内存测量认知**（测哪一侧、怎么抓峰值、指标语义），不是 dumpsys 脚本。

### AI 分析 trace 范式

采出 chromeTrace 后，除了人肉在 `chrome://tracing` 翻，还可把 trace（或其摘要）交给 LLM 做自然语言瓶颈分析——直接问"瓶颈在哪 / 哪个阶段最耗时 / 哪里卡顿"。这是对现有分析手段的一句话补充，可直接用在本 SKILL 产出的 `chromeTrace.json` 上。

---

## References
- [QNN HTP Optrace Profiling](https://docs.qualcomm.com/nav/home/htp_backend.html?product=1601111740009302#qnn-htp-optrace-profiling)
- [Profile Your Model](https://docs.qualcomm.com/doc/80-90441-15/topic/profile-your-model.html#panel-0-0-1)
- [Performance Analysis Using Benchmarking Tools](https://docs.qualcomm.com/doc/80-63442-4/topic/performance-analysis-using-benchmarking-tools.html)