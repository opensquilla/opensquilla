# Web UI

The OpenSquilla Web UI is the local control console for setup, chat sessions,
approvals, channels, logs, agents, usage, and operational status. It is the
best surface when you want browser-based chat, visible tool activity, durable
approvals, and a quick view of runtime health.

## Start the Web UI

Run the gateway in the foreground:

```sh
opensquilla gateway run
```

Open:

```text
http://127.0.0.1:18791/control/
```

Or start a managed background gateway:

```sh
opensquilla gateway start --json
opensquilla gateway status
```

The default gateway binds to `127.0.0.1` for safety.

For gateway lifecycle, host/port, and exposure details, see
[`gateway.md`](gateway.md).

## Main Areas

| Area | Use it for |
| --- | --- |
| Chat | Run and resume chat sessions, inspect tool activity, publish artifacts, and use manual compact controls. |
| Overview / Health | See readiness, provider state, memory state, sandbox posture, and recovery hints. |
| Channels | Add, edit, enable, disable, restart, and inspect channel adapters. |
| Skills | Browse available skills and meta-skill surfaces. |
| Sessions | Inspect durable conversations and operational state. |
| Agents | Manage durable agent entries. |
| Usage | Inspect token and estimated-cost rollups. |
| Cron | View and manage scheduled runs. |
| Config | Edit setup sections from the browser. |
| Logs | Inspect runtime logs and diagnostics. |
| Approvals | Respond to sensitive tool-call approval requests. |

## Chat Sessions

The chat UI supports:

- streaming assistant output;
- tool-call cards;
- artifact cards;
- pending message queue behavior while compaction or runtime work is in flight;
- manual `/compact`;
- per-turn usage and savings metadata when available;
- copyable session keys.

Use the session selector to switch between existing sessions. Copy the session
key when reporting a bug or asking another OpenSquilla surface to inspect the
same session.

## Manual Compaction

Long sessions can be compacted from chat. If no compaction is needed, the UI
reports:

```text
Already within context budget; no compact was applied
```

If compaction is running, wait for its terminal state before assuming the next
message has the compacted context. See
[`features/compaction-and-cache.md`](features/compaction-and-cache.md).

## Artifacts

When the agent publishes a file, the Web UI shows an artifact card. Use artifact
cards for:

- generated HTML prototypes;
- reports and briefings;
- exported data files;
- PDFs, slide decks, images, and other generated outputs.

For channel delivery limits and artifact recovery, see
[`artifacts-and-media.md`](artifacts-and-media.md).

## Approvals

Some tools require confirmation. The approvals area gives operators a durable
place to approve or deny sensitive actions instead of burying the decision in
chat text.

Use the approvals area when:

- the agent wants to write files;
- a command requires elevated permissions;
- a channel or external action needs human confirmation;
- unattended automation should pause before a risky operation.

## Logs and Diagnostics

For local diagnosis:

```sh
opensquilla diagnostics on
opensquilla gateway status
opensquilla doctor
```

Use the Web UI logs and health views to correlate provider readiness, channel
state, session state, and user-visible errors.

## Safety

The Web UI is local by default. If you bind the gateway to a public interface,
configure token auth and network controls first:

```sh
opensquilla gateway run --listen 0.0.0.0 --port 18791
```

Do not expose an unauthenticated gateway to the public internet.

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
