/**
 * `useMarkdown` — reactive wrapper around `renderMarkdown`.
 *
 * S7.5 L8 PR-804.
 *
 * Given a reactive markdown source (Ref<string> or computed source), this
 * composable returns a `html` ref whose value is the sanitised HTML
 * string. SFCs typically bind it as:
 *
 *   const text = ref(...)
 *   const { html } = useMarkdown(text)
 *   <div v-html="html" />
 *
 * Re-rendering only happens when the source changes; the actual marked
 * + hljs + DOMPurify pass is fast enough (~ 1 ms / 1 KB) that we don't
 * need to debounce.
 */
import { computed, type ComputedRef, type MaybeRef, unref } from "vue";

import { renderMarkdown, type RenderMarkdownOptions } from "./markdown";

export interface UseMarkdownReturn {
  readonly html: ComputedRef<string>;
}

export function useMarkdown(
  source: MaybeRef<string>,
  opts: RenderMarkdownOptions = {},
): UseMarkdownReturn {
  const html = computed<string>(() => renderMarkdown(unref(source), opts));
  return { html };
}
