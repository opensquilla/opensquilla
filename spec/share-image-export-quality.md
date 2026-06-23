# Share Image Export Quality Spec

Status: Draft
Owner: Frontend
Last updated: 2026-06-17
Scope: `opensquilla-webui/`

## Background

The chat share flow lets users select bubbles, generate a PNG preview, and then
download or copy the image. Recent manual review found three export quality
issues:

- The final assistant meta line can sit too close to the bottom edge of the
  exported conversation card.
- The generated PNG can look blurry, especially when viewed on high-density
  screens or displayed larger than its exported CSS size.
- The cost amount, for example `$0.000646`, must not appear in the exported
  share image. The model name may remain, but cost is private operational
  metadata and must stay aligned with the existing export assertions.

## Current Findings

Relevant files:

- `opensquilla-webui/src/composables/chat/useChatShareExport.ts`
- `opensquilla-webui/src/components/chat/AssistantMessage.vue`
- `opensquilla-webui/src/components/chat/SharePreviewModal.vue`
- `opensquilla-webui/e2e/share-export.spec.ts`

The export pipeline currently clones live message DOM into an offscreen export
stage, rasterizes that stage with `html-to-image`, and then draws the resulting
canvas into a fixed share template.

Key observed implementation details:

- `useChatShareExport.ts` uses `toCanvas(...)` from `html-to-image`.
- Export content width is fixed at `704px`; template width is fixed at `760px`.
- `captureScale()` is capped by `CAPTURE_SCALE_LIMIT = 2`.
- The final template draws the rasterized content canvas via `drawImage(...)`.
- `AssistantMessage.vue` gives `.msg-ai-footer` only top spacing, while
  `.msg-ai-meta` has no bottom padding or margin.
- `.msg-meta__cost` is already listed in the clone strip selectors.
- `share-export.spec.ts` already asserts that the export clone has zero
  `.msg-meta__cost` elements and that exported text does not match dollar-cost
  content.

## Goals

- Give the last visible meta line enough bottom breathing room in the exported
  conversation card.
- Improve generated PNG sharpness without changing the share flow interaction.
- Ensure cost metadata is never visible in exported share images.
- Keep the existing model-name visibility behavior unless a separate product
  decision changes it.
- Keep the export deterministic enough for existing Playwright coverage.

## Non-Goals

- Do not redesign the full chat message UI.
- Do not redesign the share preview modal.
- Do not change pricing, usage, or assistant message metadata collection.
- Do not remove model names from the export unless separately approved.
- Do not introduce a network-dependent export service.

## Requirements

### SHARE-1: Bottom spacing for exported final content

Priority: P1
Risk: Low

Required behavior:

- The exported image must add visible bottom spacing after the final visible
  content in the selected share set.
- This includes assistant messages whose final visible line is model/meta text
  and user-only exports where the selected user bubble is the final content.
- The spacing should be export-specific or otherwise preserve the live chat
  layout unless changing live layout is explicitly desired.
- The selected content card should not appear clipped or visually cramped at
  the bottom edge.

Implementation direction:

- Prefer export-stage CSS in `shareExportCss()` if the live chat layout should
  remain unchanged.
- Target the exported assistant footer or the final exported message rather
  than adding unrelated global padding that changes QR/footer spacing.
- Account for both single-message and multi-message share selections.

Acceptance criteria:

- A selected assistant message whose last visible line is model/meta text has
  clear bottom space before the card border.
- A selected user message by itself also has clear bottom space before the card
  border.
- Multi-message exports do not gain excessive vertical gaps between bubbles.
- The share footer and QR area remain visually separate from the content card.

### SHARE-2: Sharper PNG output

Priority: P1
Risk: Medium

Required behavior:

- The exported PNG should render text sharply in the preview and after download.
- The implementation should avoid unnecessary bitmap resampling where practical.
- If raster resampling remains necessary, the export scale must be high enough
  that normal high-DPI viewing does not make text look soft.

Implementation direction:

- Review the two-step raster path:
  1. DOM to `contentCanvas` via `html-to-image`.
  2. `contentCanvas` to final template via `drawImage(...)`.
- Avoid downscaling and then upscaling text where possible.
- Consider aligning capture width and final draw width, or increasing the
  internal export scale in a bounded way.
- Preserve a reasonable maximum canvas size and keep the existing tall-image
  guard behavior.

Acceptance criteria:

- Downloaded PNG text is visibly sharper than the current output at the same
  preview size.
- Export dimensions remain predictable and do not exceed browser canvas limits
  for normal selected chat ranges.
- Existing light/dark export theme switching still works.
- Copy image and download image continue to use the same rendered asset.

### SHARE-3: Remove cost metadata from share exports

Priority: P0
Risk: Low

Required behavior:

- Cost text such as `$0.000646` must never appear in the share preview,
  copied image, or downloaded PNG.
- `.msg-meta__cost` must be removed from the cloned export DOM before
  rasterization.
- Existing e2e expectations that assert no `.msg-meta__cost` and no dollar-cost
  text must remain aligned with implementation behavior.
- Model name text such as `deepseek-v4-flash-20260423` may remain visible unless
  a separate privacy/product requirement says otherwise.

Implementation direction:

- Keep `.msg-meta__cost` in `SHARE_CLONE_STRIP_SELECTORS`.
- Check whether stale built gateway assets or stale browser state can serve an
  older export implementation.
- After implementation, rebuild the Web UI assets served by the gateway so
  source and packaged dist behavior match.

Acceptance criteria:

- `opensquilla-webui/e2e/share-export.spec.ts` keeps asserting:
  - `costEls` is `0`.
  - exported text does not match dollar-cost content.
- Manual export of a message with model and cost metadata includes the model
  name but excludes the `$...` amount.
- The generated preview image, copied image, and downloaded PNG are consistent.

### SHARE-4: Share mode isolates message edit controls

Priority: P0
Risk: Low

Required behavior:

- Entering share mode must prevent accidental message editing or replay actions
  from the message list.
- User message `Edit`, assistant `Regenerate`, and whole-conversation `Fork`
  controls must not be available while share mode is active.
- Bubble selection must continue to work by clicking the bubble or its share
  picker.

Implementation direction:

- Prefer not rendering message action rows while `shareMode` is true, instead of
  relying on click guards around destructive actions.
- Keep the share banner controls as the only active share-mode command surface.

Acceptance criteria:

- In share mode, `.msg-user-actions` and `.msg-ai-actions` are absent from the
  live message list.
- The `Edit`, `Regenerate`, and `Fork conversation` buttons are absent in share
  mode.
- Clicking a user bubble still selects it for sharing.

## Verification Plan

Run after implementation:

```bash
cd opensquilla-webui && npm run typecheck
cd opensquilla-webui && npm run build
cd opensquilla-webui && npx playwright test e2e/share.spec.ts
cd opensquilla-webui && npx playwright test e2e/share-export.spec.ts
```

Manual browser check:

- Start the gateway and open the Vue control UI.
- Generate an assistant message that includes model and cost metadata.
- Select the assistant message for sharing.
- Open the share preview.
- Confirm the bottom meta line has comfortable spacing from the card border.
- Select only a user message and confirm the exported card still has bottom
  breathing room.
- Enter share mode and confirm message edit/replay/fork controls are hidden.
- Confirm the preview text is sharp at normal preview size.
- Download the PNG and inspect it at 100 percent scale.
- Confirm the model name remains visible.
- Confirm no dollar-cost amount appears anywhere in the image.

## Open Questions

- Should export scale be increased globally, or only when browser/device DPR
  suggests the current cap is insufficient?
- Should the exported PNG report a larger logical width, or keep the current
  `760px` template contract while improving physical pixel density?
- Should the share preview modal display the image at natural CSS size or limit
  it to avoid browser-side upscaling?
