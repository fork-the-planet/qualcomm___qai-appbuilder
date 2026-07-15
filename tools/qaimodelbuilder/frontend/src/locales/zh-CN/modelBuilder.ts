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
    conflictDetected: "检测到冲突 — 请选择处理策略",
    defaultPrecision: "App Builder 中的默认精度",
    generate: "生成 App Builder Pack",
    generating: "生成中...",
    import: "导入到 App Builder",
    importFailed: "导入失败",
    importSuccess: "已成功导入到 App Builder",
    noBinsHint: "output/ 下未发现任何精度产物，请先在 Model Builder 中至少构建一个精度。",
    noCandidates: "未发现可导入的 Pack 候选。请先在 Model Builder 中完成 Phase 7 生成候选包。",
    packGenerated: "Pack 已生成：{name}",
    policyBump: "升级版本号",
    policyCancel: "存在则取消",
    policyReplace: "替换已有",
    ready: "就绪",
    relativeTime: {
      hoursAgo: "{n} 小时前",
      justNow: "刚刚",
      minutesAgo: "{n} 分钟前",
    },
    repickPrecision: "重新选择精度",
    rollback: "回滚",
    rollbackSuccess: "已回滚到上一版本",
    scanBinsTitle: "在 output/ 下检测到的精度",
    sizeMB: "{n} MB",
    title: "导入到应用构建器",
    validate: "校验",
    validationPassed: "校验通过 — 可以导入",
    suggestedVersion: "建议的下一个版本号：{v}",
    variantsCount: "已选 {n} 个精度",
    noWorkspace: "当前对话未检测到模型工作区。请先在 Model Builder 中转换一个模型。",
    workspaceFound: "已找到模型工作区：",
    warn: {
      provenance_failed: "模型精度验证未通过 — REPORT.md 中未包含有效的 Cosine Similarity 数值。建议：运行推理验证（对比 ONNX 基线与 QNN 输出的余弦相似度），将结果写入 REPORT.md（格式：Cosine Similarity (ONNX vs FP16): 0.9999），然后重新导出。",
      provenance_not_found: "未找到模型验证记录（REPORT.md 中缺少 Cosine Similarity 数据）。如需消除此警告，请在 REPORT.md 中补充推理验证结果后重新导出。",
    },
  },
};

export default modelBuilder;
