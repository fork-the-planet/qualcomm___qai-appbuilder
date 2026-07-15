/**
 * `useVersions` — package update checking for notification badges.
 *
 * S7.5 L7 PR-703.
 *
 * Checks the backend for available package updates and exposes a computed
 * `updateAvailable` flag for use in notification badges.
 *
 * Endpoint (TestClient-verified):
 *   GET /api/versions/available → { updates: AvailableUpdate[], checked_at }
 *
 * NOTE: the V2 Clean-Cutover backend has no single application-level
 * `current_version`/`latest_version`; versions are tracked per package.
 * The previously-used `/api/system/versions` endpoint does NOT exist
 * (returns 404) — it must never be reintroduced.
 */
import { ref, computed, type Ref, type ComputedRef } from "vue";
import { useI18n } from "vue-i18n";

import { apiJson } from "@/api";
import { useToastStore } from "@/stores/toast";

// ─── Types ───────────────────────────────────────────────────────────────────

/** A single available package update — mirrors backend `AvailableUpdate`. */
export interface AvailableUpdate {
  name: string;
  current_version: string;
  latest_version: string;
  update_type: string;
}

/** `GET /api/versions/available` response shape. */
export interface AvailableVersionsResponse {
  updates: AvailableUpdate[];
  checked_at: string;
}

// ─── Composable ──────────────────────────────────────────────────────────────

export function useVersions() {
  const updates: Ref<AvailableUpdate[]> = ref([]);
  const checkedAt: Ref<string> = ref("");
  const loading: Ref<boolean> = ref(false);

  const toast = useToastStore();
  const { t } = useI18n();

  /** True when the backend reports at least one available package update. */
  const updateAvailable: ComputedRef<boolean> = computed(
    () => updates.value.length > 0,
  );

  async function checkVersions(): Promise<void> {
    loading.value = true;
    try {
      const res = await apiJson<AvailableVersionsResponse>("GET", "/api/versions/available");
      updates.value = Array.isArray(res.updates) ? res.updates : [];
      checkedAt.value = res.checked_at ?? "";
    } catch (e) {
      toast.push({
        id: crypto.randomUUID(),
        kind: "error",
        message: `${t("service.versionCheckFailed", "Failed to check versions")}: ${(e as Error).message}`,
        timeoutMs: 5000,
      });
    } finally {
      loading.value = false;
    }
  }

  return {
    updates,
    checkedAt,
    updateAvailable,
    loading,
    checkVersions,
  };
}
