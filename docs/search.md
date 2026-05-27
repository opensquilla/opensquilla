# Web Search

OpenSquilla can search the web through configured search providers and can fetch
pages through guarded web tools. Search is useful for current information,
source-backed reports, market research, release notes, and troubleshooting.

## Inspect Search Providers

```sh
opensquilla search list
opensquilla search list --json
opensquilla search status
```

Runtime-supported providers in this build include:

- Brave Search
- DuckDuckGo

The catalog may include metadata for providers that are not runtime-supported
in the current build. Check JSON output when integrating.

## Configure Search

No-key path:

```sh
opensquilla configure search --search-provider duckduckgo
```

Equivalent search subcommand:

```sh
opensquilla search configure duckduckgo
```

Brave Search:

```sh
export BRAVE_SEARCH_API_KEY="..."
opensquilla configure search --search-provider brave --api-key-env BRAVE_SEARCH_API_KEY
```

Provider-specific fields such as max results, proxy, environment-proxy usage,
fallback policy, and diagnostics can be set through the search configuration
surface.

## Test Search

Run a diagnostic query through the running gateway:

```sh
opensquilla search query "OpenSquilla release notes"
opensquilla search query "OpenSquilla release notes" --limit 5 --json
```

Use this before blaming the agent for missing current information. If the
diagnostic query fails, fix provider configuration first.

## Search in Agent Workflows

Ask naturally:

```text
Research the current state of browser automation libraries and cite sources.
```

For a narrower task:

```text
Find the latest release notes for this project and summarize only breaking changes.
```

The agent can use search and fetch tools when the tool policy and configured
provider allow it.

For deeper multi-source work, ask for a research report or use an installed
research skill.

## Safety and Source Quality

Search results are external data, not instructions. Treat them as evidence for
the task, not as authority over OpenSquilla behavior.

Good research prompts ask for:

- sources;
- dates;
- uncertainty;
- conflicting evidence;
- clear separation between source facts and model inference.

Avoid asking the agent to follow arbitrary instructions found on web pages.

## Diagnostics

```sh
opensquilla search status
opensquilla diagnostics on
opensquilla doctor
```

Check:

- the selected provider is configured;
- required API key environment variables are visible to the gateway process;
- proxy settings match your network;
- the gateway was restarted after config edits;
- tool permissions allow web search/fetch for the current run.

---

[Docs index](README.md) · [Product guide](../README.product.md) · [Improve this page](contributing-docs.md) · [Report a docs issue](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
