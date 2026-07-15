/**
 * rAF-throttled per-tab tool-output buffer (WIRE-tools).
 *
 * V1 truth: `useChat.js:1041` coalesced the high-frequency exec stdout/stderr
 * `{type:"output"}` SSE frames through a `_pendingText` buffer that was
 * flushed to the DOM on the next `requestAnimationFrame` (`_flushOutputToUI`),
 * so a chatty command (thousands of lines/sec) did not trigger a Vue re-render
 * per line — it batched all deltas seen within one frame into a single store
 * mutation.
 *
 * In V2 the equivalent live increments arrive as `partial=true` `tool_result`
 * SSE frames (see `frameHandlers.handleToolResult`). Applying every one of
 * them straight to the Pinia store would re-render the tool card on each line.
 * This composable re-implements V1's batching as a small, framework-light
 * utility keyed by `tabId`: callers `push(tabId, delta)` for each partial and
 * register a `flush(tabId, mergedText)` sink that runs at most once per
 * animation frame with the concatenation of all deltas buffered since the last
 * flush.
 *
 * It is intentionally store-agnostic (no Pinia import) so it stays unit-
 * testable and reusable; the chat store/transport wires `flush` to a single
 * `appendToolOutput`-style mutation. When `requestAnimationFrame` is
 * unavailable (SSR / tests) it falls back to a microtask via `queueMicrotask`
 * / `setTimeout(0)` so the same batching contract holds.
 */

export type ToolOutputFlushSink = (tabId: string, mergedDelta: string) => void;

export interface ToolOutputThrottle {
  /** Buffer one partial delta for `tabId`; schedules a flush if needed. */
  push: (tabId: string, delta: string) => void;
  /** Force an immediate synchronous flush of any pending deltas for `tabId`
   *  (or all tabs when `tabId` is omitted). Used at stream end so the final
   *  buffered text is not lost when the rAF is cancelled. */
  flushNow: (tabId?: string) => void;
  /** Drop any pending buffer for `tabId` without flushing (stream aborted). */
  cancel: (tabId: string) => void;
  /** Drop everything + cancel the scheduled frame (teardown). */
  dispose: () => void;
}

type RafHandle = number | ReturnType<typeof setTimeout>;

function scheduleFrame(cb: () => void): RafHandle {
  if (typeof requestAnimationFrame === "function") {
    return requestAnimationFrame(() => cb());
  }
  // SSR / test fallback — preserve the "batch then flush once" contract.
  return setTimeout(cb, 0);
}

function cancelFrame(handle: RafHandle | null): void {
  if (handle === null) return;
  if (typeof cancelAnimationFrame === "function" && typeof handle === "number") {
    cancelAnimationFrame(handle);
    return;
  }
  clearTimeout(handle as ReturnType<typeof setTimeout>);
}

/**
 * Create a throttle instance bound to a `flush` sink.
 *
 * @param flush called (at most once per animation frame, per tab) with the
 *   merged text accumulated since the previous flush. The sink is expected to
 *   append `mergedDelta` to the active tool card's output for `tabId`.
 */
export function useToolOutputThrottle(
  flush: ToolOutputFlushSink,
): ToolOutputThrottle {
  // tabId -> buffered delta text not yet flushed.
  const pending = new Map<string, string>();
  let frame: RafHandle | null = null;

  function drain(): void {
    frame = null;
    if (pending.size === 0) return;
    // Snapshot + clear before invoking the sink so re-entrant `push` calls
    // (a flush sink that synchronously triggers more deltas) start a fresh
    // buffer + schedule a new frame rather than mutating the map mid-drain.
    const batch = Array.from(pending.entries());
    pending.clear();
    for (const [tabId, text] of batch) {
      if (text !== "") flush(tabId, text);
    }
  }

  function ensureScheduled(): void {
    if (frame === null) frame = scheduleFrame(drain);
  }

  return {
    push(tabId, delta) {
      if (delta === "") return;
      pending.set(tabId, (pending.get(tabId) ?? "") + delta);
      ensureScheduled();
    },
    flushNow(tabId) {
      if (tabId === undefined) {
        drain();
        return;
      }
      const text = pending.get(tabId);
      if (text === undefined) return;
      pending.delete(tabId);
      if (text !== "") flush(tabId, text);
    },
    cancel(tabId) {
      pending.delete(tabId);
    },
    dispose() {
      pending.clear();
      cancelFrame(frame);
      frame = null;
    },
  };
}
