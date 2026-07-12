# Desktop Profile Recovery Contract

## Stable layout

`H` is an OpenSquilla profile root. Desktop passes `OPENSQUILLA_STATE_DIR=H`;
the variable does not name the `state/` child.

```text
H/
├── config.toml
├── workspace/
├── skills/
├── media/
├── session-archive/
├── router/
└── state/
```

Workspace selection changes identity, persona, and Markdown memory. Session and
scheduler databases remain under `state/`; choosing a workspace never switches
or merges chat history.
