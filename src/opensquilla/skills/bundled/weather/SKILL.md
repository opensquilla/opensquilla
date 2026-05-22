---
name: weather
description: "Get current weather and forecasts via wttr.in or Open-Meteo. Use when: user asks about weather, temperature, or forecasts for any location. NOT for: historical weather data, severe weather alerts, or detailed meteorological analysis. No API key needed."
homepage: https://wttr.in/:help
provenance:
  origin: openclaw-derived
  license: MIT
  upstream_url: https://github.com/openclaw/openclaw
  maintained_by: OpenSquilla
metadata:
  {
    "openclaw":
      {
        "emoji": "☔",
        "requires": { "bins": ["curl"] },
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "os": ["darwin"],
              "formula": "curl",
              "bins": ["curl"],
              "label": "Install curl (brew)",
            },
          ],
      },
  }
---

# Weather Skill

Get current weather conditions and forecasts.

## Location

Always include a city, region, or airport code in weather queries.

## Commands

### Current Weather

```bash
# One-line summary
curl "https://wttr.in/London?format=3"

# Detailed current conditions
curl "https://wttr.in/London?0"

# Specific city
curl "https://wttr.in/New+York?format=3"
```

### Forecasts

```bash
# 3-day forecast
curl "https://wttr.in/London"

# Week forecast
curl "https://wttr.in/London?format=v2"

# Specific day (0=today, 1=tomorrow, 2=day after)
curl "https://wttr.in/London?1"
```

### Format Options

```bash
# One-liner
curl "https://wttr.in/London?format=%l:+%c+%t+%w"

# JSON output
curl "https://wttr.in/London?format=j1"

# PNG image
curl "https://wttr.in/London.png"
```

### Format Codes

- `%c` — Weather condition emoji
- `%t` — Temperature
- `%f` — "Feels like"
- `%w` — Wind
- `%h` — Humidity
- `%p` — Precipitation
- `%l` — Location

## Quick Responses

**"What's the weather?"**

```bash
curl -s "https://wttr.in/London?format=%l:+%c+%t+(feels+like+%f),+%w+wind,+%h+humidity"
```

**"Will it rain?"**

```bash
curl -s "https://wttr.in/London?format=%l:+%c+%p"
```

**"Weekend forecast"**

```bash
curl "https://wttr.in/London?format=v2"
```

## Notes

- No API key needed (uses wttr.in)
- Rate limited; don't spam requests
- Works for most global cities
- Supports airport codes: `curl https://wttr.in/ORD`
