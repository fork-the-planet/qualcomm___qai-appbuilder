<!--
 * PipelineCard.vue — MB Pro pipeline/v1 dependency graph card.
 *
 * Rendered inside the assistant message's tool-call area (ChatMessageList →
 * ToolCallList) in place of the generic ``ToolExecPanel`` whenever
 * ``call.toolName === "show_pipeline"`` — same pattern as ConfigReviewCard
 * and StepProgressCard.
 *
 * The upstream ``show_pipeline`` handler in modelbuilder_pro.py returns a
 * pre-rendered Markdown string (not raw JSON). It looks like:
 *
 *   🧬 已校验流程图 pipeline/v1 (jobs/xxx/pipeline.json ...)
 *
 *   ## 已校验流程图（pipeline/v1，4 step / 4 边 …）
 *     ▶ stage1  (main.py)  ↑产: outputs/model.pt
 *     ▶ stage2  (run_ar128.sh)
 *   【依赖边（写→读，file:line 已核真有读写动词）】
 *     stage1 → stage2  ::outputs/... [写 file:L / 读 file:L]
 *
 * We render it with the project's existing ``renderMarkdown`` so the
 * section heading, list structure, and code-like paths display nicely —
 * no custom parser needed, zero risk of format regressions.
-->
<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "@/composables/markdown";

interface Props {
  result?: string;
}

const props = withDefaults(defineProps<Props>(), { result: "" });

const html = computed<string>(() =>
  props.result ? renderMarkdown(props.result) : "",
);

const isEmpty = computed(() => !props.result?.trim());
</script>

<template>
  <section class="pipeline-card" data-testid="pipeline-card">
    <header class="pipeline-card__header">
      <span class="pipeline-card__icon" aria-hidden="true">🧬</span>
      <span class="pipeline-card__title">Pipeline / 依赖图</span>
    </header>

    <div v-if="isEmpty" class="pipeline-card__empty">（暂无 pipeline 流程图）</div>

    <!-- eslint-disable-next-line vue/no-v-html -->
    <div
      v-else
      class="pipeline-card__body markdown-body"
      v-html="html"
    />
  </section>
</template>

<style scoped>
.pipeline-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  margin: 6px 0;
  border-radius: 8px;
  border: 1px solid var(--color-border, rgba(0, 0, 0, 0.12));
  background: var(--color-surface, rgba(255, 255, 255, 0.6));
}

.pipeline-card__header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text, inherit);
}

.pipeline-card__icon {
  font-size: 16px;
  line-height: 1;
}

.pipeline-card__empty {
  font-size: 12px;
  color: var(--color-text-muted, #6b7280);
  font-style: italic;
}

.pipeline-card__body {
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
}

/* Override markdown-body defaults to keep the card compact */
.pipeline-card__body :deep(h2) {
  font-size: 13px;
  font-weight: 600;
  margin: 4px 0 6px;
  color: var(--color-text, inherit);
}

.pipeline-card__body :deep(p) {
  margin: 4px 0;
}

.pipeline-card__body :deep(pre),
.pipeline-card__body :deep(code) {
  font-size: 11px;
  background: var(--color-surface, rgba(0, 0, 0, 0.04));
  padding: 2px 4px;
  border-radius: 3px;
}
</style>
