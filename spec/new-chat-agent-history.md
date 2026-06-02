# New Chat, Agent, and Conversations IA Spec

Status: Draft for review
Owner: Product/UI review
Last updated: 2026-06-01

## Background

The current Vue refactor exposes multiple actions that sound similar but have different effects:

- Sidebar top action currently behaves like a quick blank chat creation flow.
- Sessions page `New session` / create flow can choose an agent, optionally create an agent, and create a backend session.
- Agents page owns agent lifecycle, but Sessions can also create an agent as a side effect.
- History is currently a flat session list, so the user cannot tell which agent a chat belongs to without reading the raw session key.
- The persisted session ledger includes more than web chat: cron runs, channel conversations, subagents, CLI sessions, and operational task sessions all coexist in the same low-level session namespace.
- Session keys are not reliable enough as the only source of product meaning because existing data mixes shapes such as `agent:<agent_id>:webchat:<id>`, `agent:<agent_id>:<id>`, and `agent:<agent_id>:subagent:<id>`.

This makes the mental model unclear. A user clicking `New chat` cannot see which agent the chat will bind to, because the current implementation derives the agent implicitly from the active session key.

## Design Goal

Make the product model explicit:

- **Agent** is an identity/configuration.
- **Chat** is a conversation under one selected agent.
- **Conversation** is a user-facing thread that may come from web chat, channels, or automations.
- **Sidebar Conversations** is the daily navigation surface for user-facing conversations.
- **Sessions** is the operational ledger for persisted session/run state.

The user should always know which agent a new chat belongs to before the chat is created. The user should also be able to find important channel and automation conversations without treating the sidebar as a raw sessions table.

## Page Ownership Model

The three surfaces should coexist by owning different jobs:

| Surface | Primary job | Daily user path? | Creates Agent? | Creates Conversation? | Shows raw session/run state? |
| --- | --- | --- | --- | --- | --- |
| Sidebar Conversations | Navigate user-facing threads and start chats | Yes | No | Web chat only, after agent selection | No |
| Agents page | Configure agent identities | Sometimes | Yes | Optional row action only | No |
| Sessions page | Inspect and manage session/run records | No | No | Not the normal path | Yes |

### Agents page: configuration center

Agents page owns who an agent is and how it works.

Responsibilities:

- Create, edit, and delete agents.
- Configure agent name, identity, model defaults, workspace, prompt, and permissions when supported.
- Offer a row-level `Chat` action as a convenience for starting a chat with that specific agent.

Non-responsibilities:

- Do not become the main chat history view.
- Do not show a full raw sessions table.
- Do not automatically create a chat after creating an agent unless a future reviewed spec explicitly adds that behavior.

### Sidebar Conversations: daily conversation entry

Sidebar Conversations owns the user's normal conversation workflow. It is not a mirror of `sessions.list`; it is a curated navigation surface for threads users are likely to continue, inspect, or recognize.

Responsibilities:

- `New chat` opens an agent picker.
- Existing user-facing conversations are grouped by source family first, then by the most relevant local grouping.
- Chat items use human-readable summaries.
- Channel items use channel/account/thread labels where available.
- Automation items use cron/job labels where available.
- Clicking a conversation opens the exact session key or the route that owns that conversation.

Non-responsibilities:

- Do not create agents silently.
- Do not show raw session keys as the primary label.
- Do not expose every low-level session type.
- Do not show subagents, CLI sessions, internal task sessions, or system maintenance records as normal conversations unless a future reviewed spec gives them a user-facing presentation.

### Sessions page: operational ledger

Sessions page owns low-level session/run management.

Responsibilities:

- List sessions and runs across all surfaces.
- Show raw session key, agent ID, session type, status, timestamps, token/usage metadata when available, and active task state.
- Support search, filters, refresh, delete/cleanup, and open-session actions.

Non-responsibilities:

- Do not be the primary daily chat creation path.
- Do not create agents as a side effect.
- Do not duplicate the sidebar `New chat` flow with a confusingly similar primary action.

## Non-Goals

- Do not redesign the full Agents page.
- Do not redesign the backend session manager.
- Do not change LLM routing behavior.
- Do not implement rich chat summarization yet.
- Do not remove the Sessions page; it remains useful as an operational table.
- Do not make the sidebar a complete replacement for Sessions filtering/search.
- Do not create cron jobs or channel bindings from `New chat`.

## Product Decisions

### 1. Agent creation belongs to Agents

Primary agent lifecycle actions should live in the Agents page.

Required behavior:

- Agents page has an explicit `New agent` action.
- Creating an agent should not automatically create or open a chat unless a future reviewed spec says so.
- Sessions page should not be the primary place users discover agent creation.
- Sessions page should not call `agents.create` from its normal session create path.
- A `Create agent...` affordance may appear in a picker only if it navigates to Agents or opens the same reviewed Agent creation UI.

Rationale:

- Agent creation is a configuration-management action.
- Hiding it inside session creation makes side effects hard to predict.

### 2. Sidebar `New chat` must choose or show an agent

The sidebar quick action should be named `New chat`, not `New session`.

Required behavior:

- Clicking `New chat` opens a lightweight agent picker instead of immediately creating a blank chat.
- The picker clearly shows the selected agent.
- The default selected agent can be:
  - the current chat's agent, if currently in a chat;
  - otherwise the most recently used agent;
  - otherwise `main`.
- User can switch the agent before confirming.
- Confirming creates a new webchat key under the selected agent.

Expected key shape:

```text
agent:<agent_id>:webchat:<random_suffix>
```

Rationale:

- `New chat` is a conversation action, but the agent binding is part of the conversation identity.
- The current implicit binding from `sessionKey` is too hidden.

### 3. Sidebar Conversations should group by user-facing source family

The sidebar should use `Conversations`, not raw `History`, as its product concept. It should group first by user-facing source family so web chat, channel conversations, and automations do not compete in one flat list.

```text
Conversations
  Chats
    Main Agent
      养老院志愿者欢乐
      智谱华章核心技术同学...
    Infra Agent
      部署失败排查
  Channels
    Slack / infra-alerts
      部署失败排查
    WeChat / 张三
      今天的产品反馈
  Automations
    Daily Report
      2026-06-01 run
    Paper Monitor
      最新论文扫描
```

Required behavior:

- Source-family groups are expandable/collapsible.
- Required source families:
  - `Chats`: web chat conversations started from `New chat`, Agent row `Chat`, or compatible legacy web-origin sessions.
  - `Channels`: conversations from external channels such as Slack, WeChat, Telegram, Feishu, DingTalk, WeCom, Matrix, QQ, or future channel adapters.
  - `Automations`: cron/scheduled conversations and automation run outputs that users may inspect later.
- Within `Chats`, group by Agent because agent identity is the user's main organizing concept for manual chat.
- Within `Channels`, group by channel/account/thread where available; show Agent as secondary metadata.
- Within `Automations`, group by job/schedule label where available; show Agent as secondary metadata.
- Current conversation is visibly highlighted.
- Empty agents should not appear under `Chats`.
- Source families with no items should not appear unless a future empty-state design is approved.
- Group order should be stable and useful:
  - current source family first if the current route belongs to a conversation;
  - then source families with most recently updated conversations;
  - within a source family, most recently updated groups first.

Rationale:

- Web chat, channel conversations, and automations have different user mental models.
- Agent is the executor, but not always the primary navigation anchor for channel and cron history.
- The sidebar becomes a conversation navigation surface rather than a raw session-key list.

### 4. Chat list item title uses first user message

Until real summarization exists, each chat item title should use the first user message.

Required behavior:

- Use the first non-empty user message as the title.
- Strip protocol/time prefixes and collapse whitespace.
- Truncate to a compact sidebar length.
- If no user message exists, show `New chat`.
- If loading the first message fails, fall back to the session suffix or `New chat`.

Examples:

```text
养老院志愿者欢乐
智谱华章核心技术同学 infra方向
New chat
```

Rationale:

- Raw session keys are not useful as primary labels.
- First user message is deterministic and cheap.

### 5. Sessions page becomes operational management

Sessions page should keep its table and operational controls, but it should not compete with sidebar `New chat`.

Required behavior:

- Sessions page no longer creates agents.
- Sessions page does not present the normal daily chat creation action.
- Keep refresh, delete, status, run state, and search.
- Keep raw session key visibility in the table.
- Opening a row navigates to the corresponding chat/session when applicable.

Allowed advanced behavior:

- A future `Create managed session` action may exist only if it is clearly advanced/operational.
- If retained, it must choose an existing agent only, or link to Agents for creating one.

Rationale:

- Sessions is useful for inspection, cleanup, and debugging.
- Daily chat creation should happen from the sidebar.
- Agent creation should happen from Agents.

## Interaction Flows

### Flow A: Create a new chat from sidebar

1. User clicks `New chat`.
2. Agent picker opens.
3. Picker defaults to current/recent/main agent.
4. User confirms.
5. UI generates a new webchat key for the selected agent.
6. Chat route becomes:

```text
/chat?session=agent:<agent_id>:webchat:<random_suffix>
```

7. Chat area is blank and ready for input.
8. History shows the new chat under the selected agent as `New chat`.

### Flow B: Start chat from an Agent row

Agent row chat is a convenience path, not a separate creation concept.

1. User opens Agents page.
2. User clicks `Chat` on an agent.
3. UI creates a new webchat for that specific agent.
4. Chat opens directly.

### Flow C: Open existing conversation from Sidebar Conversations

1. User expands a source-family group.
2. User expands the relevant local group:
   - Agent under `Chats`;
   - channel/account/thread under `Channels`;
   - job/schedule under `Automations`.
3. User clicks a conversation title.
4. The owning route opens with the relevant session key or route identifier.
5. Current conversation highlight moves to the clicked item.

### Flow D: Inspect sessions operationally

1. User opens Sessions page.
2. User searches, filters, or sorts sessions.
3. User inspects raw session/run state.
4. User opens a session or performs cleanup.

This flow should not be required for normal chat creation.

## Data Requirements

Sidebar Conversations needs enough data to render grouped conversation summaries without reverse-engineering product meaning from raw session keys.

Minimum required fields per conversation:

```ts
type SidebarConversationItem = {
  key: string
  agentId: string
  title: string
  conversationKind: 'chat' | 'channel' | 'automation'
  surface: 'webchat' | 'cron' | string
  groupLabel: string
  subtitle?: string
  updatedAt?: string | number
  runStatus?: string
  interactive?: boolean
}
```

Potential sources:

- Existing `sessions.list` output for session keys, agent IDs, timestamps, and run status.
- Existing history/messages endpoint for deriving the first user message.
- Existing channel metadata fields such as channel kind, account/thread identifiers, subject, and delivery context.
- Existing cron metadata such as job ID, schedule label, subject, and bound session key.
- A future backend summary field if needed for performance.

Implementation should avoid fetching full histories for too many sessions on every sidebar render. If existing APIs are insufficient, add a bounded summary API rather than loading every message list in the sidebar.

### Key and metadata rules

Frontend code should not rely on session-key substring rules as the long-term source of truth.

Required direction:

- Treat `key` as a stable identifier, not as the primary product taxonomy.
- Prefer structured fields from `sessions.list` or a future summary endpoint:
  - `conversationKind`
  - `surface`
  - `agentId`
  - `groupLabel`
  - `title`
  - `updatedAt`
  - `interactive`
- Legacy key parsing may remain only as a compatibility shim while structured fields are incomplete.
- If a row's `agent_id` conflicts with the agent encoded in the key, the UI should prefer an explicitly documented canonical field and avoid silently mixing both.
- Sessions page may show raw conflicts for debugging; Sidebar Conversations should avoid exposing the conflict as primary copy.

## Route and Compatibility Rules

Preferred route for new chat creation after confirmation:

```text
/chat?session=<webchat_session_key>
```

Compatibility:

- Legacy `/chat?new=1` may be supported temporarily.
- `/chat?newChat=1` should not remain as the long-term primary interaction if agent selection is required.
- After a chat is created, URL should normalize to `session=<key>`.

## UI Requirements

### New chat picker

Required elements:

- Title: `New chat`
- Agent selector
- Confirm button
- Cancel button

Recommended copy:

- Agent selector label: `Agent`
- Confirm button: `Start chat`

Do not show raw session keys in this modal.

Rules:

- The picker selects existing agents.
- It must not silently create a new agent.
- If inline creation is later approved, it should reuse the Agents creation UI and make the side effect explicit.

### Sidebar Conversations group

Required elements:

- Source-family label: `Chats`, `Channels`, or `Automations`
- Local group label:
  - Agent display name for `Chats`
  - Channel/account/thread label for `Channels`
  - Job/schedule label for `Automations`
- Expand/collapse affordance
- Conversation title list
- Current conversation highlight
- Running/queued/failed indicator when relevant
- Subtle secondary metadata: source, agent, relative time, and message/run count when available

Recommended row shape:

```text
[icon] Title                         status
       Source · Agent · time · count
```

Examples:

```text
养老院志愿者欢乐
Chat · Main Agent · 2h ago

部署失败排查
Slack · infra-alerts · Infra Agent · 12m ago

Daily Report
Cron · Research Agent · today 08:00
```

Visual rules:

- Avoid dense dividers between every item.
- Prefer a soft hover state, muted secondary text, and small source/status badges.
- Do not show raw session keys unless the user is in Sessions or an explicit debug/detail surface.

### Sessions table

Required elements:

- Raw session key
- Agent ID or display name
- Session kind/type when available
- Run status
- Last updated / created timestamp
- Open action
- Delete/cleanup action where authorized

Recommended copy:

- Page title remains `Sessions`.
- Primary creation action should be absent by default.
- If an advanced create action exists, label it `Create managed session`, not `New session` or `New chat`.

## Acceptance Criteria

- Sidebar has no action named `New session`.
- User cannot create a new chat from the sidebar without seeing the selected agent.
- New chat creation uses the selected agent, not an implicit hidden agent.
- Agent creation happens from Agents, not from Sessions.
- Sidebar daily navigation is labeled and modeled as Conversations, not raw History.
- `Chats` are grouped by agent.
- `Channels` are grouped by channel/account/thread where metadata is available.
- `Automations` are grouped by cron/job/schedule where metadata is available.
- Chat list items display first-user-message summaries where available.
- Empty chats display `New chat`.
- Non-user-facing sessions such as subagents, CLI sessions, and internal task sessions do not appear as normal sidebar conversations by default.
- Sessions page no longer presents a confusing duplicate of the daily `New chat` action.
- Sessions page does not create agents as a side effect.
- Sessions page keeps raw operational session/run visibility.
- Opening an existing conversation item preserves its session key or owning route identifier.
- Refreshing a chat route does not create another chat.
- Existing direct links with `session=<key>` continue to work.

## Verification Plan

Before implementation is accepted:

- Typecheck passes.
- Build passes.
- Browser smoke:
  - open Chat;
  - click `New chat`;
  - verify agent picker appears;
  - select a non-main agent;
  - verify resulting session key contains that agent ID;
  - send a first message;
  - verify Conversations shows that message summary under `Chats` and the selected agent.
- Regression:
  - direct `/chat?session=<key>` links still load history;
  - Sessions page can still list, search, refresh, and open sessions;
  - Agents page can still create agents.
  - Sessions page cannot silently create an agent during normal session operations.
  - channel and cron sessions remain visible in Sessions even if their sidebar Conversation presentation is incomplete.

## Open Questions for Review

- Should Sessions page retain any advanced `Create managed session` action, or should all creation move to `New chat` and Agents?
- Should `New chat` eventually allow creating a new agent inline, or should it only select existing agents and link to Agents?
- Should first-message summaries be computed client-side at first, or should the backend expose a lightweight session summary field?
- Should collapsed/expanded Agent groups persist in localStorage?
- What is the maximum number of chats shown per Agent group before showing `View all`?
- Which existing session fields should be the canonical source for `conversationKind`, `surface`, and `groupLabel`?
- Should legacy `agent:<agent_id>:<random_suffix>` web-origin sessions be migrated to `conversationKind: chat`, or only displayed through compatibility rules?
- Which channel providers should get first-class icons/labels in the first implementation pass?
- Should automation runs show every run or collapse repeated runs under one job with the latest run as the primary row?
