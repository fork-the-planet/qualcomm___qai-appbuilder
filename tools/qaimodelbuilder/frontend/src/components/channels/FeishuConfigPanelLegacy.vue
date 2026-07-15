<script setup lang="ts">
/**
 * FeishuConfigPanelLegacy — Legacy wrapper that delegates to FeishuConfigPanel.
 *
 * Retained for backward compatibility with call sites that reference the
 * legacy component name. Simply renders the real FeishuConfigPanel.
 */
import { useI18n } from "vue-i18n";
import FeishuConfigPanel from "./FeishuConfigPanel.vue";

const { t } = useI18n();
</script>

<template>
  <div
    class="qai-feishu-config-legacy"
    data-testid="feishu-config-panel-legacy"
  >
    <p class="qai-feishu-config-legacy__notice">
      {{ t("channels.legacy_notice", "This view uses the legacy component path. Please update to FeishuConfigPanel.") }}
    </p>
    <FeishuConfigPanel />
  </div>
</template>

<style scoped>
.qai-feishu-config-legacy {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.qai-feishu-config-legacy__notice {
  margin: 0;
  padding: var(--space-2);
  font-size: var(--text-xs);
  color: var(--warning, #e65100);
  background: #fff3e0;
  border-radius: 4px;
}
</style>
