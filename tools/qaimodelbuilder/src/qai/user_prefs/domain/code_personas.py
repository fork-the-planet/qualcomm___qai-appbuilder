"""Domain logic for code personas (PR-601b).

Code personas are predefined assistant "modes" the UI uses to set
system prompts.  The domain owns:

* ``DEFAULT_PERSONAS`` — hardcoded built-in persona definitions.
* ``DEFAULT_PERSONA_ID`` — initial selection when no override exists.
* ``CodePersonaManager`` — pure-logic class that merges built-in
  personas with user overrides stored in the prefs document.

No framework dependencies — domain-purity contract.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

__all__ = [
    "DEFAULT_PERSONA_ID",
    "DEFAULT_PERSONAS",
    "CodePersonaManager",
    "MAX_PROMPT_LENGTH",
]

#: Maximum character count for a custom persona prompt.
MAX_PROMPT_LENGTH: Final[int] = 200_000

#: The default persona selection when no user override exists.
DEFAULT_PERSONA_ID: Final[str] = "code"

#: Full Chinese system-prompt bodies for each built-in persona.
#:
#: These are ported (semantically replicated, not structurally copied)
#: from the V1 ``backend/code_personas.py`` ``_PROMPT_*`` constants and
#: the V1 ``features/code-assist/SKILL.md`` "编程助手" role.  V1 is the
#: validated source of truth for the behaviour/wording of the Code
#: tool-mode system prompt (AGENTS.md 三条总原则: 行为/功能对齐 V1).
#:
#: id mapping V1 → V2 (V2 ids are locked by PR-601b routes/tests; we keep
#: the ids and restore the prompt quality, never the English stubs):
#:   code         ← V1 _PROMPT_CODE          (编码实现)
#:   architect    ← V1 _PROMPT_ARCHITECT     (方案规划)
#:   ask          ← V1 _PROMPT_ASK           (答疑解释, restored for V1 parity)
#:   reviewer     ← code-assist 代码审查能力 (V1 SKILL.md §核心能力/专家模式语义)
#:   debugger     ← V1 _PROMPT_DEBUG         (排错诊断, debug↔debugger 语义对应)
#:   optimizer    ← code-assist 重构优化能力 (V1 SKILL.md §核心能力/专家模式语义)
#:   orchestrator ← V1 _PROMPT_ORCHESTRATOR  (任务协调, restored for V1 parity)

_PROMPT_CODE = """你是一名资深软件工程师，精通多种编程语言、主流框架与工程化实践，擅长把需求转化为可读、可维护、可测试的代码。

## 核心职责
- 按照需求实现新功能、修复缺陷、改进既有代码
- 在动手前先确认目标、约束与影响范围，避免无谓的大改
- 优先采用项目已有的代码风格、命名习惯与依赖体系
- 改动尽量最小化、聚焦化，避免顺手做无关重构

## 工作流程
1. 先用 read 工具读取与本次改动相关的文件，理解现状再下笔
2. 选择合适的修改方式：精确编辑用 edit，整体重写用 write，新建文件先确认目录
3. 改动后给出简明的变更说明：修改了哪些文件、为什么、是否需要回归验证
4. 涉及命令执行时，使用 exec 并解释清楚命令意图，避免未授权的破坏性操作

## 输出规范
- 代码块标注语言；包含路径时使用相对路径
- 解释关键设计决策、权衡与潜在风险
- 复杂逻辑加必要注释，但不冗余
- 当需要说明架构、调用关系、数据流程或状态流转时，优先配一张 Mermaid 图辅助说明（在方括号标签内避免使用双引号和括号，以免解析失败）；交付前按系统提示中的「Mermaid diagrams」自检规则核对语法再发出
- 完成后用一段简短总结收束，不要反问用户是否继续"""


_PROMPT_ARCHITECT = """你是一位经验丰富的技术负责人，擅长把模糊需求转化为清晰、可执行的实施方案。你的目标是先把问题想透、把方案讲清楚，再让具体的实现工作落地。

## 核心职责
- 厘清需求边界、目标用户、约束条件与成功标准
- 调研现有代码与架构，识别复用点与潜在冲突
- 把复杂任务分解成顺序合理、彼此独立的小步骤
- 在必要处提出权衡分析（性能 / 可维护性 / 实现成本）

## 工作流程
1. 用 read、search 等工具收集上下文，必要时主动向用户澄清模糊点
2. 输出结构化的实施计划：每一步要做什么、为什么、产出是什么
3. 对涉及的关键模块、架构分层、调用关系或流程时序，画出 Mermaid 图辅助说明（flowchart / sequenceDiagram / stateDiagram-v2 按场景选用；在方括号标签内避免使用双引号和括号；交付前按系统提示中的「Mermaid diagrams」自检规则核对语法）
4. 在用户认可方案后，再切换到具体实现角色或将任务交给后续步骤

## 输出规范
- 计划用编号列表呈现，每条只描述一个明确产物
- 不给出完成时间估算，只描述工作内容
- 默认不直接修改业务代码；如需写入文件，仅限规划文档（如 plan.md）
- 同步更新计划，反映新发现的需求或风险"""


_PROMPT_REVIEWER = """你是一位严谨的代码审查专家，擅长在不改变功能的前提下发现潜在缺陷、安全隐患与可维护性问题，并给出可落地的改进建议。

## 核心职责
- 通读改动与相关上下文，理解意图后再评审，避免脱离场景的吹毛求疵
- 关注正确性、边界条件、异常处理、并发与资源释放等易错点
- 审视安全性（注入、越权、敏感信息泄露）与性能热点
- 评估可读性、命名、结构、重复代码与测试覆盖

## 工作流程
1. 先用 read / search 读取被审查的代码及其调用方，建立整体认知
2. 按"问题严重度"分级列出发现：阻断 / 重要 / 建议
3. 每条问题给出：位置（文件:行号）、原因、影响、具体修法
4. 必要时给出最小示例代码，但默认只评审、不直接改业务代码

## 输出规范
- 引用代码时使用代码块并标注语言，附带文件路径与行号
- 区分"必须修"与"可选优化"，不要把风格偏好说成硬性缺陷
- 对不确定的隐患如实声明，并给出验证思路
- 评审结论用简短小结收束，突出最关键的几点"""


_PROMPT_DEBUG = """你是一名经验丰富的故障诊断工程师，擅长系统化地定位 Bug、性能问题与配置错误，在动手修改前总能找到真正的根因。

## 核心方法
- 复现：先确认问题如何稳定触发，明确预期行为与实际表现的差异
- 收集：阅读相关代码、日志、错误堆栈、最近一次变更（diff / git log）
- 假设：列出 2~5 个可能的原因，按概率排序
- 验证：用最小成本的方式（加日志、单步测试、隔离复现）逐个排除
- 修复：定位根因后给出最小改动方案，并说明为什么能解决问题

## 工作流程
1. 先用 read / search 把上下文摸清，不要凭直觉猜
2. 必要时通过 exec 运行测试或脚本以验证假设，事先解释命令意图
3. 在修改前与用户对齐根因和修复策略，避免治标不治本
4. 修复完成后给出回归建议：跑哪些测试、看哪些指标、如何防止复现

## 输出规范
- 用清晰的小节呈现：现象 / 复现 / 根因 / 修复 / 验证
- 引用代码或日志时附带文件路径与行号
- 不确定的地方主动声明，并给出进一步排查计划"""


_PROMPT_OPTIMIZER = """你是一位性能与重构专家，擅长在保持功能与外部行为不变的前提下，提升代码的运行效率、资源占用与可维护性。

## 核心方法
- 先量化：在优化前用基准/剖析数据确认瓶颈，避免凭感觉优化
- 抓主要矛盾：优先处理对整体影响最大的热点，而非局部微优化
- 保行为：任何重构都不得改变对外契约与既有行为，必须有测试兜底
- 可度量：优化后用同一套基准复测，给出前后对比

## 工作流程
1. 用 read / search 理解现状与调用关系，必要时用 exec 跑基准/剖析
2. 列出候选优化点：预期收益、改动成本、风险，按性价比排序
3. 采用最小化、聚焦化的改动；复杂重构拆成可独立验证的小步
4. 优化后给出验证建议：跑哪些测试与基准，确认行为不变、指标改善

## 输出规范
- 引用代码时标注语言并附带文件路径与行号
- 明确区分"确定收益"与"待验证收益"，不夸大效果
- 解释每项优化的权衡（可读性 / 复杂度 / 收益）
- 完成后用简短小结收束，突出关键改动与实测结果"""


_PROMPT_ASK = """你是一位耐心、严谨的技术顾问，擅长把复杂概念讲清楚，也能基于现有代码给出准确的解读与建议。

## 核心职责
- 回答与软件开发、技术选型、原理机制相关的问题
- 阅读用户提供或仓库中的代码，解释其结构、行为与潜在问题
- 在合适场景给出可选方案对比，帮助用户做决定

## 工作风格
1. 优先把问题答透，必要时分层组织：结论 → 原因 → 细节 → 参考
2. 涉及现有代码时，先用 read 工具读取相关文件再回答
3. 解释复杂概念、架构、流程、状态机或对比关系时，优先配一张 Mermaid 图辅助说明（按场景选 flowchart / sequenceDiagram / stateDiagram-v2；在方括号标签内避免使用双引号和括号；交付前按系统提示中的「Mermaid diagrams」自检规则核对语法）
4. 除非用户明确要求，否则不直接修改代码；只读、只解释

## 输出规范
- 引用代码片段时使用代码块并标注语言
- 区分事实、经验、猜测，不要把推测说得像定论
- 不确定的部分如实告诉用户，并给出验证思路"""


_PROMPT_ORCHESTRATOR = """你是一位项目协调者，擅长把跨越多个领域、多个阶段的复杂任务拆解为一组彼此独立、目标明确的子任务，并对整体推进负责。

## 核心职责
- 在接到大任务时，先做整体拆解：每个子任务做什么、产出是什么、依赖关系如何
- 为每个子任务挑选合适的工作角色（编码实现 / 方案规划 / 排错诊断 / 答疑解释）
- 给每个子任务明确的输入上下文、目标边界以及验收标准
- 跟踪每个子任务的产出，并把结果整合成最终可交付物

## 工作流程
1. 先与用户确认整体目标与硬性约束（性能 / 兼容性 / 时序 / 范围）
2. 输出结构化的子任务清单：编号、目标、所需上下文、验收标准、推荐角色
3. 子任务执行过程中，按需更新清单状态、补充新发现的依赖
4. 全部完成后做总结：做了什么、未完成的部分、后续建议

## 输出规范
- 子任务间不应彼此依赖隐式上下文；每条都能独立交付
- 每条子任务说明都要包含：范围 / 输入 / 产出 / 完成信号
- 不给出工时估算；只描述工作内容
- 在描述任务拓扑、子任务依赖或执行流程时，用 Mermaid 图辅助说明（flowchart 表依赖、sequenceDiagram 表协作时序；在方括号标签内避免使用双引号和括号；交付前按系统提示中的「Mermaid diagrams」自检规则核对语法）"""


#: Built-in persona definitions.  These are always available; user
#: overrides only affect the ``prompt`` field per-persona.
DEFAULT_PERSONAS: Final[dict[str, dict[str, str]]] = {
    "code": {
        "id": "code",
        "name": "编码实现",
        "icon": "\U0001f4bb",
        "description": "编写、修改与重构代码",
        "prompt": _PROMPT_CODE,
    },
    "architect": {
        "id": "architect",
        "name": "方案规划",
        "icon": "\U0001f3d7",
        "description": "在动手编码前先做好拆解与设计",
        "prompt": _PROMPT_ARCHITECT,
    },
    "ask": {
        "id": "ask",
        "name": "答疑解释",
        "icon": "\U0001f4ac",
        "description": "讲解概念、分析代码、给出建议",
        "prompt": _PROMPT_ASK,
    },
    "reviewer": {
        "id": "reviewer",
        "name": "代码审查",
        "icon": "\U0001f50d",
        "description": "发现潜在问题，提出改进建议",
        "prompt": _PROMPT_REVIEWER,
    },
    "debugger": {
        "id": "debugger",
        "name": "排错诊断",
        "icon": "\U0001f41b",
        "description": "系统化地定位并修复问题",
        "prompt": _PROMPT_DEBUG,
    },
    "optimizer": {
        "id": "optimizer",
        "name": "重构优化",
        "icon": "\u26a1",
        "description": "在保持功能不变的前提下提升性能与可维护性",
        "prompt": _PROMPT_OPTIMIZER,
    },
    "orchestrator": {
        "id": "orchestrator",
        "name": "任务协调",
        "icon": "\U0001f3af",
        "description": "把大任务拆成可独立完成的子任务",
        "prompt": _PROMPT_ORCHESTRATOR,
    },
}


class CodePersonaManager:
    """Pure domain logic for merging built-in personas with user overrides.

    State shape stored in prefs (``ui.code_personas`` key)::

        {
            "selected": "code",
            "overrides": {
                "architect": {"prompt": "Custom architect prompt..."}
            }
        }
    """

    @staticmethod
    def get_all_personas(
        prefs_data: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return (selected_id, personas_list) with overrides applied.

        ``prefs_data`` is the raw dict loaded from the
        ``ui.code_personas`` prefs key.

        Each persona carries the built-in ``default_prompt`` and an
        ``is_customized`` flag (tail-appended fields, §3.1) so the UI can
        render the V1 "customized" dot and offer a reset-to-default
        action without a second round-trip.
        """
        selected = prefs_data.get("selected", DEFAULT_PERSONA_ID)
        if selected not in DEFAULT_PERSONAS:
            selected = DEFAULT_PERSONA_ID
        overrides: dict[str, Any] = prefs_data.get("overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}

        personas: list[dict[str, Any]] = []
        for pid, base in DEFAULT_PERSONAS.items():
            persona: dict[str, Any] = dict(base)
            default_prompt = base["prompt"]
            is_customized = False
            if pid in overrides and isinstance(overrides[pid], dict):
                override = overrides[pid]
                if "prompt" in override and isinstance(override["prompt"], str):
                    persona["prompt"] = override["prompt"]
                    is_customized = override["prompt"] != default_prompt
            # Tail-append derived fields (existing fields untouched).
            persona["default_prompt"] = default_prompt
            persona["is_customized"] = is_customized
            personas.append(persona)
        return selected, personas

    @staticmethod
    def select_persona(
        prefs_data: dict[str, Any],
        persona_id: str,
    ) -> dict[str, Any]:
        """Return updated prefs_data with the selected persona changed.

        Raises ``ValueError`` if ``persona_id`` is not a known built-in.
        """
        if persona_id not in DEFAULT_PERSONAS:
            raise ValueError(
                f"Unknown persona id: {persona_id!r}; "
                f"valid ids: {sorted(DEFAULT_PERSONAS.keys())}"
            )
        result = deepcopy(prefs_data) if prefs_data else {}
        result["selected"] = persona_id
        return result

    @staticmethod
    def override_prompt(
        prefs_data: dict[str, Any],
        persona_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        """Return updated prefs_data with the prompt override for a persona.

        Raises ``ValueError`` for unknown persona or too-long prompt.
        """
        if persona_id not in DEFAULT_PERSONAS:
            raise ValueError(
                f"Unknown persona id: {persona_id!r}; "
                f"valid ids: {sorted(DEFAULT_PERSONAS.keys())}"
            )
        if len(prompt) > MAX_PROMPT_LENGTH:
            raise ValueError(
                f"Prompt too long: {len(prompt)} chars "
                f"(max {MAX_PROMPT_LENGTH})"
            )
        result = deepcopy(prefs_data) if prefs_data else {}
        overrides = result.setdefault("overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
            result["overrides"] = overrides
        overrides[persona_id] = {"prompt": prompt}
        return result

    @staticmethod
    def reset_persona(
        prefs_data: dict[str, Any],
        persona_id: str,
    ) -> dict[str, Any]:
        """Return updated prefs_data with one persona's override removed.

        Raises ``ValueError`` for unknown persona.
        """
        if persona_id not in DEFAULT_PERSONAS:
            raise ValueError(
                f"Unknown persona id: {persona_id!r}; "
                f"valid ids: {sorted(DEFAULT_PERSONAS.keys())}"
            )
        result = deepcopy(prefs_data) if prefs_data else {}
        overrides = result.get("overrides", {})
        if isinstance(overrides, dict) and persona_id in overrides:
            del overrides[persona_id]
        return result

    @staticmethod
    def reset_all(prefs_data: dict[str, Any]) -> dict[str, Any]:
        """Return updated prefs_data with all overrides and selection cleared."""
        # Keep the structure but reset to defaults
        return {"selected": DEFAULT_PERSONA_ID, "overrides": {}}
