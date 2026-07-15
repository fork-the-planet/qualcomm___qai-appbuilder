/**
 * Pinia factory.
 *
 * S5 PR-050: only the Pinia instance lives here. Individual stores
 * sit in sibling files (`ui.ts`, `chatTabs.ts` PR-054, …).
 */
import { createPinia, type Pinia } from "pinia";

export function createAppPinia(): Pinia {
  return createPinia();
}
