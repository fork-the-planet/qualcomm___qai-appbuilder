/**
 * `useCsrfRecovery` — automatic CSRF token refresh on 403.
 *
 * S7.5 L7 PR-710.
 *
 * When a request fails with ForbiddenApiError and the response indicates
 * a CSRF token mismatch, this composable triggers a token refresh by
 * re-fetching any GET endpoint (which re-sets the qai_csrf cookie) and
 * provides a retry mechanism.
 */
import { ref } from "vue";

import { apiJson, ForbiddenApiError } from "@/api";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface CsrfRecoveryResult {
  recovered: boolean;
}

// ─── Composable ──────────────────────────────────────────────────────────────

export function useCsrfRecovery() {
  const recovering = ref(false);

  /**
   * Determines if an error is a CSRF mismatch (403 with csrf-related code).
   */
  function isCsrfMismatch(error: unknown): boolean {
    if (!(error instanceof ForbiddenApiError)) return false;
    const code = error.code;
    return (
      code === "csrf_mismatch" ||
      code === "csrf_missing" ||
      code === "security.csrf_failed" ||
      error.message.toLowerCase().includes("csrf")
    );
  }

  /**
   * Refresh the CSRF cookie by making a lightweight GET request.
   * The server sets the qai_csrf cookie on any successful response.
   */
  async function refreshCsrfToken(): Promise<boolean> {
    recovering.value = true;
    try {
      // A lightweight GET that always succeeds and refreshes cookies
      await apiJson("GET", "/api/system/build-info");
      return true;
    } catch {
      return false;
    } finally {
      recovering.value = false;
    }
  }

  /**
   * Wraps an async operation with CSRF recovery. If the operation fails
   * due to CSRF mismatch, refreshes the token and retries once.
   */
  async function withCsrfRecovery<T>(
    operation: () => Promise<T>,
  ): Promise<T> {
    try {
      return await operation();
    } catch (error) {
      if (isCsrfMismatch(error)) {
        const refreshed = await refreshCsrfToken();
        if (refreshed) {
          // Retry the operation once after token refresh
          return await operation();
        }
      }
      throw error;
    }
  }

  return {
    recovering,
    isCsrfMismatch,
    refreshCsrfToken,
    withCsrfRecovery,
  };
}
