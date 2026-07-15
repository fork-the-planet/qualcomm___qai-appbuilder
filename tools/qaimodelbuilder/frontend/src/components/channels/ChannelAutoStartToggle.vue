<script setup lang="ts">
/**
 * ChannelAutoStartToggle — per-instance auto-start checkbox (V1 parity).
 *
 * Binds to `config.auto_start` for one channel instance and persists
 * immediately via POST `/api/{kind}/config` (kind_specific is preserved
 * by the server-side merge, so toggling auto-start never clobbers other
 * config keys).
 *
 * Owns its own `useChannelSettings(kind, instanceId)` instance.
 */
import { onMounted } from "vue";
import { useI18n } from "vue-i18n";

import { useToastStore } from "@/stores/toast";
import { useChannelSettings, type ChannelKind } from "@/composables/useChannelSettings";

const props = defineProps<{
  kind: ChannelKind;
  instanceId: string;
}>();

const { t } = useI18n();
const toast = useToastStore();

const { autoStart, saving, loadConfig, saveConfig } = useChannelSettings(
  props.kind,
  props.instanceId,
);

async function onToggle(): Promise<void> {
  const ok = await saveConfig();
  if (!ok) {
    // Revert the optimistic flip on failure.
    autoStart.value = !autoStart.value;
    toast.push({
      id: crypto.randomUUID(),
      kind: "error",
      message: t("channels.autoStartSaveFailed", "Failed to update auto-start"),
      timeoutMs: 5000,
    });
  }
}

onMounted(loadConfig);
</script>

<template>
  <label
    class="channel-autostart"
    :data-testid="`${kind}-autostart-${instanceId}`"
  >
    <input
      v-model="autoStart"
      type="checkbox"
      :disabled="saving"
      :data-testid="`${kind}-autostart-checkbox-${instanceId}`"
      @change="onToggle"
    />
    <span>{{ t("channels.autoStart", "Auto-start this channel on service start") }}</span>
  </label>
</template>

<style scoped>
.channel-autostart {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-sm, 0.875rem);
  cursor: pointer;
}
</style>
