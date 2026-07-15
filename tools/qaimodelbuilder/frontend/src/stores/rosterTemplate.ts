/**
 * Roster-template store — reusable multi-Agent discussion "teams".
 *
 * Thin CRUD client for the conversation-INDEPENDENT roster-template library:
 *
 *   GET    /api/chat/roster-templates
 *   POST   /api/chat/roster-templates
 *   PATCH  /api/chat/roster-templates/{id}
 *   DELETE /api/chat/roster-templates/{id}
 *   POST   /api/chat/roster-templates/{id}/apply   (instantiate into a conversation)
 *
 * A roster template is a named bundle of role definitions (display_name /
 * model_id / persona / config) a user can preview + import into any
 * conversation, so a roster need not be rebuilt every time. Built-in presets
 * (``is_builtin``) are factory-seeded and read-only.
 *
 * PURE V2 enhancement (V1 has no multi-Agent discussion). The store owns the
 * wire shapes + HTTP only; it maps snake_case wire ↔ camelCase view models.
 */
import { defineStore } from "pinia";
import { ref } from "vue";
import { apiJson } from "@/api";

// ---------------------------------------------------------------------------
// Wire shapes (snake_case — backend contract)
// ---------------------------------------------------------------------------

interface RosterMemberConfigWire {
  allowed_tools?: string[] | null;
  enabled_skills?: string[] | null;
  color?: number | string | null;
}

interface RosterMemberWire {
  display_name: string;
  model_id?: string | null;
  persona?: string | null;
  config?: RosterMemberConfigWire | null;
}

interface RosterTemplateWire {
  id: string;
  name: string;
  description: string;
  members: RosterMemberWire[];
  is_builtin: boolean;
  default_mode_id?: string | null;
  cloned_from_id?: string | null;
  created_at: string;
  updated_at: string;
}

interface RosterTemplateListWire {
  items?: RosterTemplateWire[] | null;
}

interface ApplyResponseWire {
  conversation_id: string;
  participant_ids: string[];
  members_added: number;
  applied_mode_id?: string | null;
  applied_mode_name?: string | null;
}

// ---------------------------------------------------------------------------
// View models (camelCase)
// ---------------------------------------------------------------------------

export interface RosterTemplateMemberView {
  displayName: string;
  modelId?: string;
  persona?: string;
  allowedTools: string[];
  enabledSkills: string[];
  color?: number;
}

export interface RosterTemplateView {
  id: string;
  name: string;
  description: string;
  members: RosterTemplateMemberView[];
  isBuiltin: boolean;
  /** Optional bound default collaboration mode (chat_mode_template id). */
  defaultModeId?: string;
  /** Source template id when this is a clone (esp. a clone of a factory preset);
   *  "" / undefined = not a clone. Reset is only meaningful when set. */
  clonedFromId?: string;
}

/** Body for create / update (id is route/response only). */
export interface RosterTemplateInput {
  name: string;
  description: string;
  members: RosterTemplateMemberView[];
  /** Optional bound default collaboration mode; "" / undefined = no binding. */
  defaultModeId?: string;
}

/** Result of applying a roster template to a conversation. */
export interface RosterApplyResult {
  membersAdded: number;
  /** Non-null only when a bound default mode resolved + was selected. */
  appliedModeId?: string;
  appliedModeName?: string;
}

// ---------------------------------------------------------------------------
// Wire ↔ view-model mappers
// ---------------------------------------------------------------------------

function wireToMember(w: RosterMemberWire): RosterTemplateMemberView {
  return {
    displayName: w.display_name,
    ...(w.model_id != null && w.model_id !== "" ? { modelId: w.model_id } : {}),
    ...(w.persona != null && w.persona !== "" ? { persona: w.persona } : {}),
    allowedTools: Array.isArray(w.config?.allowed_tools)
      ? [...(w.config?.allowed_tools as string[])]
      : [],
    enabledSkills: Array.isArray(w.config?.enabled_skills)
      ? [...(w.config?.enabled_skills as string[])]
      : [],
    ...(typeof w.config?.color === "number" ? { color: w.config?.color } : {}),
  };
}

function wireToTemplate(w: RosterTemplateWire): RosterTemplateView {
  return {
    id: w.id,
    name: w.name,
    description: w.description,
    members: Array.isArray(w.members) ? w.members.map(wireToMember) : [],
    isBuiltin: w.is_builtin === true,
    ...(w.default_mode_id != null && w.default_mode_id !== ""
      ? { defaultModeId: w.default_mode_id }
      : {}),
    ...(w.cloned_from_id != null && w.cloned_from_id !== ""
      ? { clonedFromId: w.cloned_from_id }
      : {}),
  };
}

function memberToWire(m: RosterTemplateMemberView): Record<string, unknown> {
  return {
    display_name: m.displayName,
    ...(m.modelId !== undefined && m.modelId !== "" ? { model_id: m.modelId } : {}),
    ...(m.persona !== undefined && m.persona !== "" ? { persona: m.persona } : {}),
    config: {
      allowed_tools: m.allowedTools,
      enabled_skills: m.enabledSkills,
      ...(m.color !== undefined ? { color: m.color } : {}),
    },
  };
}

function inputToWire(input: RosterTemplateInput): Record<string, unknown> {
  return {
    name: input.name,
    description: input.description,
    members: input.members.map(memberToWire),
    // Always sent so PATCH can both set and CLEAR (null) the bound mode;
    // empty string maps to null (no binding).
    default_mode_id:
      input.defaultModeId !== undefined && input.defaultModeId !== ""
        ? input.defaultModeId
        : null,
  };
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useRosterTemplateStore = defineStore("rosterTemplate", () => {
  /** Cached library (built-ins first, then user saved). */
  const templates = ref<RosterTemplateView[]>([]);
  const loaded = ref(false);

  async function fetchAll(): Promise<RosterTemplateView[]> {
    const resp = await apiJson<RosterTemplateListWire>(
      "GET",
      "/api/chat/roster-templates",
    );
    const items = Array.isArray(resp?.items) ? resp.items : [];
    templates.value = items.map(wireToTemplate);
    loaded.value = true;
    return templates.value;
  }

  async function create(input: RosterTemplateInput): Promise<RosterTemplateView> {
    const w = await apiJson<RosterTemplateWire>(
      "POST",
      "/api/chat/roster-templates",
      inputToWire(input),
    );
    const view = wireToTemplate(w);
    templates.value = [...templates.value, view];
    return view;
  }

  async function update(
    id: string,
    input: RosterTemplateInput,
  ): Promise<RosterTemplateView> {
    const w = await apiJson<RosterTemplateWire>(
      "PATCH",
      `/api/chat/roster-templates/${encodeURIComponent(id)}`,
      inputToWire(input),
    );
    const view = wireToTemplate(w);
    templates.value = templates.value.map((tpl) => (tpl.id === id ? view : tpl));
    return view;
  }

  async function remove(id: string): Promise<void> {
    await apiJson("DELETE", `/api/chat/roster-templates/${encodeURIComponent(id)}`);
    templates.value = templates.value.filter((tpl) => tpl.id !== id);
  }

  /** Apply (import) a template's members into a conversation as named agents.
   *  When the team carries a bound default mode that resolves, it is also
   *  selected on the conversation (reported back via ``appliedMode*``). */
  async function applyToConversation(
    id: string,
    conversationId: string,
  ): Promise<RosterApplyResult> {
    const resp = await apiJson<ApplyResponseWire, { conversation_id: string }>(
      "POST",
      `/api/chat/roster-templates/${encodeURIComponent(id)}/apply`,
      { conversation_id: conversationId },
    );
    return {
      membersAdded: resp.members_added,
      ...(resp.applied_mode_id != null && resp.applied_mode_id !== ""
        ? { appliedModeId: resp.applied_mode_id }
        : {}),
      ...(resp.applied_mode_name != null && resp.applied_mode_name !== ""
        ? { appliedModeName: resp.applied_mode_name }
        : {}),
    };
  }

  /** Clone any template (factory preset or own) into a NEW non-builtin copy
   *  (records cloned_from_id server-side). Returns the new copy view. */
  async function clone(id: string): Promise<RosterTemplateView> {
    const w = await apiJson<RosterTemplateWire>(
      "POST",
      `/api/chat/roster-templates/${encodeURIComponent(id)}/clone`,
    );
    const view = wireToTemplate(w);
    templates.value = [...templates.value, view];
    return view;
  }

  /** Reset a "clone of a factory preset" copy back to its source content (the
   *  copy id is preserved). Returns the reset view. */
  async function reset(id: string): Promise<RosterTemplateView> {
    const w = await apiJson<RosterTemplateWire>(
      "POST",
      `/api/chat/roster-templates/${encodeURIComponent(id)}/reset`,
    );
    const view = wireToTemplate(w);
    templates.value = templates.value.map((tpl) => (tpl.id === id ? view : tpl));
    return view;
  }

  return {
    templates,
    loaded,
    fetchAll,
    create,
    update,
    remove,
    applyToConversation,
    clone,
    reset,
  };
});
