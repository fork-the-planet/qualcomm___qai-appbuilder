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

const modelBuild = {
  buildFailed: "模型建構失敗",
  buildSuccess: "模型建構成功",
  building: "建構中...",
  contextLength: "上下文長度",
  outputDir: "輸出目錄",
  quantW16A16: "W16A16 - 全精度（16位元權重，16位元啟動）",
  quantW4A16: "W4A16 - 4位元權重，16位元啟動",
  quantW4A8: "W4A8 - 4位元權重，8位元啟動",
  quantW8A16: "W8A16 - 8位元權重，16位元啟動",
  quantW8A8: "W8A8 - 8位元權重和啟動",
  quantization: "量化",
  selectModel: "選擇要建構的模型",
  title: "模型建構",
};

export default modelBuild;
