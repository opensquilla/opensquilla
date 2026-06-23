# Share Export Unified Bottom Safe Area

## Context

The share image export currently handles bottom spacing through role-specific
rules:

- Assistant exports add bottom padding to the final `.msg-ai-footer`.
- User-only exports add bottom padding to the final `.msg-user`.

Both rules use the same numeric padding, but they do not apply the spacing at
the same semantic layer. This makes the behavior harder to reason about and can
still leave user-message exports visually cramped, because the visible user
content is the inner `.msg-user-bubble`, not the outer `.msg-user` wrapper.

The export should treat this as one shared layout problem: the final visible
content inside the exported card needs a consistent bottom safe area, regardless
of whether the last selected message is from the user or the assistant.

## Goals

- Use one export-specific bottom safe-area model for all selected message roles.
- Preserve the live chat layout; this is an export-template concern only.
- Keep inter-message spacing unchanged for multi-message exports.
- Make tests assert the actual visible-content-to-card-bottom gap, not only the
  presence of padding on a role-specific element.

## Non-Goals

- Do not redesign user or assistant message bubbles.
- Do not change the share modal layout.
- Do not change PNG scale, template width, QR/footer layout, or export filename
  behavior.
- Do not change model/cost metadata visibility rules beyond existing share
  export requirements.

## Requirements

### SAFE-1: Unified Final Content Bottom Spacing

Priority: P1

Required behavior:

- The exported card must include a consistent bottom safe area after the final
  visible content in the selected share set.
- The behavior must apply when the final selected message is a user message.
- The behavior must apply when the final selected message is an assistant
  message with model/meta text as the final visible content.
- The behavior must apply to single-message and multi-message share selections.

Implementation direction:

- Prefer one export-stage rule or wrapper-level mechanism that applies to the
  final exported message/content block independent of role.
- Avoid separate role-specific visual policies unless role-specific structure
  makes them unavoidable.
- If role-specific selectors remain necessary, expose them as implementation
  details behind one shared safe-area constant and one shared test concept.

Acceptance criteria:

- User-only exports have at least the configured safe-area distance between the
  visible user bubble and the card bottom.
- Assistant-last exports have at least the configured safe-area distance between
  the visible assistant footer/meta line and the card bottom.
- Mixed user + assistant exports do not introduce extra spacing between
  selected messages.
- The final export card, QR/footer band, and content card remain visually
  separate.

### SAFE-2: Stronger Regression Tests

Priority: P1

Required behavior:

- Tests must measure the actual visual bottom gap from the last visible content
  box to the exported card/stage bottom.
- Tests must cover at least:
  - user-only selection,
  - assistant-only or assistant-last selection with meta,
  - mixed selection where the final selected message is user.

Implementation direction:

- Extend the existing share export probe to capture:
  - the final selected clone,
  - the final visible content element inside that clone,
  - the final visible content bottom,
  - the exported stage/card bottom.
- Prefer a shared assertion helper for bottom safe-area expectations instead of
  separate user and assistant assertions.

Acceptance criteria:

- A regression that only pads `.msg-ai-footer` fails user-last tests.
- A regression that only pads `.msg-user` without increasing the visible bubble
  gap fails user-only tests.
- Existing cost-removal and sharpness assertions continue to pass.

## Verification Plan

Run after implementation:

```bash
cd opensquilla-webui && npm run typecheck
cd opensquilla-webui && npm run build
cd opensquilla-webui && npx playwright test e2e/share.spec.ts
cd opensquilla-webui && npx playwright test e2e/share-export.spec.ts
```

Manual check:

- Open the Vue control UI through the gateway.
- Share only a user message and confirm the bubble is not cramped against the
  bottom of the content card.
- Share an assistant message with model/meta text and confirm the meta row has
  the same bottom breathing room.
- Share a sequence where the last selected message is a user message and confirm
  the same final bottom spacing.
- Confirm spacing between selected bubbles is not inflated.

## Open Questions

- What exact safe-area value should be used for the final exported content:
  `14px`, `16px`, or a token-derived spacing value?
- Should the safe area be attached to the final message clone, the export stack,
  or a dedicated inner content wrapper?
