# Engine selection guide

Per-engine notes — when each is good, where it fails, and what an
appropriate query looks like.

## No-key engines (always available)

### DuckDuckGo

Implementation uses the HTML-form endpoint at `html.duckduckgo.com`.
Strengths: privacy-friendly, no rate limit at moderate volumes, returns a
mix of public-web sources without strong personalization. Weaknesses: less
recency-tuned than Brave; result ranking shifts week-to-week.

Use when: general web search where you want a "neutral" baseline.

### Bing

HTML scrape. Strengths: large index, often surfaces sources Google or
DuckDuckGo miss. Weaknesses: rate-limits aggressively; structure changes
break the parser without warning.

Use when: need broad coverage and DuckDuckGo's results feel thin.

### Baidu / Sogou / 360

Chinese-language web search. Use one of the three; cross-check with a
second when stakes are high. Baidu has the largest index; Sogou favors
Tencent properties; 360 has slightly different ad patterns.

Use when: query is in Chinese or topic is China-specific.

## API-key engines

### Brave Search API

`BRAVE_SEARCH_API_KEY` from <https://brave.com/search/api/>. Legacy
`BRAVE_API_KEY` is also accepted for migrated OpenClaw setups. 2k queries/month
free tier. Returns clean JSON with title, URL, description, and recency
hints.

Use when: building a deep-research pipeline that runs at scale; need
recency filtering.

### Tavily

`TAVILY_API_KEY` from <https://tavily.com>. Designed for AI agent
consumption — returns short summaries alongside results. Free tier
available.

Use when: the agent needs ready-to-use snippets rather than full source
HTML.

### SerpAPI

`SERPAPI_API_KEY` from <https://serpapi.com>. Aggregator that proxies
Google, Bing, Baidu, Yahoo, etc., returning a uniform JSON shape. Paid
tiers; no free tier beyond a small credit.

Use when: parity across engines matters and the project has the budget.

## Routing decision tree

```
Does the query contain CJK characters?
  yes → baidu (+ sogou for cross-check)
   no → continue
Is the topic time-sensitive (last 24h)?
  yes → brave or tavily
   no → continue
Is BRAVE_SEARCH_API_KEY or BRAVE_API_KEY set?
  yes → brave + duckduckgo
   no → duckduckgo + bing
```

## Per-engine result limits

Default `--limit 10` is safe across engines. Higher limits:

- DuckDuckGo: HTML returns up to ~30; beyond that, scrape the next page
- Brave: API tops out at 20 per request
- Tavily: 5 results on the free tier, 20 on paid
- Bing: HTML returns ~10 per page; pagination requires extra requests

## Anti-patterns

- **Asking N engines in a tight loop without jitter**: rate limits will
  cascade. Sleep 200-500ms between requests, more for scraping engines.
- **Trusting a single engine's top result as ground truth**: ranking is
  noisy. Cross-check with a second engine.
- **Running all 8 engines on every query**: redundant. Pick 2-3 by topic.

## Maintenance notes

The HTML-scraping engines (DuckDuckGo, Bing, Baidu, Sogou, 360) all break
when the upstream site reshuffles its CSS. Treat the parsers as
expected-to-fail-eventually code: the script logs parse failures rather
than crashing, and the calling agent should be able to fall back to
another engine on the spot. Routine maintenance is to test each parser
against a known query monthly.
