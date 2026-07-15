// =============================================================================
// i18n locale sub-file — 手工维护，UTF-8（无 BOM）。
//
// 真值源说明：本项目 i18n 已无自动生成管道（旧的 _L8-locale-gen.py 与
// _migrated/*.json 均未保留在仓库）。因此本文件就是当前唯一真值源，
// 必须手工维护。修改时严守 AGENTS.md §3.10 文件编码铁律（UTF-8，禁止
// GBK/CP437 等非 UTF-8 编码，禁止双重编码损坏）。
//
// 类型：en/{ns}.ts 经主入口 en.ts 组装后由 typeof 推导出 MessageSchema；
// zh-CN / zh-TW 的同名子文件须保持与 en 完全一致的 key 结构（由 locale
// parity 测试 + tsc 强制）。
// =============================================================================

const harness = {
  agent: {
    compressing: "Compressing context...",
    interrupted: "Operation interrupted by user",
    maxIterations: "Maximum iterations reached",
  },
  config: {
    agent: {
      autoCompress: {
        desc: "Automatically compress context when approaching token limit",
      },
      autoTitle: {
        desc: "Automatically generate conversation titles",
      },
      experienceExtraction: {
        desc: "Auto-extract reusable experiences after successful tasks",
      },
      maxIterations: {
        desc: "Maximum tool call rounds in agentic loop",
      },
      title: "Agent Loop",
    },
    security: {
      smartApproval: {
        label: "Smart Approval",
        desc: "Use LLM to pre-evaluate tool call risks (auto-approve low risk, auto-deny high risk)",
      },
    },
  },
  experiences: {
    category: "Category",
    deleteConfirm: "Delete this experience?",
    deleted: "Experience deleted",
    empty: "No experiences saved yet",
    insights: "Insights",
    summary: "Summary",
    title: "Experiences",
  },
  guardrail: {
    blocked: "Tool call blocked by guardrail",
    warn: "Guardrail warning",
  },
  search: {
    noResults: "No matching conversations found",
    placeholder: "Search conversations...",
    searching: "Searching...",
  },
  stopGeneration: {
    tooltip: "Stop the current AI response",
  },
  stopped: "Generation stopped by user",
};

export default harness;
