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

const modelBuilder = {
  promote: {
    conflictDetected: "檢測到衝突 — 請選擇處理策略",
    defaultPrecision: "App Builder 中的預設精度",
    generate: "產生 App Builder Pack",
    generating: "產生中...",
    import: "匯入到 App Builder",
    importFailed: "匯入失敗",
    importSuccess: "已成功匯入到 App Builder",
    noBinsHint: "output/ 下未發現任何精度產物，請先在 Model Builder 中至少構建一個精度。",
    noCandidates: "未發現可匯入的 Pack 候選。請先在 Model Builder 中完成 Phase 7 生成候選包。",
    packGenerated: "Pack 已生成：{name}",
    policyBump: "升級版本號",
    policyCancel: "存在則取消",
    policyReplace: "替換已有",
    ready: "就緒",
    relativeTime: {
      hoursAgo: "{n} 小時前",
      justNow: "剛剛",
      minutesAgo: "{n} 分鐘前",
    },
    repickPrecision: "重新選擇精度",
    rollback: "回滾",
    rollbackSuccess: "已回滾到上一版本",
    scanBinsTitle: "在 output/ 下偵測到的精度",
    sizeMB: "{n} MB",
    title: "匯入到應用構建器",
    validate: "校驗",
    validationPassed: "校驗通過 — 可以匯入",
    suggestedVersion: "建議的下一個版本號：{v}",
    variantsCount: "已選 {n} 個精度",
    noWorkspace: "當前對話未偵測到模型工作區。請先在 Model Builder 中轉換一個模型。",
    workspaceFound: "已找到模型工作區：",
    warn: {
      provenance_failed: "模型精度驗證未通過 — REPORT.md 中未包含有效的 Cosine Similarity 數值。建議：執行推理驗證（對比 ONNX 基線與 QNN 輸出的餘弦相似度），將結果寫入 REPORT.md（格式：Cosine Similarity (ONNX vs FP16): 0.9999），然後重新匯出。",
      provenance_not_found: "未找到模型驗證記錄（REPORT.md 中缺少 Cosine Similarity 資料）。如需消除此警告，請在 REPORT.md 中補充推理驗證結果後重新匯出。",
    },
  },
};

export default modelBuilder;
