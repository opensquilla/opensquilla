import { stripTerminalControls } from "./primitives.mjs";

function safeText(value) {
  if (typeof value === "string") return stripTerminalControls(value);
  if (value === null || value === undefined) return "";
  try { return stripTerminalControls(JSON.stringify(value)); }
  catch { return stripTerminalControls(String(value)); }
}

function itemName(item, fallback) {
  return safeText(item?.name ?? item?.filename ?? item?.path ?? item?.id ?? fallback);
}

function attachmentTail(message) {
  const names = Array.isArray(message?.attachments)
    ? message.attachments.map((item) => itemName(item, "attachment")).filter(Boolean)
    : [];
  return names.length ? `\nattachments · ${names.join(" · ")}` : "";
}

function artifactText(message) {
  const names = Array.isArray(message?.artifacts)
    ? message.artifacts.map((item) => itemName(item, "artifact")).filter(Boolean)
    : [];
  return names.length ? `artifacts · ${names.join(" · ")}` : "";
}

function toolCall(call, index) {
  if (!call || typeof call !== "object" || Array.isArray(call)) return null;
  if (call.type === "text") return null;
  const fn = call.function && typeof call.function === "object" ? call.function : {};
  const name = safeText(call.name ?? call.tool_name ?? call.toolName ?? fn.name ?? "");
  if (!name) return null;
  const args = safeText(call.input ?? call.arguments ?? fn.arguments ?? "").replace(/\s+/g, " ").trim();
  const result = safeText(call.result ?? call.output ?? call.content ?? call.error ?? "");
  const execution = call.execution_status && typeof call.execution_status === "object"
    ? String(call.execution_status.status ?? "")
    : "";
  const failed = Boolean(call.is_error ?? call.isError ?? call.error)
    || ["error", "timeout", "cancelled"].includes(execution);
  return {
    id: safeText(call.tool_use_id ?? call.toolId ?? call.id ?? `tool-${index}`),
    name,
    args,
    result,
    status: failed ? "error" : "ok",
  };
}

function usageText(message) {
  const usage = message?.usage && typeof message.usage === "object" ? message.usage : null;
  if (!usage) return "";
  const input = Number(usage.input_tokens ?? usage.inputTokens ?? 0);
  const output = Number(usage.output_tokens ?? usage.outputTokens ?? 0);
  const cost = Number(usage.cost_usd ?? usage.costUsd ?? 0);
  const model = safeText(usage.model ?? "");
  const fields = [];
  if (model) fields.push(model);
  if (input || output) fields.push(`${input.toLocaleString("en-US")} in · ${output.toLocaleString("en-US")} out`);
  if (Number.isFinite(cost) && cost > 0) fields.push(`$${cost.toFixed(6)}`);
  return fields.join(" · ");
}

export function historyBoundaryText(message) {
  const count = Number(message?.loaded_count ?? message?.messages?.length ?? 0);
  const scope = String(message?.history_scope ?? "complete");
  if (scope === "compacted") {
    const summaries = Array.isArray(message?.compaction_summaries) ? message.compaction_summaries.length : 0;
    const summaryTail = summaries ? ` · ${summaries} earlier ${summaries === 1 ? "summary" : "summaries"}` : "";
    return `history · compacted · ${count} recent messages${summaryTail}`;
  }
  if (scope === "latest_window" || message?.has_more) return `history · latest ${count} messages · older messages available`;
  if (count === 0) return "";
  return `history · complete · ${count} messages`;
}

/** Clear old renderables, create a fresh flow, and synchronously replay one frame. */
export function replaceHistoryConversation({ message, conversationBox, flowFactory, addBoundary, nextId }) {
  for (const child of conversationBox.getChildren?.() ?? []) {
    conversationBox.remove?.(child.id);
  }
  const flow = flowFactory();
  const boundary = historyBoundaryText(message);
  if (boundary) addBoundary(boundary);
  replayHistory({ messages: message?.messages, flow, nextId });
  return flow;
}

/** Replay one canonical snapshot through the same turn views used by live turns. */
export function replayHistory({ messages, flow, nextId }) {
  const seen = new Set();
  let promptOpen = false;
  for (const [index, raw] of (Array.isArray(messages) ? messages : []).entries()) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const durableId = safeText(raw.id || `legacy-${index}`);
    if (seen.has(durableId)) continue;
    seen.add(durableId);
    const id = nextId(durableId);
    const role = String(raw.role ?? "message");

    if (role === "user") {
      if (promptOpen) flow.endTurn(false);
      const view = flow.turnForPrompt(id);
      view.begin(`${id}-prompt`, "prompt", {
        text: `${safeText(raw.text)}${attachmentTail(raw)}`.trim(),
      });
      promptOpen = true;
      continue;
    }

    const view = flow.ensure(id);
    const reasoning = safeText(raw.reasoning);
    if (reasoning) {
      view.begin(`${id}-reasoning`, "reasoning", {});
      view.append(`${id}-reasoning`, reasoning);
      view.end(`${id}-reasoning`);
    }

    for (const [toolIndex, rawCall] of (Array.isArray(raw.tool_calls) ? raw.tool_calls : []).entries()) {
      const call = toolCall(rawCall, toolIndex);
      if (!call) continue;
      const blockId = `${id}-tool-${call.id}`;
      view.begin(blockId, "tool", { name: call.name, args: call.args });
      if (call.result) view.append(blockId, call.result);
      view.update(blockId, { status: call.status });
      view.end(blockId);
    }

    const text = safeText(raw.text);
    if (text) {
      const kind = role === "error" ? "error" : role === "assistant" ? "answer" : "thinking";
      const blockId = `${id}-${kind}`;
      view.begin(blockId, kind, kind === "error" ? { text } : {});
      if (kind !== "error") view.append(blockId, text);
      view.end(blockId);
    }
    const artifacts = artifactText(raw);
    if (artifacts) {
      const blockId = `${id}-artifacts`;
      view.begin(blockId, "history-detail", { text: artifacts });
      view.end(blockId);
    }
    const usage = usageText(raw);
    if (usage) view.begin(`${id}-usage`, "usage", { text: usage });
    flow.endTurn(false);
    promptOpen = false;
  }
  if (promptOpen) flow.endTurn(false);
}
