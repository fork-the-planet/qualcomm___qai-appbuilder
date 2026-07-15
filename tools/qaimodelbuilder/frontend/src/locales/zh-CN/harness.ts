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
    compressing: "正在压缩上下文...",
    interrupted: "操作已被用户中断",
    maxIterations: "已达最大迭代次数",
  },
  config: {
    agent: {
      autoCompress: {
        desc: "接近 token 上限时自动压缩上下文",
      },
      autoTitle: {
        desc: "自动生成对话标题",
      },
      experienceExtraction: {
        desc: "任务成功后自动提取可复用经验",
      },
      maxIterations: {
        desc: "Agentic loop 最大工具调用轮次",
      },
      title: "Agent 循环",
    },
    security: {
      smartApproval: {
        label: "智能审批",
        desc: "使用 LLM 预评估工具调用风险（低风险自动放行，高风险自动拒绝）",
      },
    },
  },
  experiences: {
    category: "分类",
    deleteConfirm: "确定删除此经验？",
    deleted: "经验已删除",
    empty: "暂无保存的经验",
    insights: "经验洞察",
    summary: "摘要",
    title: "经验库",
  },
  guardrail: {
    blocked: "工具调用被防护栏拦截",
    warn: "防护栏警告",
  },
  search: {
    noResults: "未找到匹配的对话",
    placeholder: "搜索对话记录...",
    searching: "搜索中...",
  },
  stopGeneration: {
    tooltip: "停止当前 AI 响应",
  },
  stopped: "已由用户停止生成",
};

export default harness;
