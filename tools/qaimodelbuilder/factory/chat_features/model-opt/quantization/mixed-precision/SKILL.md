---
skill_id: mixed-precision-fp16-overrides
tier: advanced
triggers:
  - "想只把敏感几层保 FP16 其余保 INT8 / 局部精度回退"
  - "W8A16 baseline 跑通但尾部/输出/某分支精度不够"
  - "残差 Add 两输入 dtype 不同 / QNN 静默插 Convert"
  - "INT16 权重 + FP16 激活被拒 / 0xc26 / Value -128"
sources: ["内部 QNN/HTP 工程实践整理"]
---

# Local FP16 Fallback：混精度 Override 契约 + HTP 硬件约束

> **知识定位**：把少数敏感层保 FP16、其余保 INT（W8A16/W8A8）的**落地工具**——`--quantization_overrides` JSON 契约、残差 dtype 对称规则、双端 `--float_bitwidth 16` 配对，以及 HTP FP16 激活的权重精度硬件可行性。
> **抽取内核**：override JSON schema（activation + param 都要标）、残差 Add 两输入必须同 dtype（否则 QNN 静默插 INT→FP16 Convert）、converter+quantizer 两端都要 `--float_bitwidth 16`、红旗自检表；WxFP16 硬件可行性（W4FP16/W8FP16 支持，W16FP16 被拒）与 INT16 offset 硬约束 + 0xc26 指纹。
> **剥离外壳**：某 LLM 优化流水线的 KV-cache FP16 encoding、embedding config 字段、PPL 评测等 LLM 外壳剥掉；只保留纯工具链/HTP 层面的契约与硬件约束。
> **适用小模型的理由**："W8A16 baseline 跑通但尾部/输出/某分支精度不够，只把敏感层保 FP16"是端侧 CNN/超分/检测最常见的精细混精度需求；契约与硬件约束都与模型语义无关。

---

## 1. 何时用

- CNN / vision / 超分 / 检测 ONNX 走 `qairt-converter → qairt-quantizer → qnn-context-binary-generator` 编译到 HTP；
- W8A16 baseline 已能跑，但**尾部 / 输出 / 某个分支**精度不可接受；
- 能从 ONNX 图（Netron）按名字锁定要保 FP16 的 tensor。

配套：定位"该回退哪个 tensor"用 `narrow-point-localization`（C3）；本 SKILL 负责把那份决策**落地成正确的 override JSON + 编译 flag**。

## 2. 核心两条规则

1. **converter 和 quantizer 两端都必须看到 `--float_bitwidth 16`**（否则 float dtype 在 DLC 里默认成 FP32）。
2. **残差算子（Add/Concat/Mul）的每个输入必须同 dtype**——否则 QNN 静默插 INT→FP16 Convert 算子（增加延迟、可能 regress、破坏 `--enable_intermediate_outputs` 可复现性）。

## 3. Override JSON Schema

```json
{
    "activation_encodings": {
        "<onnx_tensor_name>": [{"bitwidth": 16, "dtype": "float"}]
    },
    "param_encodings": {
        "<onnx_initializer_name>": [{"bitwidth": 16, "dtype": "float"}]
    }
}
```

- `bitwidth`: 16；`dtype`: `"float"`（**不是** `"int"`；`"int"`+16 表示 INT16）；
- 值必须是**含一个 dict 的 list**，不是裸 dict；
- 名字必须与 ONNX 图**逐字节匹配**（大小写、前导 `/` 都要对）；
- 保 FP16 的每一层，**activation_encodings（输出 tensor 名）和 param_encodings（weight/bias initializer 名）都要标**——只标 activation，权重仍走 INT8，该层并非真正 FP16。

## 4. 残差分支 dtype 对称规则（核心）

```
producer_A ──┐
              Add ──► consumer
producer_B ──┘
```

**producer_A 和 producer_B 的输出 tensor 必须同 dtype。** 只标一个为 FP16，qairt-quantizer 会在 Add 前插一个隐式 `INT→FP16 Convert`。所以当你关心的分支在某 Add 处汇入兄弟分支时，**兄弟分支也要标 FP16**（连同它的 weight/bias）。

## 5. 参考流水线（超分案例，已验证）

拓扑：
```
input → /anchor/net/Conv ─────────────► /add_op/Add → /clip_output/Clip → output
                                             ▲
/cnn/cnn.11/Clip_output_0 → /conv_last/Conv ─┘
```

保 FP16 集合：`/anchor/net/Conv`、`/conv_last/Conv`、`/add_op/Add`（其输出流向 output）。

### Step 0 — override JSON

```json
{
    "activation_encodings": {
        "/anchor/net/Conv_output_0":  [{"bitwidth": 16, "dtype": "float"}],
        "/conv_last/Conv_output_0":   [{"bitwidth": 16, "dtype": "float"}],
        "/add_op/Add_output_0":       [{"bitwidth": 16, "dtype": "float"}],
        "output":                     [{"bitwidth": 16, "dtype": "float"}]
    },
    "param_encodings": {
        "conv_last.weight":   [{"bitwidth": 16, "dtype": "float"}],
        "conv_last.bias":     [{"bitwidth": 16, "dtype": "float"}],
        "anchor.net.weight":  [{"bitwidth": 16, "dtype": "float"}],
        "anchor.net.bias":    [{"bitwidth": 16, "dtype": "float"}]
    }
}
```

### Step 1 — qairt-converter（overrides + float_bitwidth）

```bash
qairt-converter \
  --input_network  model.onnx \
  --output_path    model.dlc \
  --source_model_input_shape "input" "1,1,720,1280" \
  --quantization_overrides conv_last_fp16_overrides.json \
  --float_bitwidth 16
```

### Step 2 — qairt-quantizer（W8A16 baseline + float_bitwidth + float_bias_bitwidth）

```bash
qairt-quantizer \
  --input_dlc   model.dlc \
  --input_list  input_list.txt \
  --bias_bitwidth  32 \
  --act_bitwidth   16 \
  --weights_bitwidth 8 \
  --use_per_channel_quantization \
  --act_quantizer_calibration   enhanced \
  --param_quantizer_calibration enhanced \
  --float_bitwidth 16 \
  --float_bias_bitwidth 16 \
  --output_dlc  model_quant.dlc
```

### Step 3 — context binary（与标准编译一致）

```bash
qnn-context-binary-generator \
    --model       ${QNN_SDK_ROOT}/lib/x86_64-linux-clang/libQnnModelDlc.so \
    --backend     ${QNN_SDK_ROOT}/lib/x86_64-linux-clang/libQnnHtp.so \
    --dlc_path    model_quant.dlc \
    --binary_file model_serialized \
    --config_file config.json \
    --profiling_level basic \
    --enable_intermediate_outputs \
    --output_dir  bin_output
```

## 6. 决策工作流

1. 先跑纯 W8A16 baseline，测精度；
2. 精度不达标 → dump 逐层 cosine vs FP 参考（`--enable_intermediate_outputs`）；用 C3 定位 narrow point；
3. 找到"保 FP16 就能救精度"的最小 tensor 集合，从最后一个 conv/head 起，按需扩；
4. 走 ONNX 图：对每个选中节点，若任一**融合伙伴**（Add/Concat/Mul/Sub 的另一输入）是 INT，把它也加进去（或接受隐式 Convert 开销）；
5. 写 `overrides.json`（activation + param 两块都写）；
6. 重跑 Step 1+2+3；
7. 设备上用 `qnn-net-run` 验证，再比 cosine。

## 7. 常见错误

| 错误 | 修法 |
|---|---|
| 只标 activation，忘了 param | 两块都加，否则权重仍 INT8，该层不是真 FP16 |
| converter 漏 `--float_bitwidth 16` | 加；否则 DLC 存 FP32，quantizer 无法落实 FP16 意图 |
| quantizer 漏 `--float_bitwidth 16` | 加；否则 fallback float 默认 FP32 → 额外开销 |
| 漏 `--float_bias_bitwidth 16` | 加；否则 bias 默认 FP32，Add 处 dtype 不对称 |
| 残差 Add 只标一个输入 | 两个 producer（连同其 weight/bias）都标 |
| `"dtype":"int"` + `"bitwidth":16` 当成 FP16 | FP16 必须 `"dtype":"float"`；int+16 = INT16 |
| 值用裸 dict 而非 list | 包成 `[ ... ]`，schema 要求 list |
| tensor 名错（缺前导 `/`、大小写错） | 打开 Netron 复制**精确**输出 tensor 名 |

## 8. 红旗自检表——见到即停并复查

- `qnn-net-run` 日志在两个本该 FP16 的节点间出现额外 `Convert` 算子；
- HTP graph profiler 显示标记层仍以 INT 运行；
- 中间输出 dump 里本该 FP16 的 tensor 仍有 8-bit 量化台阶；
- `qairt-quantizer` 警告 `tensor '<name>' not found in graph` → 名字打错，修 JSON。

以上都意味着 **override JSON 没生效**——对着 ONNX 重核名字 + 复查两端 `--float_bitwidth 16`。

## 9. HTP FP16 激活的权重精度硬件约束（纯硬件可行性）

当把激活提到 FP16 时，权重能配哪种精度受 HTP 硬件限制：

| 方案 | `default_param_bw` | HTP 支持 | 说明 |
|------|-------------------|---------|------|
| **W8FP16** | 8 | ✅ | 精度最优，首选 |
| **W4FP16** | 4 | ✅ | 内存受限时 |
| **W16FP16** | 16 | ❌ | **不可用** |

> **HTP FP16 Conv2d 仅支持权重类型：`FP16`、`INT8(SFIXED_POINT_8)`、`INT4`。**
> **INT16 权重 + FP16 激活会被 HTP 直接拒绝**，报 `Unsupported datatypes: Conv2d in[1]=SFIXED_POINT_16`。

推论：做混精度时，若某敏感层要走"FP16 激活"，其权重要么 FP16、要么降到 INT8/INT4；**不要**指望 INT16 权重配 FP16 激活。

### INT16 encoding offset 硬约束 + 0xc26 故障指纹

- INT16 对称量化的某些 encoding 要求 **offset = -32768**（0x8000 语义槽位），若被工具链写成 0 或非法值，会在 context binary 生成阶段触发 **`0xc26`**（`Value -128` 类）失败。
- 见到 context-binary-generator 报 `0xc26` / `Value -128`：怀疑 encoding 的 offset/enc_type 非法（如 LPBQ offset 应保持规范值、INT16 对称 offset 槽位被改写）。这是"encoding 违反 HTP 硬约束"的指纹，不是模型逻辑 bug。

## 10. 何时不用

- 纯 FP16 编译（完全无 INT）→ 不写 overrides，两端只加 `--float_bitwidth 16`；
- AIMET QuantSim 产出的 encodings 已含 per-tensor dtype → 直接用 `--quantization_overrides` 喂那份 encodings（同 schema）；
- 首层 conv 的 per-channel 权重离群问题 → 走 bias-split pattern（C2，见 graph patterns）。

## 11. 与现有 SKILL 的关系

- 现有 `accuracy/SKILL.md` B6 只有粗档选项（改校准 / CLE / 整体升 W8A16 / 全保 FP16 / 接受），**缺"只把敏感层保 FP16、其余 INT8"的精细档**。本 SKILL 是**新增补充**：override JSON 契约 + 残差 dtype 对称 + 双端 float_bitwidth + HTP FP16 权重可行性表 + 0xc26 指纹，是 C3 定位后的落地工具，不与 B6 现有条目重复。
