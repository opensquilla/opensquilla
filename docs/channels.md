# Channels

Channels let OpenSquilla run from messaging platforms while sharing the same
agent runtime as the CLI and Web UI. Use channels when you want the same agent
to answer from Slack, Telegram, Feishu/Lark, Discord, DingTalk, WeCom, Matrix,
QQ, or another supported adapter.

## Supported Channel Types

Inspect your local install:

```sh
opensquilla channels types
opensquilla channels types --json
opensquilla channels describe feishu
```

This build exposes the following channel families:

| Type | Label | Transport | Public URL needed |
| --- | --- | --- | :---: |
| `dingtalk` | DingTalk | websocket | no |
| `discord` | Discord | websocket | no |
| `feishu` | Feishu / Lark | mixed | depends on mode |
| `matrix` | Matrix | websocket | no |
| `qq` | QQ Bot | websocket | no |
| `slack` | Slack | mixed | depends on mode |
| `telegram` | Telegram | mixed | depends on mode |
| `wecom` | WeCom | webhook | yes |

The local `channels describe <type>` output is the source of truth for required
fields, secrets, extras, and restart behavior.

## Setup Flow

Interactive setup:

```sh
opensquilla configure channels
```

Add a channel explicitly:

```sh
opensquilla channels add telegram --name personal
```

Add provider-specific fields as needed. Slack supports two modes:

```sh
# Slack Socket Mode: outbound websocket, no public URL.
opensquilla channels add slack --name team \
  --field connection_mode=socket \
  --field app_token=xapp-... \
  --token xoxb-...

# Slack Events API webhook: requires a public Request URL and signing secret.
opensquilla channels add slack --name team-webhook \
  --field connection_mode=webhook \
  --field signing_secret=... \
  --token xoxb-...
```

Restart the gateway process after config edits:

```sh
opensquilla gateway restart
```

Verify runtime connection:

```sh
opensquilla channels status
opensquilla channels status personal --json
```

Saving a channel proves the config was written. `channels status` proves whether
the running gateway loaded and connected it.

## Manage Channels

```sh
opensquilla channels list
opensquilla channels enable <name>
opensquilla channels disable <name>
opensquilla channels edit <name>
opensquilla channels restart <name>
opensquilla channels logout <name>
opensquilla channels remove <name>
```

Use `gateway restart` after config changes. Use `channels restart <name>` only
for an already-loaded live adapter.

## Slack Modes

Slack Socket Mode uses an outbound websocket and does not require a public
Request URL. It requires the bot token (`xoxb-...`) plus an app-level token
(`xapp-...`) saved as `app_token`.

Slack webhook mode uses the Events API Request URL. It requires the bot token
plus `signing_secret`, and the gateway must be reachable by Slack.

Leave `slack_channel_id` empty when the adapter should reply to the incoming
conversation. Set it only when you want a default fallback channel. Enable
`reply_in_thread` when replies should stay in Slack threads.

## Webhook Channels

Slack webhook mode and WeCom require a public, provider-reachable URL. Feishu
and Telegram may require one depending on mode.

For public channels:

- bind the gateway to a reachable interface;
- place it behind a trusted reverse proxy or tunnel;
- configure auth;
- check provider callback URLs and secrets carefully.

Example bind for a controlled network:

```sh
opensquilla gateway run --listen 0.0.0.0 --port 18791
```

Do not expose an unauthenticated gateway to the public internet.

## Attachments and Artifacts

Channel adapters can differ in attachment and artifact delivery behavior.
OpenSquilla normalizes agent execution through the same runtime path, but the
platform transport still controls file size limits, message threading, and
download/upload capabilities.

When a channel cannot deliver a large artifact directly, use the Web UI artifact
card or session export as the recovery path.

## Troubleshooting

If a channel does not respond:

1. Check config entries:

   ```sh
   opensquilla channels list
   ```

2. Check runtime status:

   ```sh
   opensquilla channels status <name> --json
   ```

3. Restart the gateway process after config changes:

   ```sh
   opensquilla gateway restart
   ```

4. For webhook channels, confirm the public URL, provider callback secret, and
   gateway auth/network boundary.

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
