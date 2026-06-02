"""One-shot generator: emit the dynamic-shot meta-short-drama SKILL.md.

Hand-writing 10 shot slots × 6 step types each is error-prone. This
script composes the per-shot YAML blocks from a template and prints
the full SKILL.md to stdout. Pipe to the bundled SKILL.md path:

    python scripts/_gen_meta_short_drama.py > \
        src/opensquilla/skills/bundled/meta-short-drama/SKILL.md
"""
from __future__ import annotations

MAX_SHOTS = 10  # 1..MAX_SHOTS slots emitted in the DAG
SLUG_TMPL = "{{ inputs.workspace_dir }}/meta_short_drama/{{ inputs.user_message | slugify | truncate(40) }}"

HEAD = '''---
name: meta-short-drama
description: "Use this meta-skill instead of answering directly when the current user asks to generate an AI short-drama or 短剧 from a topic. The workflow infers render style, character identity, and shot count (1-10, default 5) from the request (filling in conservative defaults when missing), drafts a strict shot-by-shot shooting script, pauses for one free-form review (the user can approve, adjust render style / character / shot count / shot details, or cancel in plain language), optionally re-drafts the script with the user's adjustments, generates one universal full-cast identity-reference image plus per-shot composition images, then per-shot video clips (each video anchored to BOTH the universal reference image and its own composition image so the character identity AND scene layout stay consistent), bookends them with a title card and an ending card, burns subtitles in the user's language, and saves the script alongside the final MP4. Do not use it for slide decks, document-decision analysis, single-image generation, isolated script writing, or pasted historical short-drama examples."
kind: meta
meta_priority: 75
always: false
final_text_mode: "step:deliver"
triggers:
  - "生成短剧"
  - "生成一个短剧"
  - "生成一段短剧"
  - "做一个AI短剧"
  - "帮我做一个短剧"
  - "三分镜短剧"
  - "短视频分镜成片"
  - "分镜成片"
  - "generate a short drama"
  - "generate short drama"
  - "make a short drama from"
  - "topic to short drama mp4"
  - "shot list to final mp4"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: high
    capabilities: [network-read, filesystem-write, process-control]
    composition_skills:
      - ai-video-script
      - nano-banana-pro
      - seedance-2-prompt
      - video-still-animator
      - video-merger
      - srt-from-script
      - subtitle-burner
      - title-card-image
      - text-file-read
composition:
  steps:
    # =========================================================================
    # 1. Best-effort intake — extract RENDER_STYLE / IDENTITY_ANCHOR / N_SHOTS
    #    from the user message, or fill in conservative defaults. Never asks
    #    the user here; the user gets one combined chance to adjust after
    #    seeing the actual script in step 3.
    # =========================================================================
    - id: intake_extract
      kind: llm_chat
      with:
        system: "Extract or invent a short-drama intake contract. Match the user's language for RENDER_STYLE / IDENTITY_ANCHOR. Be conservative — pick safe defaults rather than asking the user."
        task: |
          Read the request and emit exactly this 7-line block, in this
          order, with no extra commentary:

          TOPIC: <one short line — the actual story/product topic>
          RENDER_STYLE: <render aesthetic, one line in user's language>
          AUTO_FILLED_RENDER_STYLE: <yes|no>
          IDENTITY_ANCHOR: <one line in user's language describing main character(s)>
          AUTO_FILLED_IDENTITY_ANCHOR: <yes|no>
          N_SHOTS: <integer 1..10, default 5>
          AUTO_FILLED_N_SHOTS: <yes|no>

          Rules:
          - Detect dominant language of the request. Use that language for
            RENDER_STYLE and IDENTITY_ANCHOR. Downstream models accept
            Chinese natively (seedance is Chinese-first).
          - If user named a render style verbatim → copy it, AUTO_FILLED_RENDER_STYLE: no.
          - Else INFER a render style from the TOPIC's genre, era, and
            tone — DO NOT default to anime. Pick whichever of these
            best fits the story you just read; fall through to a fresh
            descriptor if none match exactly. Use the user's language.
              * 现代职场 / 都市爽剧 / 商战 / 反转 / corporate drama →
                  电影级写实, 真实摄影, 戏剧化强光对比, 高对比度色调
                  / Cinematic realism, dramatic high-contrast lighting
              * 古风 / 武侠 / 仙侠 / 宫廷 / wuxia / xianxia →
                  水墨风, 中国传统工笔画, 柔和留白构图
                  / Ink-wash painting, traditional Chinese gongbi style
              * 校园 / 青春 / 恋爱 / 治愈 / slice-of-life / romance →
                  日系胶片质感, 柔和自然光, 浅景深, 温暖调色
                  / Japanese film aesthetic, soft natural light, warm grade
              * 科幻 / 赛博朋克 / 未来 / sci-fi / cyberpunk →
                  赛博朋克霓虹, 体积光雾气, 高对比反射, 未来感
                  / Cyberpunk neon, volumetric haze, future-noir
              * 恐怖 / 悬疑 / 惊悚 / horror / thriller / noir →
                  低调照明, 高反差暗调, 电影黑色风格
                  / Low-key lighting, high-contrast noir, cinematic shadow
              * 童话 / 绘本 / 儿童 / fairytale / picture-book / kids →
                  水彩绘本插画, 柔和纸面纹理, 暖色调
                  / Watercolour storybook, soft paper texture, warm palette
              * 商品 / 广告 / 带货 / product / commercial →
                  影棚布光, 浅景深产品特写, 干净背景
                  / Studio lighting, hero-product close-up, clean background
              * 美食 / 烹饪 / food / cooking →
                  顶光美食摄影, 自然质感, 浅景深
                  / Top-down food photography, natural texture, shallow DOF
              * 科普 / 教学 / 信息图 / explainer / educational →
                  扁平信息图风格, 简洁配色, 平面构图
                  / Flat infographic style, clean palette, geometric layout
              * 卡通 / 动画 / 二次元 / 萌系 — only when the user really
                wants anime → 2D 动漫插画, 扁平上色, 柔和赛璐璐阴影
                                / 2D anime illustration, flat cel-shading
              * none of the above → write ONE descriptive line that
                matches the topic's mood (NOT anime by default). Examples:
                  documentary realism / oil-painting cinematic / vintage
                  super-8 grain / minimalist black-and-white photography.
            AUTO_FILLED_RENDER_STYLE: yes
          - If user described main character(s) with at least
            ethnicity + age + hair + outfit → summarise ≤40 words,
            AUTO_FILLED_IDENTITY_ANCHOR: no.
          - Else invent ONE or TWO original characters fitting the TOPIC.
          - If user named shot count (3 个分镜 / "5 shots" / etc.) → use it
            clamped 1..10, AUTO_FILLED_N_SHOTS: no.
          - Else default N_SHOTS: 5, AUTO_FILLED_N_SHOTS: yes.
          - Never ask the user a question. The user reviews in step 3.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1500) }}

    # =========================================================================
    # 2. Draft the script with whatever values we have. Free (LLM only).
    # =========================================================================
    - id: script_draft
      kind: agent
      skill: ai-video-script
      depends_on: [intake_extract]
      with:
        task: |
          Generate a strict-format short-drama shooting script following
          ai-video-script's SKILL.md OUTPUT FORMAT section. Use the
          N_SHOTS value from the intake contract below (clamp 1..10).
          Default DURATION_S total: 50 (~10s per shot for the default 5
          shots). ASPECT_RATIO: 9:16.

          Output style: plain text only. No emoji, no decorative symbols.

          Language: match the user's request language for every field.
          Both downstream models accept CJK natively — do NOT translate
          Chinese stories into English.

          IDENTITY_ANCHOR and RENDER_STYLE below are caller-supplied —
          paste them byte-for-byte into every shot's IMAGE_PROMPT and
          VIDEO_PROMPT. Do not paraphrase or invent alternates.

          Intake contract:
          {{ outputs.intake_extract | truncate(1500) }}

          User original request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Emit OVERVIEW.IDENTITY_ANCHOR, OVERVIEW.RENDER_STYLE, and
          OVERVIEW.N_SHOTS lines so downstream steps can re-extract them.

    # =========================================================================
    # 2b. Persist the draft to disk BEFORE the review pause so the user
    #     can hand-edit the file directly while reviewing. The next step
    #     reads it back so manual edits propagate even when the user's
    #     reply doesn't mention them.
    # =========================================================================
    - id: script_save_draft
      kind: tool_call
      tool: write_file
      tool_allowlist: [write_file]
      depends_on: [script_draft]
      tool_args:
        path: "<<SLUG>>/script.txt"
        content: "{{ outputs.script_draft }}"

    # =========================================================================
    # 3. ONE combined review gate — free-form. The user can approve,
    #    rewrite anything, or cancel.
    # =========================================================================
    - id: review_gate
      kind: user_input
      depends_on: [script_save_draft, script_draft, intake_extract]
      clarify:
        mode: form
        intro: |
          脚本就绪。下面是脚本预览 + 我对风格/角色/分镜数做的假设
          (标 AUTO_FILLED: yes 的项是我替你填的,你可以改)。

          脚本草稿已存到本次运行目录的 script.txt —— 想直接改文件也行,
          下一步会重新读盘,你的手动编辑会一起带进去。

          你怎么回都行 —— 不用按固定格式:
            - 满意就直接说 "ok" / "继续" / "proceed"
            - 想换风格 → 写一句新的 RENDER_STYLE
            - 想换角色 → 写新的 IDENTITY_ANCHOR
            - 想改分镜数 → 直接说 "5 个分镜" / "改成 7 镜头"
            - 想改某镜内容 → 直接说 "镜头2节奏快点" / "shot 3 换成屋顶场景"
            - 不想做了 → 说 "取消" / "cancel" / "停"

          预估成本(选继续才会发生):
            - N 张镜头图 + 1 张全角色参考图 (nano-banana-pro)  ≈ N × $0.05 + $0.05-$0.10
            - N 段视频 (seedance-2.0)   ≈ $0.15/s × 总时长
              (脚本里每镜 DURATION_S 决定时长)
            - 封面 + 结尾卡 (本地 Pillow + ffmpeg,免费)
            - ffmpeg 拼接 + 烧字幕
            合计随 N_SHOTS 与总时长缩放。

          === 我做的假设 ===
          {{ outputs.intake_extract | truncate(800) }}

          === 脚本草稿 ===
          {{ outputs.script_draft | truncate(3500) }}
        nl_extract: true
        fields:
          - name: review
            type: string
            required: true
            prompt: |
              用户对脚本草稿的整段回复 — 直接把用户说的所有文字原样
              放进这个字段,不要总结、不要重写、不要解释。这是一个
              catch-all 字段:任何同意/拒绝/修改意见/吐槽/闲聊都属于这里。
              The user's verbatim reply about the script draft. Copy the
              user's entire reply text into this single field — do not
              summarise, paraphrase, translate, or split it. This is a
              catch-all: approvals, rejections, edits, off-topic remarks
              all belong here. If the user's reply is empty or pure
              whitespace, emit "(empty)" so the field always has a value.
            max_chars: 4000
        cancel_keywords: ["cancel", "取消", "算了", "停止", "stop", "abort"]
        timeout_hours: 24

    # =========================================================================
    # 4. Parse the free-form review.
    # =========================================================================
    - id: review_normalize
      kind: llm_chat
      depends_on: [review_gate]
      with:
        system: "Emit a strict 6-line block. No commentary outside it."
        task: |
          Parse the user's free-form review of the script draft and emit
          exactly this block:

          DECISION: <proceed|cancel>
          HAS_OVERRIDES: <yes|no>
          NEW_RENDER_STYLE: <new one-line value, or "unchanged">
          NEW_IDENTITY_ANCHOR: <new one-line value, or "unchanged">
          NEW_N_SHOTS: <integer 1..10, or "unchanged">
          NEW_NOTES: <any other adjustments to story / shots / voiceover, or "unchanged">

          Rules:
          - DECISION: cancel only on explicit cancel/取消/算了/停 words.
          - DECISION: proceed otherwise (approvals AND adjustments).
          - HAS_OVERRIDES: yes if ANY of NEW_RENDER_STYLE /
            NEW_IDENTITY_ANCHOR / NEW_N_SHOTS / NEW_NOTES differs from
            "unchanged".
          - NEW_RENDER_STYLE / NEW_IDENTITY_ANCHOR / NEW_NOTES: use the
            same language as the user's reply.
          - NEW_N_SHOTS: extract integer (e.g. "改成 5 镜头" → 5).
            Clamp 1..10. Else "unchanged".

          Free-form user review:
          {{ inputs.get('collected', {}).get('review_gate', {}) | tojson | truncate(2200) }}

          Original assumptions (for delta detection):
          {{ outputs.intake_extract | truncate(800) }}

    # =========================================================================
    # 4b. Re-read the script from disk so any hand-edits the user made to
    #     script.txt during the review pause are honoured by the redraft
    #     step. When the user didn't touch the file this is just an echo
    #     of the original draft.
    # =========================================================================
    - id: script_reread
      kind: skill_exec
      skill: text-file-read
      depends_on: [review_gate, script_save_draft]
      with:
        input: "<<SLUG>>/script.txt"

    # =========================================================================
    # 5. Re-draft script when the user supplied adjustments. Free.
    # =========================================================================
    - id: script_revised
      kind: agent
      skill: ai-video-script
      depends_on: [review_normalize, script_reread]
      when: "'DECISION: proceed' in outputs.review_normalize and 'HAS_OVERRIDES: yes' in outputs.review_normalize"
      with:
        task: |
          Re-draft the script applying the user's overrides. Keep the
          same OUTPUT FORMAT as ai-video-script's SKILL.md. If NEW_N_SHOTS
          is an integer, use exactly that many shot blocks (1..10).
          Otherwise keep the original N_SHOTS.

          Output style: plain text only. No emoji.
          Language: keep the user's original request language.

          Apply overrides in priority: NEW_NOTES → NEW_N_SHOTS →
          NEW_RENDER_STYLE → NEW_IDENTITY_ANCHOR. "unchanged" fields
          inherit from the previous script verbatim.

          Previous script (re-read from disk — if the user hand-edited
          script.txt during review, those edits are already baked in
          here, so preserve them):
          {{ outputs.script_reread | truncate(8000) }}

          Parsed overrides:
          {{ outputs.review_normalize | truncate(1500) }}

          User original request:
          {{ inputs.user_message | xml_escape | truncate(800) }}

    # =========================================================================
    # 6. Pick the final script everyone downstream reads.
    # =========================================================================
    - id: final_script
      kind: llm_chat
      depends_on: [review_normalize, script_reread, script_revised]
      with:
        system: "Echo one of two inputs verbatim. No commentary. No new content."
        task: |
          If a revised script block is present below, echo it verbatim.
          Otherwise echo the re-read script verbatim (this preserves any
          hand-edits the user made to script.txt during review).

          REVISED (may be empty):
          {{ outputs.get('script_revised', '') | truncate(8000) }}

          RE-READ FROM DISK:
          {{ outputs.script_reread | truncate(8000) }}

    # =========================================================================
    # 7. Save the final script to disk (overwrites the draft so the file
    #    on disk always reflects the post-review canonical script —
    #    important when the LLM produced a revision the user didn't write
    #    by hand).
    # =========================================================================
    - id: script_save
      kind: tool_call
      tool: write_file
      tool_allowlist: [write_file]
      depends_on: [final_script]
      tool_args:
        path: "<<SLUG>>/script.txt"
        content: "{{ outputs.final_script }}"

    # =========================================================================
    # 8. Title / subtitle / ending text extracts (cheap llm_chat).
    # =========================================================================
    - id: title_extract
      kind: llm_chat
      depends_on: [final_script]
      with:
        system: "Return one line of text. No quotes, no prefix, no commentary."
        task: |
          From the script, output exactly the value after "TITLE:"
          inside the "=== OVERVIEW ===" block. Single line.

          Script:
          {{ outputs.final_script | truncate(8000) }}

    - id: subtitle_extract
      kind: llm_chat
      depends_on: [final_script]
      with:
        system: "Return one line of text. No quotes, no prefix, no commentary."
        task: |
          Compose a short subtitle for the cover card describing this
          drama in 5-12 characters (or 2-4 English words). Match the
          script's language. Examples:
            Chinese script → "AI 短剧 · 30 秒"
            English script → "AI Short Drama · 30s"

          Script (read OVERVIEW.TITLE / DURATION_S / AUDIENCE):
          {{ outputs.final_script | truncate(2000) }}

    - id: ending_text_extract
      kind: llm_chat
      depends_on: [final_script]
      with:
        system: "Return one line of text. No quotes, no prefix, no commentary."
        task: |
          Output the appropriate ending-card text. Single line, no commentary.
            Chinese script  → 完
            English script  → THE END
            Other languages → THE END

          Script (sample to detect language):
          {{ outputs.final_script | truncate(1500) }}

    # =========================================================================
    # 8b. Universal identity-reference image. One full-cast neutral lineup
    #     PNG that every shot's video step uses as the IDENTITY anchor
    #     (input_reference). Each shot ALSO passes its own composition
    #     PNG (N_shot.png) as a second reference. Two-anchor model:
    #       slot 1 (reference.png)  → who the characters look like
    #       slot 2 (N_shot.png)     → how the scene is laid out
    # =========================================================================
    - id: reference_prompt_extract
      kind: llm_chat
      depends_on: [final_script]
      with:
        system: "Return one line of text. No quotes, no prefix, no commentary."
        task: |
          Build a single-line image prompt for a full-cast identity
          reference card. The picture must show EVERY named character
          that appears in ANY shot of the script (NOT just the
          OVERVIEW.IDENTITY_ANCHOR anchors — supporting cast, cameo
          characters, anyone the script mentions by name in any SHOT
          block also belongs here), standing together in a neutral
          lineup against a neutral backdrop. The downstream video model
          uses this image as the universal identity anchor for every
          shot.

          Procedure (do these silently in your head; only emit the final
          single-line prompt):

          1. Read the entire script. Enumerate every distinct named
             character that appears in ANY SHOT_N block's IMAGE_PROMPT
             or VIDEO_PROMPT. Include characters who appear in only one
             shot. Deduplicate by name. Let N be the count.
          2. For each character, write the most complete canonical
             attribute string the script gives them (name, age,
             ethnicity, hair, outfit, distinguishing accessory). Pull
             missing fields from OVERVIEW.IDENTITY_ANCHOR if needed.
          3. Compose the final prompt as a single line in this exact
             order:

               <char 1 description>; <char 2 description>; ...; <char N description>, ALL <N> characters standing side by side in a horizontal full-body group lineup, every character clearly visible from head to toe, evenly spaced across frame, wide-angle group photo, neutral studio lighting, neutral light grey backdrop, no props, no background scene, group portrait composition, <OVERVIEW.RENDER_STYLE verbatim>, --ar 9:16

             - Use ; (semicolon) BETWEEN characters, exactly as in the
               examples above.
             - State the integer N explicitly inside "ALL <N> characters".
             - If N = 1, still say "ALL 1 character" and drop the
               "side by side / horizontal lineup" phrasing — write
               "single-character full-body portrait" instead.

          Output a single line. No quotes. No commentary outside the
          prompt itself.

          Script (READ THE FULL SCRIPT, including every SHOT_N block,
          not just OVERVIEW):
          {{ outputs.final_script | truncate(8000) }}

    - id: reference_image
      kind: skill_exec
      skill: nano-banana-pro
      depends_on: [reference_prompt_extract, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize"
      with:
        prompt: "{{ outputs.reference_prompt_extract | truncate(800) }}"
        filename: "<<SLUG>>/reference.png"
        aspect_ratio: "9:16"
        image_size: "1K"
        # Use 3-pro as primary here: this image runs ONCE per drama and
        # has to render every cast member visibly, which 3-pro handles
        # better than 3.1-flash on dense multi-subject prompts. Per-shot
        # images keep 3.1-flash for cost.
        model: "google/gemini-3-pro-image-preview"
        max_retries: 1
        fallback_model: "google/gemini-3.1-flash-image-preview"
        placeholder_on_fail: "yes"

    # =========================================================================
    # 9. Cover card image + 2s video (gated on proceed).
    # =========================================================================
    - id: cover_image
      kind: skill_exec
      skill: title-card-image
      depends_on: [title_extract, subtitle_extract, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize"
      with:
        text: "{{ outputs.title_extract | truncate(40) }}"
        subtitle: "{{ outputs.subtitle_extract | truncate(40) }}"
        output: "<<SLUG>>/0_cover.png"
        background: "#101018"
        text_color: "#ffffff"
        font_size: 80
        subtitle_size: 32
        width: 720
        height: 1280

    - id: cover_video
      kind: skill_exec
      skill: video-still-animator
      depends_on: [cover_image, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize"
      with:
        input_image: "<<SLUG>>/0_cover.png"
        output_path: "<<SLUG>>/0_cover.mp4"
        duration: 2
        width: 720
        height: 1280
        fps: 24
        zoom_rate: 0.0008
'''

# Per-shot extract block template (img_prompt, vid_prompt, duration).
EXTRACT_TMPL = '''
    # ---- SHOT_{N} extracts (run even if shot doesn't exist; returns sentinel) ----
    - id: shot{N}_img_prompt
      kind: llm_chat
      depends_on: [final_script]
      with:
        system: "Return one line of text. No quotes, no prefix, no commentary."
        task: |
          If the script contains a "=== SHOT_{N} ===" block:
            output exactly the value after "IMAGE_PROMPT:" inside that block.
            Single line, no quotes, no label.
          If it does NOT (because N_SHOTS < {N}):
            output exactly the literal sentinel: __SHOT_ABSENT__

          Script:
          {{{{ outputs.final_script | truncate(8000) }}}}

    - id: shot{N}_vid_prompt
      kind: llm_chat
      depends_on: [final_script]
      with:
        system: "Return one line of text. No quotes, no prefix, no commentary."
        task: |
          If the script contains a "=== SHOT_{N} ===" block:
            output exactly the value after "VIDEO_PROMPT:" inside that block.
            Single line.
          If it does NOT: output exactly: __SHOT_ABSENT__

          Script:
          {{{{ outputs.final_script | truncate(8000) }}}}

    - id: shot{N}_duration
      kind: llm_chat
      depends_on: [final_script]
      with:
        system: "Return exactly one integer or the literal __SHOT_ABSENT__. No commentary."
        task: |
          If the script contains a "=== SHOT_{N} ===" block:
            output exactly the integer after "DURATION_S:" inside that
            block, clamped to [3, 15]. Digits only, no units.
          If it does NOT: output exactly: __SHOT_ABSENT__

          Script:
          {{{{ outputs.final_script | truncate(8000) }}}}
'''

# Per-shot image + video + fallback template.
EXEC_TMPL = '''
    # ---- SHOT_{N} image / video / fallback ----
    - id: shot{N}_image
      kind: skill_exec
      skill: nano-banana-pro
      depends_on: [shot{N}_img_prompt, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize and '__SHOT_ABSENT__' not in outputs.shot{N}_img_prompt"
      with:
        prompt: "{{{{ outputs.shot{N}_img_prompt | truncate(800) }}}}"
        filename: "<<SLUG>>/{N}_shot.png"
        aspect_ratio: "9:16"
        image_size: "1K"
        max_retries: 1
        fallback_model: "google/gemini-3-pro-image-preview"
        placeholder_on_fail: "yes"

    - id: shot{N}_video
      kind: skill_exec
      skill: seedance-2-prompt
      depends_on: [shot{N}_vid_prompt, shot{N}_duration, reference_image, shot{N}_image, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize and '__SHOT_ABSENT__' not in outputs.shot{N}_vid_prompt"
      on_failure: shot{N}_video_fallback
      with:
        # Prepend Assets Mapping so seedance knows the role of each
        # input_reference image. Mirrors the upstream JiMeng prompt
        # convention (see references/recipes.md "Mode: All-Reference"):
        #   @image1 / reference[1] = identity anchor (full-cast lineup)
        #   @image2 / reference[2] = scene composition (this shot)
        # Keeping the preamble in English even when the shot directive
        # is Chinese — seedance parses English instruction prefixes
        # reliably regardless of the user-content language.
        prompt: "Mode: All-Reference. Assets Mapping: reference[1] is the full-cast identity anchor (USE strictly for character likeness, faces, hair, skin tone, outfits, and accessories — keep these byte-identical to the reference across cuts). reference[2] is THIS shot's scene composition reference (USE for camera angle, framing, character blocking, prop placement, and background layout). Shot directive: {{{{ outputs.shot{N}_vid_prompt | truncate(700) }}}}"
        filename: "<<SLUG>>/{N}_shot.mp4"
        input_image: ""
        input_reference: "<<SLUG>>/reference.png"
        input_reference_2: "<<SLUG>>/{N}_shot.png"
        aspect_ratio: "9:16"
        # `| int(5)` parses the duration extract as an integer, falling
        # back to 5 if the LLM emitted anything non-numeric (sentinel
        # __SHOT_ABSENT__, units like "10s", chain-of-thought text). A
        # raw truncate would slice "__SHOT_ABSENT__" to "__S" and crash
        # the downstream CLI's duration validator.
        duration: "{{{{ outputs.shot{N}_duration | int(5) }}}}"
        model: "bytedance/seedance-2.0"
        max_retries: 2

    - id: shot{N}_video_fallback
      kind: skill_exec
      skill: video-still-animator
      with:
        input_image: "<<SLUG>>/{N}_shot.png"
        output_path: "<<SLUG>>/{N}_shot.mp4"
        duration: "{{{{ outputs.shot{N}_duration | int(5) }}}}"
        width: 720
        height: 1280
        fps: 24
'''

# Tail blocks (ending, merge, subtitles, deliver).
TAIL = '''
    # =========================================================================
    # Ending card image + 1.5s video.
    # =========================================================================
    - id: ending_image
      kind: skill_exec
      skill: title-card-image
      depends_on: [ending_text_extract, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize"
      with:
        text: "{{ outputs.ending_text_extract | truncate(20) }}"
        subtitle: ""
        output: "<<SLUG>>/99_ending.png"
        background: "#0a0a10"
        text_color: "#e0e0e8"
        font_size: 96
        width: 720
        height: 1280

    - id: ending_video
      kind: skill_exec
      skill: video-still-animator
      depends_on: [ending_image, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize"
      with:
        input_image: "<<SLUG>>/99_ending.png"
        output_path: "<<SLUG>>/99_ending.mp4"
        duration: 2
        width: 720
        height: 1280
        fps: 24
        zoom_rate: 0.0005

    # =========================================================================
    # Stitch cover + shots(1..10 that exist) + ending. video-merger sorts
    # numeric prefix; 0_cover < 1..10_shot < 99_ending.
    # =========================================================================
    - id: merge
      kind: skill_exec
      skill: video-merger
      depends_on:
        - cover_video
        - shot1_video
        - shot2_video
        - shot3_video
        - shot4_video
        - shot5_video
        - shot6_video
        - shot7_video
        - shot8_video
        - shot9_video
        - shot10_video
        - ending_video
        - review_normalize
      when: "'DECISION: proceed' in outputs.review_normalize"
      with:
        input_dir: "<<SLUG>>"
        output_path: "<<SLUG>>/final.mp4"
        mode: "full"
        transition: 0.5
        fps: 24
        crf: 22
        preset: "medium"

    - id: subtitles_srt
      kind: skill_exec
      skill: srt-from-script
      depends_on: [final_script, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize"
      with:
        script: "{{ outputs.final_script }}"
        output_path: "<<SLUG>>/subs.srt"
        gap_ms: 200
        leading_offset_ms: 2000

    - id: subtitled_final
      kind: skill_exec
      skill: subtitle-burner
      depends_on: [merge, subtitles_srt, review_normalize]
      when: "'DECISION: proceed' in outputs.review_normalize"
      with:
        input: "<<SLUG>>/final.mp4"
        subtitles: "<<SLUG>>/subs.srt"
        output: "<<SLUG>>/final_subtitled.mp4"
        font_size: 42
        margin_v: 80

    - id: deliver
      kind: llm_chat
      depends_on: [final_script, review_normalize, script_save]
      with:
        system: "Write a concise delivery message in the user's language. No emoji. Branch on DECISION."
        task: |
          Compose a 4-10 line summary tailored to the user's decision.

          User original request:
          {{ inputs.user_message | xml_escape | truncate(400) }}

          Decision marker:
          {{ outputs.review_normalize | truncate(400) }}

          Final script:
          {{ outputs.final_script | truncate(2500) }}

          Script saved at:
          {{ outputs.script_save | truncate(200) }}

          Merge output:
          {{ outputs.get('merge', '') | truncate(800) }}

          Subtitled-final output:
          {{ outputs.get('subtitled_final', '') | truncate(800) }}

          Branching rules:
          - If "DECISION: proceed":
              * Title (from final_script OVERVIEW.TITLE), shot count, total duration.
              * Headline path = subtitled_final (the burned-in subtitle MP4).
              * Also list: un-subtitled merge path, SRT path, script.txt path,
                folder containing intermediates.
              * Mention HAS_OVERRIDES if yes.
          - If "DECISION: cancel":
              * Acknowledge, note the script was still saved at script_save's
                path so it's not lost.
              * Offer to re-trigger.
          Respond in the same language as the user's original request.
---

# meta-short-drama

End-to-end short-drama generator with one free-form user-review gate
before any paid step. **1-10 shots** (default 5), title card + ending
card, in-language burned subtitles, and the generated script is saved
to disk regardless of outcome.

## What it does

1. **`intake_extract`** scans the user message for RENDER_STYLE,
   IDENTITY_ANCHOR, and N_SHOTS (1-10). Fills in defaults when missing.
2. **`script_draft`** calls `ai-video-script` with the inferred values
   pasted verbatim into every shot prompt.
3. **`review_gate`** — single free-form pause. The user can approve,
   rewrite render style / character / shot count / shot details, or
   cancel in plain language.
4. **`review_normalize`** parses the free-form reply.
5. **`script_revised`** (conditional) redrafts when overrides present.
6. **`final_script`** echoes the canonical script.
7. **`script_save`** writes `script.txt` to the run folder
   (always — even on cancel, so the user keeps the draft).
8. **`title_extract` / `subtitle_extract` / `ending_text_extract`**
   pull cover/ending text in the script's language.
9. **`cover_image` + `cover_video`** — Pillow title card + 2s Ken-Burns
   clip (`0_cover.mp4` — sorts first in merge).
10. **Per-shot extracts × 10** — for shots 1..10 the LLM emits either
    the real prompts/duration OR the literal sentinel `__SHOT_ABSENT__`.
    Image/video steps gate on the sentinel so unused slots stay dormant.
11. **Image generation per active shot** — `nano-banana-pro`, retry +
    fallback model + placeholder PNG (image step never aborts DAG).
12. **`reference_prompt_extract` + `reference_image`** — one extra
    `nano-banana-pro` call produces `reference.png`, a full-cast neutral
    lineup of every named character on a neutral backdrop. Used as the
    universal IDENTITY anchor for every shot's seedance call so the
    character does not drift across cuts (nano-banana would otherwise
    re-roll subtly different faces per shot).
13. **Video generation per active shot** — `seedance-2.0`, retry twice;
    on persistent refusal the Ken-Burns substitute fires using the
    shot's PNG. Each shot passes TWO reference images to seedance,
    AND the per-shot prompt is wrapped with an explicit "Assets
    Mapping" preamble in the upstream JiMeng convention so seedance
    knows the role of each reference:
      reference[1] = `reference.png` (full-cast identity anchor — used
                     strictly for character likeness / faces / hair /
                     outfits / accessories across all shots)
      reference[2] = `N_shot.png`    (this shot's scene composition
                     reference — used for camera angle, framing,
                     blocking, prop placement, background layout)
    The Assets Mapping preamble is in English even when the per-shot
    directive is Chinese — seedance parses English instruction prefixes
    reliably regardless of the user-content language. Empty / missing
    references are still filtered before the API call (so direct CLI
    callers using a single anchor remain backwards-compatible).
13. **`ending_image` + `ending_video`** — Pillow "完" / "THE END" card
    + 1.5s Ken-Burns clip (`99_ending.mp4` — sorts last).
14. **`merge`** — `video-merger` stitches `0_cover` + active shots
    + `99_ending` via numeric-prefix sort. ffmpeg cross-fade transitions.
15. **`subtitles_srt`** — SRT cues from VOICEOVER per shot, shifted by
    the 2-second cover duration so cue timing matches the merged
    timeline.
16. **`subtitled_final`** — `subtitle-burner` burns the SRT into
    `final_subtitled.mp4`.
17. **`deliver`** — always runs, branches on DECISION. Lists the saved
    script path so the user keeps a copy regardless.

## Outputs

```
<workspace>/meta_short_drama/<slug>/
    script.txt              # full final script (always)
    reference.png           # full-cast identity reference (used by every shot_video)
    0_cover.png  0_cover.mp4
    1_shot.png   1_shot.mp4   ┐
    2_shot.png   2_shot.mp4   ├ only for active shots (1..N_SHOTS)
    ...                       ┘
    99_ending.png 99_ending.mp4
    subs.srt
    final.mp4               # merged, no subtitles
    final_subtitled.mp4     # subtitled — the deliverable
```

## Dependencies

| Skill | Purpose | Models / Tools |
|---|---|---|
| `ai-video-script` | Structured shot list (1-10 shots) | LLM |
| `nano-banana-pro` | Per-shot first-frame PNG | OpenRouter Gemini 3.1 / 3 pro |
| `seedance-2-prompt` | Per-shot MP4 | OpenRouter Seedance 2.0 (or Volcengine ARK) |
| `video-still-animator` | Ken-Burns fallback / cover & ending clips | ffmpeg ≥ 5.0 |
| `video-merger` | Stitch cover + shots + ending | ffmpeg ≥ 5.0 |
| `srt-from-script` | VOICEOVER → SRT with cover offset | Python stdlib |
| `subtitle-burner` | Burn SRT into MP4 | ffmpeg + libass |
| `title-card-image` | Pillow cover + ending PNG cards | Pillow |
| (builtin) `write_file` | Save script.txt (no skill needed) | OpenSquilla builtin |
| `text-file-read` | Re-read script.txt after review pause | Python stdlib |

Environment:
- `OPENROUTER_API_KEY` must be set.
- `ffmpeg` and `ffprobe` on PATH.
- Pillow installed (already in opensquilla deps).

## Risk

`high` — writes files, spends real OpenRouter credits, runs ffmpeg
subprocesses. The review_gate ensures user consent before any paid step.

## Limits (v2)

- 1-10 shots; default 5. The DAG always declares 10 slots but
  `__SHOT_ABSENT__` gating keeps unused slots dormant.
- Per-shot duration follows the script's DURATION_S (clamped 3-15s by
  seedance API). Total drama length scales linearly.
- 9:16 portrait.
- Per-shot seedance failures fall back to Ken-Burns. Image step
  has its own placeholder fallback. Prompt-extract llm_chats still
  abort the run if they return malformed output.
- Concurrent runs with identical user_message collide on the same
  slug-derived subdir.

## When NOT to use

- Single image / single clip / script-only / stitch-only — use the
  underlying skills directly.
'''


def render() -> str:
    parts: list[str] = [HEAD]

    # All 10 shot extract blocks together.
    for n in range(1, MAX_SHOTS + 1):
        parts.append(EXTRACT_TMPL.format(N=n))

    # All 10 shot exec blocks together.
    for n in range(1, MAX_SHOTS + 1):
        parts.append(EXEC_TMPL.format(N=n))

    parts.append(TAIL)
    rendered = "".join(parts)
    return rendered.replace("<<SLUG>>", SLUG_TMPL)


if __name__ == "__main__":
    import sys
    sys.stdout.write(render())
