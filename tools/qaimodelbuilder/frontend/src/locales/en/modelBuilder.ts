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
    conflictDetected: "Conflict detected — choose a policy",
    defaultPrecision: "Default in App Builder",
    generate: "Generate App Builder Pack",
    generating: "Generating...",
    import: "Import to App Builder",
    importFailed: "Import failed",
    importSuccess: "Successfully imported to App Builder",
    noBinsHint: "No precision binaries found in output/. Convert at least one variant first.",
    noCandidates: "No exportable Pack candidates found. Complete Phase 7 in Model Builder to generate one.",
    packGenerated: "Pack generated: {name}",
    policyBump: "Bump version",
    policyCancel: "Cancel if exists",
    policyReplace: "Replace existing",
    ready: "Ready",
    relativeTime: {
      hoursAgo: "{n} h ago",
      justNow: "just now",
      minutesAgo: "{n} min ago",
    },
    repickPrecision: "Re-pick precision",
    rollback: "Rollback",
    rollbackSuccess: "Rolled back to previous version",
    scanBinsTitle: "Variants found in output/",
    sizeMB: "{n} MB",
    title: "Promote to App Builder",
    validate: "Validate",
    validationPassed: "Validation passed — ready to import",
    suggestedVersion: "Suggested next version: {v}",
    variantsCount: "{n} variants selected",
    noWorkspace:
      "No model workspace detected in this conversation. Use Model Builder to convert a model first.",
    workspaceFound: "Model workspace found:",
    warn: {
      provenance_failed: "Model accuracy validation not passed — REPORT.md does not contain valid Cosine Similarity values. Suggestion: run inference validation (compare ONNX baseline vs QNN output cosine similarity), write results to REPORT.md (format: Cosine Similarity (ONNX vs FP16): 0.9999), then re-export.",
      provenance_not_found: "Validation record not found (REPORT.md missing Cosine Similarity data). To resolve: add inference validation results to REPORT.md and re-export.",
    },
  },
};

export default modelBuilder;
