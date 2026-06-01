# Session View Contract

This document is the shared contract for the Web UI session optimization work on
`feature/session-contract-ui-backend`.

The goal of this branch is to improve Web UI session discovery, grouping,
labeling, and readability. Backend changes exist to support that UI work with a
stable session view contract. This is not a backend-only architecture rewrite.

## Problem

The current Web UI often treats the raw session key as both an address and a
semantic data source. That forces frontend code to infer concepts from strings
such as `agent:*:webchat:*`, `:cli:`, `:subagent:`, `:cron:`, or `:thread:`.

That is fragile because a session key may encode several independent concepts:

- routing address
- agent/workspace ownership
- entry surface
- external channel identity
- direct/group/channel conversation topology
- thread/topic modifiers
- subagent/task origin
- cron origin or delivery
- legacy compatibility shape

The UI should not own those interpretations. The backend must provide a
UI-ready session view, and the frontend should render from that view.

## API

Preferred RPC:

```ts
rpc.call("sessions.list", { limit: 200, view: "session-list-v1" })
```

If a REST endpoint is used, `/api/sessions` should support equivalent `limit`
and `view` parameters before the chat session selector relies on it for a larger
list. The current default session list size may be too small for selector UI.

The response shape remains backward compatible:

```ts
interface SessionsListResponseV1 {
  sessions: SessionListItemV1[];
  count: number;
  ts: number;
}
```

Existing callers that send only `{ limit }` must continue to work.

## Contract Fields

```ts
interface SessionListItemV1 {
  key: string;
  sessionId?: string;

  // Legacy/stored agent id. Kept for compatibility with existing callers.
  agentId?: string;

  // Effective routing/workspace owner. New UI should prefer this.
  effectiveAgentId: string;

  sessionKind: "chat" | "channel" | "task" | "cron" | "system" | "unknown";

  surface:
    | "webchat"
    | "cli"
    | "tui"
    | "mcp"
    | "slack"
    | "feishu"
    | "wecom"
    | "telegram"
    | "discord"
    | "dingtalk"
    | "matrix"
    | "qq"
    | "cron"
    | "subagent"
    | "unknown";

  conversationKind: "main" | "direct" | "group" | "channel" | "unknown";

  thread?: {
    id: string;
    kind: "thread" | "topic";
  } | null;

  title: string;
  subtitle?: string;
  groupLabel: string;

  updatedAt: number;
  messageCount: number;
  status: string;

  runStatus:
    | "idle"
    | "queued"
    | "running"
    | "interrupted"
    | "failed"
    | "timeout"
    | "cancelled";

  channel?: {
    name?: string;
    id?: string;
    accountId?: string;
    peerId?: string;
    threadId?: string;
  };

  parent?: {
    key: string;
    taskId?: string;
    spawnDepth?: number;
  } | null;

  cron?: {
    jobId?: string;
    sessionTarget?: "main" | "isolated" | "current" | "session";
    originSessionKey?: string;
    targetSessionKey?: string;
  } | null;
}
```

## Field Semantics

`key`

Public session routing address. The UI may use it for opening, resuming,
copying, deleting, and debugging a session. The UI must not parse it for
semantic classification.

`sessionId`

Backend transcript/storage identity when available. It is not the primary UI
routing address.

`agentId`

Legacy or stored agent id. This remains available for compatibility with
existing CLI/TUI/MCP and older UI paths.

`effectiveAgentId`

The agent id that should be used for UI ownership, workspace/routing display,
and agent badges. This handles legacy rows where the stored `agentId` may be
`main` while routing should follow another agent.

`sessionKind`

The lifecycle bucket of the session:

- `chat`: human-facing interactive chat session, including WebChat, CLI, TUI,
  MCP, and main-agent chat sessions.
- `channel`: external platform conversation session.
- `task`: runtime/background task session, especially subagent work.
- `cron`: cron-owned isolated run session.
- `system`: internal/system session when the backend exposes one.
- `unknown`: backend cannot classify the row.

`surface`

The entry surface or platform that produced the session view. Examples:
`webchat`, `cli`, `tui`, `mcp`, `feishu`, `slack`, `telegram`, `cron`,
`subagent`.

`conversationKind`

The conversation topology:

- `main`: an agent's main/private session.
- `direct`: direct/private one-to-one conversation.
- `group`: group, room, or multi-person conversation.
- `channel`: platform channel/broadcast-style conversation.
- `unknown`: backend cannot classify the topology.

Thread and topic information must be expressed through `thread`, not by adding
`conversationKind: "thread"`.

`thread`

Optional modifier for platform thread/topic context. It does not replace
`conversationKind`.

`title`

Primary user-facing label. UI should prefer this over the raw `key`.

`subtitle`

Secondary context such as source, agent, channel, parent, or recent context.

`groupLabel`

UI grouping label. Session selector and Sessions page grouping should use this
field instead of deriving groups from the key.

`updatedAt`

Epoch milliseconds for recency sorting and relative time display.

`messageCount`

Transcript/message count for display.

`status`

Persisted session lifecycle status.

`runStatus`

Runtime task status for current/last turn display. This is separate from the
persisted session lifecycle status.

`channel`

Optional external channel identity and delivery metadata. This should be
display-only in the UI unless a feature explicitly needs routing details.

`parent`

Optional subagent/task parent relationship.

`cron`

Optional cron metadata. Cron metadata does not automatically make an existing
webchat/channel session a cron session.

## Backend Rules

The backend owns session classification and display normalization.

Backend generation should prefer explicit structured data before legacy key
fallbacks:

1. Session row fields, including agent id, display name, channel fields,
   delivery context, parent session key, and origin metadata.
2. Route/source metadata such as source kind, channel kind, channel id,
   thread id, and interaction mode.
3. Task runtime rows for `runStatus`, subagent/task status, and parent
   relationships.
4. Cron job/session metadata for cron-owned isolated runs and cron delivery
   context.
5. Legacy key parsing only as a compatibility fallback inside backend
   normalization.

The frontend must not duplicate backend key parsing.

Backend compatibility requirements:

- Keep `sessions.list { limit }` working.
- Keep `sessions.create -> { key, sessionId }` working.
- Keep `sessions.resolve({ key })` working.
- Keep `chat.history({ sessionKey })` working.
- Keep existing row fields such as `agent_id`, `agentId`, `updated_at`,
  `updatedAt`, `message_count`, `entry_count`, `sourceKind`, and `channelKind`.
- Add new contract fields without deleting or changing the old shape.

## Frontend Rules

Frontend should render from contract fields:

- Group sessions by `groupLabel`.
- Use `title` as primary text.
- Use `subtitle` as secondary text.
- Use `effectiveAgentId` for agent badges and agent ownership display.
- Use `messageCount` for message count.
- Use `updatedAt` for relative time.
- Use `runStatus` for runtime badges.
- Use `sessionKind`, `surface`, and `conversationKind` for icons, colors, and
  high-level visual treatment.
- Treat `thread` or `topic` as a modifier, not as a separate conversation kind.
- Use `key` only for open/resume/copy/delete/RPC/debug actions.

If the UI needs a missing semantic field, backend should add it to this contract
instead of the frontend deriving it from the key.

## Forbidden Frontend Behavior

Frontend must not:

- parse `session.key` to determine session kind
- parse `session.key` to determine agent ownership
- group by key tokens such as `:webchat:`, `:cli:`, `:subagent:`, `:cron:`,
  `:thread:`, or `:topic:`
- infer external channel type from key segments
- make the raw key the dominant user-facing label except in explicit debug/copy
  contexts
- render a normal webchat/channel session as cron only because cron delivered
  into it

Temporary fallback logic should be isolated, clearly marked, and should not
become the primary UI path.

## Display Examples

### WebChat

```json
{
  "key": "agent:main:webchat:default",
  "sessionId": "0d2d6f3e-8a41-40de-a3d4-5f05a3c4557a",
  "agentId": "main",
  "effectiveAgentId": "main",
  "sessionKind": "chat",
  "surface": "webchat",
  "conversationKind": "direct",
  "thread": null,
  "title": "Web chat",
  "subtitle": "main",
  "groupLabel": "Web chat",
  "updatedAt": 1760000000000,
  "messageCount": 42,
  "status": "idle",
  "runStatus": "idle",
  "parent": null,
  "cron": null
}
```

### CLI

```json
{
  "key": "agent:main:cli:a1b2c3d4",
  "agentId": "main",
  "effectiveAgentId": "main",
  "sessionKind": "chat",
  "surface": "cli",
  "conversationKind": "main",
  "title": "CLI session",
  "subtitle": "main",
  "groupLabel": "CLI",
  "updatedAt": 1760000000000,
  "messageCount": 12,
  "status": "idle",
  "runStatus": "idle"
}
```

### Subagent Task

```json
{
  "key": "agent:main:subagent:760b927a",
  "agentId": "main",
  "effectiveAgentId": "main",
  "sessionKind": "task",
  "surface": "subagent",
  "conversationKind": "unknown",
  "title": "Subagent task",
  "subtitle": "Spawned from Web chat",
  "groupLabel": "Subagents",
  "updatedAt": 1760000000000,
  "messageCount": 8,
  "status": "running",
  "runStatus": "running",
  "parent": {
    "key": "agent:main:webchat:default",
    "taskId": "task-123",
    "spawnDepth": 1
  },
  "cron": null
}
```

### Cron-Owned Isolated Run

```json
{
  "key": "cron:daily-summary:run:abc123",
  "effectiveAgentId": "main",
  "sessionKind": "cron",
  "surface": "cron",
  "conversationKind": "unknown",
  "title": "Daily summary",
  "subtitle": "Cron isolated run",
  "groupLabel": "Cron",
  "updatedAt": 1760000000000,
  "messageCount": 4,
  "status": "idle",
  "runStatus": "idle",
  "cron": {
    "jobId": "daily-summary",
    "sessionTarget": "isolated"
  }
}
```

### Cron Delivery Into Existing Channel Session

Cron delivery metadata may be present, but the existing channel session keeps
its original visual identity.

```json
{
  "key": "agent:main:feishu:group:oc_123",
  "agentId": "main",
  "effectiveAgentId": "main",
  "sessionKind": "channel",
  "surface": "feishu",
  "conversationKind": "group",
  "title": "Launch room",
  "subtitle": "Feishu group",
  "groupLabel": "Feishu",
  "updatedAt": 1760000000000,
  "messageCount": 31,
  "status": "idle",
  "runStatus": "idle",
  "channel": {
    "name": "feishu",
    "id": "oc_123"
  },
  "cron": {
    "jobId": "launch-check",
    "sessionTarget": "session",
    "targetSessionKey": "agent:main:feishu:group:oc_123"
  }
}
```

### External Channel Thread

```json
{
  "key": "agent:main:slack:group:C123:thread:1717000000.000100",
  "agentId": "main",
  "effectiveAgentId": "main",
  "sessionKind": "channel",
  "surface": "slack",
  "conversationKind": "group",
  "thread": {
    "id": "1717000000.000100",
    "kind": "thread"
  },
  "title": "C123 thread",
  "subtitle": "Slack thread",
  "groupLabel": "Slack",
  "updatedAt": 1760000000000,
  "messageCount": 16,
  "status": "idle",
  "runStatus": "idle",
  "channel": {
    "name": "slack",
    "id": "C123",
    "threadId": "1717000000.000100"
  }
}
```

### Legacy Agent Mismatch

If stored `agentId` is `main` but the effective routing/workspace owner is
another agent, the UI must show `effectiveAgentId`.

```json
{
  "key": "agent:kid-project:webchat:test",
  "agentId": "main",
  "effectiveAgentId": "kid-project",
  "sessionKind": "chat",
  "surface": "webchat",
  "conversationKind": "direct",
  "title": "Kid project",
  "subtitle": "Web chat",
  "groupLabel": "Web chat",
  "updatedAt": 1760000000000,
  "messageCount": 5,
  "status": "idle",
  "runStatus": "idle"
}
```

## Backend Test Expectations

Backend contract tests should cover at least:

- WebChat session
- CLI session
- subagent task session
- cron-owned isolated session
- cron delivery into an existing session
- external channel session, such as Feishu, Slack, or Telegram
- thread/topic modifier
- legacy row where stored `agentId` differs from `effectiveAgentId`
- unknown/fallback row that still produces usable `title`, `groupLabel`, and
  `runStatus`

## Frontend Acceptance Criteria

- Chat session selector groups by `groupLabel`.
- Sessions page displays `title`, `subtitle`, `effectiveAgentId`,
  `messageCount`, `updatedAt`, and `runStatus`.
- No new frontend logic parses `session.key` for semantic classification.
- Existing open/resume/copy/delete behavior still uses `key`.
- WebChat, CLI, subagent, cron, and external channel sessions render from
  contract fields.
- Unknown or missing values degrade gracefully.
- Fallback logic does not reintroduce key parsing as the primary path.
