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
    compressing: "正在壓縮上下文...",
    interrupted: "操作已被使用者中斷",
    maxIterations: "已達最大迭代次數",
  },
  config: {
    agent: {
      autoCompress: {
        desc: "接近 token 上限時自動壓縮上下文",
      },
      autoTitle: {
        desc: "自動生成對話標題",
      },
      experienceExtraction: {
        desc: "任務成功後自動提取可複用經驗",
      },
      maxIterations: {
        desc: "Agentic loop 最大工具調用輪次",
      },
      title: "Agent 循環",
    },
    security: {
      smartApproval: {
        label: "智慧審批",
        desc: "使用 LLM 預評估工具調用風險（低風險自動放行，高風險自動拒絕）",
      },
    },
  },
  experiences: {
    category: "分類",
    deleteConfirm: "確定刪除此經驗？",
    deleted: "經驗已刪除",
    empty: "暫無儲存的經驗",
    insights: "經驗洞察",
    summary: "摘要",
    title: "經驗庫",
  },
  guardrail: {
    blocked: "工具調用被防護欄攔截",
    warn: "防護欄警告",
  },
  search: {
    noResults: "未找到匹配的對話",
    placeholder: "搜尋對話記錄...",
    searching: "搜尋中...",
  },
  stopGeneration: {
    tooltip: "停止當前 AI 回應",
  },
  stopped: "已由使用者停止生成",
};

export default harness;
