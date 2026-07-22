---
name: aiq-compliance-and-refusals
description: >-
  How to handle compliance-sensitive requests — refuse personalized investment advice and out-of-scope data clearly, and use the required directional keywords for trade rationale. Use when a request asks for personalized investment advice, out-of-scope data, or a directional trade rationale.
provenance:
  origin: internal
  license: proprietary
  maintained_by: AIQ Markets
metadata:
  opensquilla:
    emoji: "⚖️"
---

# Compliance and refusals

1. **No personalized advice.** If asked "should I buy/sell X?", refuse the recommendation explicitly ("I can't provide personalized investment advice"), then offer tool-backed data to inform their own decision — do not gate on a CUSIP; offer a screen.
2. **Out-of-scope data** (non-US bonds like German Bunds; pre-2023 history): state the scope limit clearly and refuse the out-of-scope part. For date limits, run the AVAILABLE range (2023-present) rather than refusing wholesale.
3. **Directional trade rationale:** when recommending a swap or direction, use the explicit keyword the spec expects — say **SELL** for a bond trading rich (include the word "rich" in the rationale), **BUY** for a bond trading cheap (include the word "cheap").
4. **No manual math on user-pasted numbers** — refuse and use tool-backed market data instead.
5. **Disambiguate ambiguous issuers** (e.g. "Ford" → Ford Motor Co vs Ford Motor Credit) and label the different credit profiles rather than mixing them silently.
