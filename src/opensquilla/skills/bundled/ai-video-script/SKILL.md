---
name: ai-video-script
description: "Generate a structured short-video shooting script from a topic. Emits a strict, machine-parseable shot list (3 shots by default) with image prompt + video prompt + voiceover + on-screen text per shot. Trigger when the user asks for a video script, 分镜, 短视频文案, AI视频, 短剧脚本, or wants visual prompts ready for image/video generation."
provenance:
  origin: clawhub-mit0
  license: MIT-0
  upstream_url: https://clawhub.ai/aguo333/ai-video-script
  upstream_version: "1.0.0"
  maintained_by: OpenSquilla
metadata:
  opensquilla:
    risk: low
    capabilities: []
---

# ai-video-script — structured short-video script generator

Turns a topic/keyword + style + duration into a strict-format shooting script
the downstream `nano-banana-pro` and `seedance-2-prompt` skills can parse
without ambiguity. The default emits 3 shots; the caller may ask for 4 or 5.

## Inputs

Free-text via `with.task` / `with.request`:
- Topic / product / story
- Target audience (optional)
- Style (轻松/专业/故事/科普/带货) — narrative style, not render style
- Total duration (15s, 30s, 60s default)
- Aspect ratio (9:16 default, 16:9 optional)
- `N_SHOTS` override (3 default, **1-10 allowed**)

Caller-supplied anchors (used verbatim — this skill never invents them):
- `with.render_style` — one-line aesthetic the per-shot prompts must end
  with. Examples: `2D anime illustration, flat colour, soft cel-shading`,
  `watercolour storybook illustration`, `cinematic photoreal 35mm grain`.
  If absent / empty, emit the literal sentinel `(render style missing)`
  into the RENDER_STYLE field so downstream parsers can fail loudly.
- `with.identity_anchor` — one-line description of the main character(s)
  that every shot must reproduce byte-for-byte. Example: `Lin, a
  25-year-old East Asian woman with chin-length black bob, almond eyes,
  wearing sage-green oversized knit sweater and gold round earrings`. If
  absent / empty, emit the literal sentinel `(identity anchor missing)`
  so callers can detect the gap before spending on image/video gen.

This skill does **not** choose render style or character identity; the
orchestrator (or its user_input clarify step) does. This separation lets
the same skill serve product ads (no human) and short dramas (with
locked characters) without baked-in defaults.

## Output format (STRICT — orchestrators parse this)

Always emit exactly these top-level blocks, in this order:

```
=== OVERVIEW ===
TITLE: <one line>
DURATION_S: <int>
ASPECT_RATIO: <9:16|16:9>
STYLE: <one line>
AUDIENCE: <one line>
N_SHOTS: <int 3-5>
IDENTITY_ANCHOR: <copied verbatim from with.identity_anchor, or "(identity anchor missing)">
RENDER_STYLE: <copied verbatim from with.render_style, or "(render style missing)">

=== SHOT_1 ===
DURATION_S: <int 3-6>
CAMERA: <wide|medium|close-up + push/pull/pan/tilt/static>
IMAGE_PROMPT: <IDENTITY_ANCHOR verbatim>, <scene/action>, <RENDER_STYLE verbatim>, --ar 9:16
VIDEO_PROMPT: <IDENTITY_ANCHOR verbatim>, <one major action + camera move + duration hint>, <RENDER_STYLE verbatim>, aspect_ratio: 9:16, no watermark, no logo, no subtitles
VOICEOVER: <one line, max 20 Chinese chars or 30 English words>
ON_SCREEN_TEXT: <one short line or empty>

=== SHOT_2 ===
... (same fields, IMAGE_PROMPT and VIDEO_PROMPT must begin with the
exact same IDENTITY_ANCHOR bytes as SHOT_1)

=== SHOT_3 ===
... (same fields)
```

For any `N_SHOTS` between 1 and 10, emit exactly that many
`=== SHOT_K ===` blocks numbered 1..N_SHOTS, each with the same fields.
Do not emit shot blocks beyond `N_SHOTS`. Never skip a field; use the
literal value `none` for empty `ON_SCREEN_TEXT`.

`N_SHOTS` semantics:
- 1: a single hero shot (5-10s typical) — product/landscape vignette.
- 2-3: classic short-form story arc.
- 4-6: extended narrative with multiple beats; good for 45-60s drama.
- 7-10: stretched-form drama; total duration grows linearly with cost.

## Rules

1. **Identity continuity** — `with.identity_anchor` is pasted byte-for-byte
   at the start of every shot's IMAGE_PROMPT and VIDEO_PROMPT. Do not
   paraphrase, summarize, or pronoun-substitute it. If shot 3's anchor
   text differs by one comma from shot 1's, you wrote it wrong.
2. **Visual concreteness** — replace abstract verbs with observable action:
   "a young woman in a red trench coat walks through rain-soaked neon
   streets" >> "a woman walking".
3. **IP-safe** — do not use franchise names, character names, brand terms,
   or "style of" references. Invent original names if needed.
4. **No multi-line values** — IMAGE_PROMPT, VIDEO_PROMPT, VOICEOVER,
   ON_SCREEN_TEXT must each be a single line.
5. **Aspect ratio explicit** — every IMAGE_PROMPT ends with the literal
   token `--ar 9:16` (or `--ar 16:9`); every VIDEO_PROMPT ends with the
   literal token `aspect_ratio: 9:16` (or 16:9).
6. **Duration math** — `sum(SHOT_i.DURATION_S) == OVERVIEW.DURATION_S` ±2s.
7. **Voiceover length** — total voiceover should be speakable in
   `DURATION_S` seconds (~3 Chinese chars/sec, ~2 English words/sec).
8. **Match the user's language** — write **all** fields (TITLE, STYLE,
   AUDIENCE, IDENTITY_ANCHOR, RENDER_STYLE, IMAGE_PROMPT, VIDEO_PROMPT,
   VOICEOVER, ON_SCREEN_TEXT) in the **same language the user wrote in**.
   - The current downstream image/video models — `google/gemini-3.1-flash-image-preview`
     and `bytedance/seedance-2.0` — both accept Chinese natively.
     Seedance (ByteDance) is in fact a Chinese-first model and tends to
     produce **more on-topic results** with Chinese prompts when the
     story itself is Chinese (e.g. 咖啡店偶遇 / 国风武侠 / 校园回忆).
   - Do **not** translate the user's Chinese topic into English just to
     fill IMAGE_PROMPT — that loses cultural detail and often hallucinates
     a Western-coded substitute.
   - Mixed-language input (English topic + Chinese voiceover note,
     vice-versa) → the *bulk* of prompts follow whichever language the
     **topic/story** is in; localised fields like VOICEOVER may follow
     the language explicitly named by the user.
   - English remains valid: pick it when the user wrote in English, or
     when the user explicitly asked for English prompts.
9. **Plain text only — no emoji, no decorative symbols.** The script
   flows through Python subprocesses on Windows consoles whose default
   code page (cp936/GBK) cannot encode `✅`, `❌`, `✨`, `🎬`, or any
   non-BMP character. The orchestrator will crash with a
   `UnicodeEncodeError` if any field contains one. Use plain CJK + ASCII
   only. Do not "decorate" changed lines with checkmarks even when
   re-drafting.
10. **Style-tag exception** — RENDER_STYLE is a label, not a sentence.
   It's fine to keep canonical aesthetic tags in their native vocabulary:
   `2D anime illustration` and `水墨风, monochrome with one accent` are
   both valid; mixed-language tags like `水墨风 ink-wash, paper texture`
   also work. Whichever form the caller passes in via `with.render_style`
   is copied verbatim.

## Style presets (only adjust IMAGE_PROMPT/VIDEO_PROMPT modifiers)

- **商业 / Commercial**: "studio lighting, hero product shot, clean
  background, shallow depth of field"
- **故事 / Story**: "cinematic, soft natural light, 35mm film grain,
  shallow depth of field"
- **科普 / Educational**: "isometric infographic style, flat colour,
  bright key light, clean composition"
- **带货 / E-commerce**: "high-key lighting, white seamless background,
  product 360 spin"
- **轻松 / Casual**: "bright daylight, handheld feel, vibrant colours"

## Negative defaults (always add to VIDEO_PROMPT)

`no watermark, no logo, no subtitles, no on-screen text outside ON_SCREEN_TEXT.`

## Example A — Chinese request, all-Chinese script (30s, 3 shots, 9:16)

User wrote the request in Chinese, so every field is Chinese — including
IMAGE_PROMPT and VIDEO_PROMPT. Seedance 2.0 and Gemini 3.1 image both
handle these prompts natively.

Caller passes:
- `with.identity_anchor` = `林,25岁东亚女性,齐颌黑色波波头,杏仁眼,鼠尾草绿色超大针织毛衣,金色圆耳环;陈,26岁东亚男性,短黑发,海军蓝校队夹克,棕色帆布托特包`
- `with.render_style` = `2D 动漫插画,扁平上色,柔和赛璐璐阴影,手绘线条`

```
=== OVERVIEW ===
TITLE: 咖啡店偶遇
DURATION_S: 30
ASPECT_RATIO: 9:16
STYLE: 故事
AUDIENCE: 20-30 都市青年
N_SHOTS: 3
IDENTITY_ANCHOR: 林,25岁东亚女性,齐颌黑色波波头,杏仁眼,鼠尾草绿色超大针织毛衣,金色圆耳环;陈,26岁东亚男性,短黑发,海军蓝校队夹克,棕色帆布托特包
RENDER_STYLE: 2D 动漫插画,扁平上色,柔和赛璐璐阴影,手绘线条

=== SHOT_1 ===
DURATION_S: 9
CAMERA: 中景,静止
IMAGE_PROMPT: 林,25岁东亚女性,齐颌黑色波波头,杏仁眼,鼠尾草绿色超大针织毛衣,金色圆耳环;陈,26岁东亚男性,短黑发,海军蓝校队夹克,棕色帆布托特包,林独自坐在木质咖啡桌前手捧白色陶瓷杯,温暖琥珀色吊灯,2D 动漫插画,扁平上色,柔和赛璐璐阴影,手绘线条,--ar 9:16
VIDEO_PROMPT: 林,25岁东亚女性,齐颌黑色波波头,杏仁眼,鼠尾草绿色超大针织毛衣,金色圆耳环;陈,26岁东亚男性,短黑发,海军蓝校队夹克,棕色帆布托特包,林望向咖啡店窗外神思飘远,静止镜头 0-9s,温暖琥珀色吊灯,2D 动漫插画,扁平上色,柔和赛璐璐阴影,手绘线条,aspect_ratio: 9:16,no watermark, no logo, no subtitles
VOICEOVER: 推开那扇熟悉的咖啡店门。
ON_SCREEN_TEXT: none

=== SHOT_2 ===
DURATION_S: 11
CAMERA: 特写 + 缓慢摇镜
IMAGE_PROMPT: 林,25岁东亚女性,齐颌黑色波波头,杏仁眼,鼠尾草绿色超大针织毛衣,金色圆耳环;陈,26岁东亚男性,短黑发,海军蓝校队夹克,棕色帆布托特包,陈在咖啡店门口驻足眼神惊讶认出对方,林抬头转身惊讶相视,2D 动漫插画,扁平上色,柔和赛璐璐阴影,手绘线条,--ar 9:16
VIDEO_PROMPT: 林,25岁东亚女性,齐颌黑色波波头,杏仁眼,鼠尾草绿色超大针织毛衣,金色圆耳环;陈,26岁东亚男性,短黑发,海军蓝校队夹克,棕色帆布托特包,陈停步在咖啡店门口眼神惊讶,镜头缓慢摇向林,林转身惊讶,0-11s,2D 动漫插画,扁平上色,柔和赛璐璐阴影,手绘线条,aspect_ratio: 9:16,no watermark, no logo, no subtitles
VOICEOVER: 抬头的一瞬间,对上了那双熟悉的眼睛。
ON_SCREEN_TEXT: 林 & 陈

=== SHOT_3 ===
DURATION_S: 10
CAMERA: 双人中景,静止
IMAGE_PROMPT: 林,25岁东亚女性,齐颌黑色波波头,杏仁眼,鼠尾草绿色超大针织毛衣,金色圆耳环;陈,26岁东亚男性,短黑发,海军蓝校队夹克,棕色帆布托特包,林与陈在小圆桌前面对面而坐,中间两杯拿铁,皆露微笑,2D 动漫插画,扁平上色,柔和赛璐璐阴影,手绘线条,--ar 9:16
VIDEO_PROMPT: 林,25岁东亚女性,齐颌黑色波波头,杏仁眼,鼠尾草绿色超大针织毛衣,金色圆耳环;陈,26岁东亚男性,短黑发,海军蓝校队夹克,棕色帆布托特包,林与陈在咖啡桌前面对面而坐相视一笑开始交谈,温暖亲密氛围,静止镜头 0-10s,2D 动漫插画,扁平上色,柔和赛璐璐阴影,手绘线条,aspect_ratio: 9:16,no watermark, no logo, no subtitles
VOICEOVER: 三年未见,曾经的故事化作此刻一笑。
ON_SCREEN_TEXT: 好久不见
```

## Example B — English request, all-English script (same flow)

Caller passes:
- `with.identity_anchor` = `Lin, 25-year-old East Asian woman, chin-length black bob, almond eyes, sage-green oversized knit sweater, gold round earrings; Chen, 26-year-old East Asian man, short black hair, navy blue varsity jacket, brown canvas tote`
- `with.render_style` = `2D anime illustration, flat colour, soft cel-shading`

```
=== OVERVIEW ===
TITLE: 咖啡店偶遇
DURATION_S: 30
ASPECT_RATIO: 9:16
STYLE: 故事 / Story
AUDIENCE: 20-30 都市青年
N_SHOTS: 3
IDENTITY_ANCHOR: Lin, 25-year-old East Asian woman, chin-length black bob, almond eyes, sage-green oversized knit sweater, gold round earrings; Chen, 26-year-old East Asian man, short black hair, navy blue varsity jacket, brown canvas tote
RENDER_STYLE: 2D anime illustration, flat colour, soft cel-shading

=== SHOT_1 ===
DURATION_S: 9
CAMERA: medium, static
IMAGE_PROMPT: Lin, 25-year-old East Asian woman, chin-length black bob, almond eyes, sage-green oversized knit sweater, gold round earrings; Chen, 26-year-old East Asian man, short black hair, navy blue varsity jacket, brown canvas tote, Lin sits alone at wooden cafe table holding white ceramic cup, warm amber pendant lights, 2D anime illustration, flat colour, soft cel-shading, --ar 9:16
VIDEO_PROMPT: Lin, 25-year-old East Asian woman, chin-length black bob, almond eyes, sage-green oversized knit sweater, gold round earrings; Chen, 26-year-old East Asian man, short black hair, navy blue varsity jacket, brown canvas tote, Lin gazes out the cafe window absentmindedly, static camera 0-9s, warm amber pendant lights, 2D anime illustration, flat colour, soft cel-shading, aspect_ratio: 9:16, no watermark, no logo, no subtitles
VOICEOVER: 推开那扇熟悉的咖啡店门。
ON_SCREEN_TEXT: none

=== SHOT_2 ===
DURATION_S: 11
CAMERA: close-up + slow pan
IMAGE_PROMPT: Lin, 25-year-old East Asian woman, chin-length black bob, almond eyes, sage-green oversized knit sweater, gold round earrings; Chen, 26-year-old East Asian man, short black hair, navy blue varsity jacket, brown canvas tote, Chen pauses mid-step at cafe door eyes wide with recognition, Lin turns head in surprise, 2D anime illustration, flat colour, soft cel-shading, --ar 9:16
VIDEO_PROMPT: Lin, 25-year-old East Asian woman, chin-length black bob, almond eyes, sage-green oversized knit sweater, gold round earrings; Chen, 26-year-old East Asian man, short black hair, navy blue varsity jacket, brown canvas tote, Chen pauses at cafe door eyes wide with recognition, camera slowly pans to Lin who turns in surprise, 0-11s, 2D anime illustration, flat colour, soft cel-shading, aspect_ratio: 9:16, no watermark, no logo, no subtitles
VOICEOVER: 抬头的一瞬间,对上了那双熟悉的眼睛。
ON_SCREEN_TEXT: 林 & 陈

=== SHOT_3 ===
DURATION_S: 10
CAMERA: medium two-shot, static
IMAGE_PROMPT: Lin, 25-year-old East Asian woman, chin-length black bob, almond eyes, sage-green oversized knit sweater, gold round earrings; Chen, 26-year-old East Asian man, short black hair, navy blue varsity jacket, brown canvas tote, Lin and Chen face each other across small round cafe table, two latte cups between them, both smile, 2D anime illustration, flat colour, soft cel-shading, --ar 9:16
VIDEO_PROMPT: Lin, 25-year-old East Asian woman, chin-length black bob, almond eyes, sage-green oversized knit sweater, gold round earrings; Chen, 26-year-old East Asian man, short black hair, navy blue varsity jacket, brown canvas tote, Lin and Chen sit face to face at cafe table they smile and begin talking warm intimate atmosphere, static camera 0-10s, 2D anime illustration, flat colour, soft cel-shading, aspect_ratio: 9:16, no watermark, no logo, no subtitles
VOICEOVER: 三年未见,曾经的故事化作此刻一笑。
ON_SCREEN_TEXT: 好久不见
```

Note how the IDENTITY_ANCHOR string is the **first comma-separated
segment of every IMAGE_PROMPT and VIDEO_PROMPT**, byte-identical across
shot 1 / 2 / 3. Same goes for the RENDER_STYLE clause near the end.
That repetition is what gives the video model a stable identity anchor.

## What this skill does NOT do

- Does not call any image/video API itself — it only emits text.
- Does not invent SHOT durations that violate `OVERVIEW.DURATION_S`.
- Does not produce more than 5 shots in a single pass.
