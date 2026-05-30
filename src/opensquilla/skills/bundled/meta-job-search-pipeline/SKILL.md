---
name: meta-job-search-pipeline
description: "Use this meta-skill instead of answering directly when a job seeker pastes a job posting and wants a complete application pack — a tailored resume aligned to the JD, a cover letter, recent company / market intel, optional interview prep, and an optional DOCX export. The skill never auto-applies; it produces text the user reviews before sending. Also handles status-digest mode (the user pastes their current application ledger and gets a ranked next-action list)."
kind: meta
meta_priority: 65
always: false
final_text_mode: "step:deliver_jobpack"
triggers:
  - "tailor my resume"
  - "改简历"
  - "找工作"
  - "投递包"
  - "job application pack"
  - "interview prep for"
  - "求职准备"
  - "申请追踪"
  - "career application"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: low
    capabilities: [network, filesystem-write]
    clawhub_top100_composition:
      - skill: "Multi Search Engine"
        local_skill: multi-search-engine
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 11
        role: "Gather current company and role context before tailoring the application pack."
      - skill: "Deep Researcher / deep research family"
        local_skill: deep-research
        rank_source: "ClawHub research-skill family, verified via current search results"
        role: "Add interview-process and company-context depth for interview prep."
      - skill: "Word / DOCX"
        local_skill: docx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 28
        role: "Export resume and cover-letter artifacts when requested."
      - skill: "Excel / XLSX"
        local_skill: xlsx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 21
        role: "Export or clean up the job-application tracker in status-digest mode."
      - skill: "PowerPoint / PPTX"
        local_skill: pptx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        role: "Create an interview-prep deck when the user explicitly asks for slides."
composition:
  steps:
    - id: preferences
      kind: llm_chat
      with:
        system: "You extract job-search-pipeline preferences. Return only the requested contract."
        task: |
          Extract the job-search brief from the user's request.

          User request:
          {{ inputs.user_message | xml_escape | truncate(2000) }}

          Return exactly:
          MODE_HINT: <TAILOR_NEW|INTERVIEW_PREP|COMPARE_ROLES|STATUS_DIGEST|UNCLEAR>
          JOB_POSTING_PRESENT: <yes|no>
          RESUME_PRESENT: <yes|no>
          TARGET_COMPANY: <name or UNKNOWN>
          TARGET_ROLE: <title or UNKNOWN>
          CANDIDATE_LEVEL: <ENTRY|MID|SENIOR|STAFF|UNKNOWN>
          LANGUAGE: <en|zh|mixed>
          EXPORT_DOCX_REQUESTED: <yes|no>
          NEEDS_CLARIFICATION: <yes|no>
          MISSING_FIELDS:
            - <job_posting|resume|target_company|none>
          CLARIFY_REASON: <one concise reason, or none>
          ASSUMPTIONS:
            - <assumption>
    - id: job_clarify
      kind: user_input
      depends_on: [preferences]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.preferences"
      clarify:
        mode: form
        intro: |
          求职准备还差关键信息，麻烦补齐 / Need a few details to build the application pack.
        nl_extract: true
        fields:
          - name: job_posting
            type: string
            required: true
            prompt: "目标岗位 JD 全文（粘贴）/ Job posting (paste)"
            max_chars: 4000
          - name: resume_text
            type: string
            required: true
            prompt: "现有简历正文（粘贴；可省略 PII）/ Current resume text"
            max_chars: 4000
          - name: target_company
            type: string
            prompt: "目标公司（如果 JD 没写）/ Target company (if not in JD)"
            max_chars: 80
          - name: candidate_level
            type: enum
            choices: [ENTRY, MID, SENIOR, STAFF]
            default: MID
            prompt: "本人 seniority / Level"
          - name: language
            type: enum
            choices: [en, zh, mixed]
            default: en
            prompt: "输出语言 / Output language"
          - name: export_docx
            type: enum
            choices: ["YES", "NO"]
            default: "NO"
            prompt: "是否要 DOCX 导出 / Export to DOCX"
        cancel_keywords: ["算了", "取消", "cancel", "stop", "abort"]
        timeout_hours: 24
    - id: mode
      kind: llm_classify
      depends_on: [preferences, job_clarify]
      output_choices:
        - TAILOR_NEW
        - INTERVIEW_PREP
        - COMPARE_ROLES
        - STATUS_DIGEST
      with:
        text: |
          Classify the job-search session intent.

          User request:
          {{ inputs.user_message | xml_escape | truncate(1200) }}

          Preferences:
          {{ outputs.get('preferences', '') | truncate(800) }}

          Clarification answers:
          {{ inputs.get('collected', {}).get('job_clarify', {}) | tojson }}

          Decision rules:
          - TAILOR_NEW: user pasted a job posting (or said tailor / 改简历 /
            申请这个 / write me a cover letter) and wants a customised
            resume + cover letter for this role. This is the default
            when a JD is present.
          - INTERVIEW_PREP: user has an upcoming interview at a specific
            company / role (mentions "interview", "面试", "下周面"); wants
            likely questions and a study plan.
          - COMPARE_ROLES: user is weighing multiple offers / postings
            and wants a comparison matrix.
          - STATUS_DIGEST: user pasted a list of in-flight applications
            and wants a ranked next-action summary.
    - id: recall_company
      kind: agent
      skill: memory
      depends_on: [mode, job_clarify]
      when: "outputs.mode in ['TAILOR_NEW', 'INTERVIEW_PREP', 'COMPARE_ROLES']"
      on_failure: recall_company_fallback
    - id: recall_company_fallback
      kind: llm_chat
      with:
        system: "You produce a no-memory fallback note for job-search preparation."
        task: |
          No durable company/application memory was read. Continue using only
          the pasted JD, resume, ledger, and interview context. Do not mention
          runtime errors to the user.
    - id: web_research
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [mode]
      when: "outputs.mode in ['TAILOR_NEW', 'INTERVIEW_PREP', 'COMPARE_ROLES']"
      on_failure: web_research_fallback
      with:
        query: "{{ inputs.get('collected', {}).get('job_clarify', {}).get('target_company', '') }} {{ outputs.get('preferences', '') | truncate(120) }} {{ inputs.user_message | truncate(160) }} recent news leadership product"
        engines: [brave, tavily, duckduckgo]
        max_results: 10
    - id: web_research_fallback
      kind: llm_chat
      with:
        system: "You produce a no-web fallback note for job-search preparation."
        task: |
          Web/company research was not available. Return a compact company
          evidence note that says external company facts are not verified, then
          extract only the role, JD requirements, and candidate evidence visible
          in the pasted request. Do not expose tool names, paths, stack traces,
          connector wording, or runtime failures.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3500) }}
    - id: enrich_company
      kind: llm_chat
      depends_on: [mode, web_research, recall_company, job_clarify]
      when: "outputs.mode in ['TAILOR_NEW', 'INTERVIEW_PREP', 'COMPARE_ROLES']"
      with:
        system: "You produce a firmographic-style company brief from web search results. Be conservative; mark UNKNOWN when sources disagree. Never invent leadership names or financials."
        task: |
          Produce a structured company brief grounded ONLY in the web research below.

          Target company:
          {{ inputs.get('collected', {}).get('job_clarify', {}).get('target_company', '') | default('UNKNOWN') }}

          Web research:
          {{ outputs.get('web_research', '') | truncate(3000) }}

          Output exactly:
          COMPANY_NAME: <as confirmed by sources>
          INDUSTRY: <or UNKNOWN>
          STAGE: <PUBLIC|UNICORN|LATE_STAGE|GROWTH|SEED|UNKNOWN>
          SIZE_BAND: <1-10|11-50|51-200|201-1000|1000+|UNKNOWN>
          KEY_LEADERS:
            - <Name, Title — only if sourced>
          RECENT_MOVES:
            - <one-line bullet of a verifiable recent move, source name>
          POTENTIAL_RED_FLAGS:
            - <none|or one-line concern grounded in sources>
    - id: deep_research
      kind: skill_exec
      skill: deep-research
      depends_on: [mode]
      when: "outputs.mode == 'INTERVIEW_PREP'"
      with:
        query: "{{ inputs.get('collected', {}).get('job_clarify', {}).get('target_company', '') }} {{ inputs.get('collected', {}).get('job_clarify', {}).get('job_posting', '') | truncate(160) }} interview process"
        depth: "standard"
        max_rounds: 2
    - id: source_fact_ledger
      kind: llm_chat
      depends_on: [mode, job_clarify]
      when: "outputs.mode == 'TAILOR_NEW'"
      with:
        system: "You extract a strict source-fact ledger for job application materials. You do not write resume prose. You only separate provided facts from tempting but unsupported inferences."
        task: |
          Build a strict fact ledger from the user's request and any
          clarification payload.

          User request:
          {{ inputs.user_message | xml_escape | truncate(3500) }}

          Clarification:
          {{ inputs.get('collected', {}).get('job_clarify', {}) | tojson | truncate(1200) }}

          Return exactly:
          OUTPUT_LANGUAGE: <zh|en|mixed, matching the user request>
          TARGET_ROLE: <role title or UNKNOWN>
          TARGET_COMPANY: <company or UNKNOWN>
          PROVIDED_JD_REQUIREMENTS:
            - <requirement explicitly visible in the source>
          PROVIDED_CANDIDATE_FACTS:
            - <fact explicitly visible in the source; preserve verbs such as participated / 参与>
          PROVIDED_METRICS:
            - <metric exactly as provided, or none>
          FORBIDDEN_INFERENCES:
            - <unsupported inference that must not appear as fact>
          MISSING_BUT_USEFUL:
            - <detail to leave as [待补充] / [confirm] or a gap>

          Forbidden inference guidance:
          - Do not infer ownership from participation or training work.
          - Do not infer 100% delivery, reduced support tickets, FAQ impact,
            formal user interviews, NPS, A/B tests, release-note ownership,
            specific software tools, AI accuracy evaluation, dialogue-log
            review, leadership, company facts, or additional metrics unless
            the source explicitly says so.
          - Treat overclaim words as unsafe unless sourced: independently
            owned, end-to-end owner, led, drove, core member, proficient,
            expert, guaranteed, 100%, reduced, improved satisfaction,
            knowledge base, FAQ, technical team, product/design team,
            dialogue records, accuracy evaluation, or fake/pretend user
            research.
    - id: tailor_resume
      kind: llm_chat
      depends_on: [mode, enrich_company, job_clarify, source_fact_ledger]
      when: "outputs.mode == 'TAILOR_NEW'"
      with:
        system: "You tailor a candidate's resume to a specific JD. Surface relevant experience, drop unrelated lines, mirror the JD's vocabulary only where the candidate has genuine coverage. Never fabricate, inflate, or infer experience the candidate did not provide."
        task: |
          Tailor the candidate's resume to the target role.

          Target JD:
          {{ inputs.get('collected', {}).get('job_clarify', {}).get('job_posting', '') | xml_escape | truncate(3000) }}
          If that field is empty, extract the JD summary from the user request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Candidate's current resume:
          {{ inputs.get('collected', {}).get('job_clarify', {}).get('resume_text', '') | xml_escape | truncate(3500) }}
          If that field is empty, extract the resume facts from the user request:
          {{ inputs.user_message | xml_escape | truncate(3500) }}

          Company brief (use to phrase impact statements appropriately):
          {{ outputs.get('enrich_company', '') | truncate(800) }}

          Strict source fact ledger:
          {{ outputs.get('source_fact_ledger', '') | truncate(2500) }}

          Past research / notes on this company (from durable memory):
          {{ outputs.get('recall_company', '') | truncate(600) }}

          Candidate seniority:
          {{ inputs.get('collected', {}).get('job_clarify', {}).get('candidate_level', 'MID') }}

          Hard rules:
          - Keep every fact in the candidate's resume verifiable; reorder
            and rephrase, do NOT invent.
          - Do not add unprovided tools, methods, outcomes, or metrics
            such as A/B testing, NPS, customer interviews, Jira,
            Confluence, HubSpot, ticket reduction, release-note ownership,
            FAQ impact, 100% delivery, AI accuracy evaluation, dialogue-log
            review, technical-team work, product/design collaboration,
            leadership, or company names unless they appear in the source.
          - Avoid overclaim wording unless sourced: 独立负责全流程, 主导,
            核心成员, 精通, 熟练, 确保100%, 降低咨询量, 提升满意度,
            形成知识库, 技术团队, 产品与设计团队, 对话记录, 准确率.
          - Do not upgrade responsibility. "Participated in / 参与" stays
            participated; do not rewrite it as owned, led, orchestrated,
            or drove unless the source explicitly says so.
          - If a detail would make the resume stronger but is missing,
            use a visible placeholder such as [待补充] / [confirm] or mark
            it as a gap. Never fill it from common sense.
          - Each bullet must lead with a verb and contain ONE measurable
            outcome where the resume already has a number.
          - Skills must come from the user's source text. Do not invent
            software names or research methods.
          - Cut sections that are clearly off-topic for this JD.
          - Match the user's language. If LANGUAGE is zh or the request is
            mainly Chinese, write Simplified Chinese. If clarification is
            empty, use LANGUAGE from preferences instead of defaulting to
            English:
            {{ outputs.get('preferences', '') | truncate(400) }}

          Output a markdown resume with sections: Summary | Experience |
          Skills | Education. Add a "## Why I Tailored It This Way"
          section at the end (max 5 bullets) calling out what you
          reordered or rephrased and why.
    - id: cover_letter
      kind: llm_chat
      depends_on: [tailor_resume, enrich_company, job_clarify, mode, source_fact_ledger]
      when: "outputs.mode == 'TAILOR_NEW'"
      with:
        system: "You write a cover letter — 3 paragraphs, one sourced company/JD fact when available, one concrete claim of fit, one ask. No filler. No fabricated company facts. No 'I am writing to express my interest'."
        task: |
          Write a cover letter for this application.

          Tailored resume highlights:
          {{ outputs.tailor_resume | truncate(2000) }}

          Company brief:
          {{ outputs.get('enrich_company', '') | truncate(800) }}

          Target JD highlights:
          {{ inputs.get('collected', {}).get('job_clarify', {}).get('job_posting', '') | xml_escape | truncate(1500) }}
          If empty, use only the JD summary visible in:
          {{ inputs.user_message | xml_escape | truncate(1500) }}

          Strict source fact ledger:
          {{ outputs.get('source_fact_ledger', '') | truncate(1800) }}

          Language contract:
          - Match the user's language. If LANGUAGE is zh or the request is
            mainly Chinese, write Simplified Chinese.
          - If no external company fact is verified, say the letter is based
            on the JD summary and do not invent company facts.
          - Keep "participated in an AI customer-service pilot" as
            participation unless the source says the candidate owned it.
          - Do not add unprovided outcomes such as reduced tickets,
            customer interviews, NPS, A/B tests, FAQ impact, 100%
            delivery, AI accuracy evaluation, dialogue-log review, or tool names.
          - Do not call missing user-research preparation a fake or pretend
            research story. Frame it as learning a real method and honestly
            stating the gap.
          {{ outputs.get('preferences', '') | truncate(400) }}

          Output a single fenced ```text``` block — exactly 3 paragraphs,
          opening with a concrete sourced fact about the company or, if none
          is verified, a concrete JD requirement. End with one specific ask
          (a 30-minute conversation about <topic>).
    - id: interview_qs
      kind: llm_chat
      depends_on: [mode, web_research, deep_research, enrich_company, job_clarify]
      when: "outputs.mode == 'INTERVIEW_PREP'"
      with:
        system: "You predict likely interview questions for a specific company/role. Ground predictions in the JD, the company brief, and any deep-research signals."
        task: |
          Predict likely interview questions.

          JD:
          {{ inputs.get('collected', {}).get('job_clarify', {}).get('job_posting', '') | xml_escape | truncate(2500) }}

          Candidate seniority:
          {{ inputs.get('collected', {}).get('job_clarify', {}).get('candidate_level', 'MID') }}

          Company brief:
          {{ outputs.get('enrich_company', '') | truncate(800) }}

          Deep research (interview process if available):
          {{ outputs.get('deep_research', '') | truncate(2500) }}

          Output groups:
          ## Behavioral (5 likely)
          ## Domain / Technical (5 likely)
          ## Company-specific (3 — based on the brief, e.g. "Why us
             specifically given their pivot to X")
          ## Reverse interview — what to ask THEM (3 — ground these in
             red-flags or recent_moves from the brief)
    - id: study_brief
      kind: llm_chat
      depends_on: [interview_qs, job_clarify]
      when: "outputs.mode == 'INTERVIEW_PREP'"
      with:
        system: "You produce a focused 48-hour study plan to prepare for a specific interview."
        task: |
          Build a 48-hour study plan grounded in the predicted questions.

          Predicted questions:
          {{ outputs.interview_qs | truncate(3000) }}

          Output:
          - Day -2: 4-5 study targets (topics, papers, specific concepts)
          - Day -1: 3 rehearsal exercises (mock answers to 3 hardest)
          - Day of: 3 reset rituals (sleep, snack, single review item)

          Each item must reference a specific question from the
          interview_qs output, not be generic.
    - id: interview_deck
      kind: skill_exec
      skill: pptx
      depends_on: [interview_qs, study_brief, enrich_company, job_clarify]
      when: "outputs.mode == 'INTERVIEW_PREP' and ('deck' in (inputs.user_message | lower) or 'slides' in (inputs.user_message | lower) or '幻灯' in inputs.user_message)"
      with:
        mode: create
        title: "Interview Prep — {{ inputs.get('collected', {}).get('job_clarify', {}).get('target_company', 'Untitled') }}"
        slides:
          - title: "Why you, why them"
            body: "{{ outputs.get('enrich_company', '') | truncate(600) }}"
          - title: "Likely behavioral questions"
            body: "{{ outputs.get('interview_qs', '') | truncate(800) }}"
          - title: "Likely technical questions"
            body: "{{ outputs.get('interview_qs', '') | truncate(800) }}"
          - title: "48-hour study plan"
            body: "{{ outputs.get('study_brief', '') | truncate(800) }}"
          - title: "Reverse-interview questions to ask THEM"
            body: "{{ outputs.get('interview_qs', '') | truncate(400) }}"
        output_path: "/tmp/interview_prep_{{ inputs.get('collected', {}).get('job_clarify', {}).get('target_company', 'untitled') | slugify }}.pptx"
    - id: compare_matrix
      kind: llm_chat
      depends_on: [mode, enrich_company, job_clarify]
      when: "outputs.mode == 'COMPARE_ROLES'"
      with:
        system: "You produce a role-comparison matrix when the user is weighing multiple postings. Be ruthless about distinguishing the offers."
        task: |
          Compare the multiple roles in the user's message into a matrix.

          User request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Clarification:
          {{ inputs.get('collected', {}).get('job_clarify', {}) | tojson | truncate(800) }}

          Output a markdown table: role | company | comp_band | growth_lever |
          risk | culture_signal | fit_score (1-10). Add a closing
          paragraph "If I had to pick today" with one recommendation
          grounded in the rows above.
    - id: ledger_summary
      kind: llm_chat
      depends_on: [mode]
      when: "outputs.mode == 'STATUS_DIGEST'"
      with:
        system: "You read a user's pasted application ledger and produce a ranked next-action list. Sort by recency-since-last-touch + signal strength. Flag stalled apps that need a polite nudge."
        task: |
          Parse the user's pasted application ledger and produce a
          ranked next-action list.

          Source text:
          {{ inputs.user_message | xml_escape | truncate(3500) }}

          For each application row found, extract:
          - company / role
          - last_action + last_action_date (or "TBD")
          - days_since_last_touch
          - next_action (one of: NUDGE | WAIT | WITHDRAW | PREPARE_INTERVIEW | NEGOTIATE | NONE)

          Output: a markdown table sorted by urgency. Below the table,
          list the top 3 nudges with a one-line draft message each.
    - id: tracker_xlsx
      kind: skill_exec
      skill: xlsx
      depends_on: [ledger_summary]
      when: "outputs.mode == 'STATUS_DIGEST'"
      with:
        mode: create
        sheets:
          - name: "Open Applications"
            rows:
              - ["company", "role", "last_action_date", "days_since_last_touch", "next_action", "draft_nudge"]
            from_markdown: "{{ outputs.ledger_summary }}"
        output_path: "/tmp/application_tracker.xlsx"
    - id: deliver_jobpack
      kind: llm_chat
      depends_on:
        - mode
        - preferences
        - job_clarify
        - tailor_resume
        - cover_letter
        - interview_qs
        - study_brief
        - compare_matrix
        - ledger_summary
        - enrich_company
        - source_fact_ledger
        - recall_company
        - interview_deck
        - tracker_xlsx
      with:
        system: "You assemble the final job-search deliverable the user will read. Return the complete deliverable inline in chat. Do not create, save, export, attach, or point primarily to an artifact unless the user explicitly asked for a file export. Never mention workflow, meta-skill, tool names, connector failures, workspace paths, or runtime details. The final answer must be source-faithful: if any intermediate draft conflicts with the source fact ledger, ignore the draft and regenerate conservatively from the ledger."
        task: |
          Assemble the final deliverable per mode.

          Mode label: {{ outputs.mode }}

          For TAILOR_NEW, do not use the raw tailor_resume or cover_letter
          draft text as source material because drafts may contain optimistic
          wording. Regenerate the final user-facing resume and letter from the
          Strict source fact ledger below.

          Available non-TAILOR_NEW step outputs (some may be empty if skipped):
          - interview_qs:
            {{ outputs.get('interview_qs', '') | truncate(3000) }}
          - study_brief:
            {{ outputs.get('study_brief', '') | truncate(1500) }}
          - compare_matrix:
            {{ outputs.get('compare_matrix', '') | truncate(2500) }}
          - ledger_summary:
            {{ outputs.get('ledger_summary', '') | truncate(2500) }}

          Company brief (if generated):
          {{ outputs.get('enrich_company', '') | truncate(800) }}

          Strict source fact ledger:
          {{ outputs.get('source_fact_ledger', '') | truncate(2500) }}

          Mode-specific structure:
          - TAILOR_NEW → "# 📄 Application Pack — <Company / Role>" header,
            then "## Tailored Resume" + "## Cover Letter" +
            "## JD Requirement / My Evidence / Gap Table" +
            "## Company Brief" + "## 48-Hour Interview Prep" +
            "## Suggested Next Steps".
          - INTERVIEW_PREP → "# 🎯 Interview Prep — <Company>" header, then
            "## Predicted Questions" + "## 48-Hour Study Plan" +
            "## Company Brief".
          - COMPARE_ROLES → "# ⚖️ Role Comparison" header, then
            "## Matrix" + "## My Take".
          - STATUS_DIGEST → "# 📋 Application Status Digest" header, then
            "## Ranked Next Actions" + "## Draft Nudges".

          Output language:
          - Match the user's language. If LANGUAGE is zh or the request is
            mainly Chinese, write Simplified Chinese, including headings.
          - If clarification did not run, use LANGUAGE from preferences.
          - Do not default Chinese user requests to English.
          {{ outputs.get('preferences', '') | truncate(400) }}

          For TAILOR_NEW, if tailored resume or cover letter outputs are
          empty or contain unsupported claims, write the final answer directly
          from the Strict source fact ledger and pasted request. Do not copy
          intermediate resume or cover-letter drafts verbatim; treat them only
          as rough drafts after source audit. Preserve truth: only use
          candidate facts present in the request, mark missing facts as gaps,
          and include a "Do not invent / 不编造" note. The JD/evidence/gap
          table must have rows for data analysis, user research or feedback,
          cross-functional launch coordination, release/user docs, sales or
          support alignment, and AI-tool exposure when those requirements are
          visible in the request. The 48-hour interview prep section should be
          useful even when no external company research was verified.
          For Chinese TAILOR_NEW outputs, use this conservative structure:
          "## 一、简历改写要点", "## 二、可直接粘贴的中文简历段落",
          "## 三、求职信", "## 四、JD 要求-我的证据-缺口表",
          "## 五、面试前 48 小时准备", "## 六、事实边界 / 不编造说明",
          and "## 七、下一步".
          In the resume paragraph, use conservative wording such as
          "负责过 3 个企业客户的上线培训", "用 SQL 做过留存报表",
          "把新手引导完成率从 52% 提升到 68%", "写过 20 多篇帮助文档",
          and "参与 AI 客服试点，但不是负责人" when those facts are present.
          Do not turn these into broader claims.
          Across all TAILOR_NEW sections, do not add unprovided tools,
          methods, outcomes, company facts, or software names. Do not upgrade
          participation to ownership. Use placeholders like [待补充] and
          explicit "缺口 / gap" labels for missing but useful details.
          Avoid overclaim wording unless sourced: 独立负责全流程, 主导,
          核心成员, 精通, 熟练, 确保100%, 降低咨询量, 提升满意度,
          形成知识库, 技术团队, 产品与设计团队, 对话记录, 准确率,
          independently owned, end-to-end owner, led, drove, core member,
          expert, guaranteed, knowledge base, FAQ, dialogue records, and
          accuracy evaluation.
          Before returning, audit every concrete claim against the Strict
          source fact ledger. If a claim is not in PROVIDED_CANDIDATE_FACTS,
          PROVIDED_JD_REQUIREMENTS, or PROVIDED_METRICS, remove it or mark it
          as [待补充]. Do not present FORBIDDEN_INFERENCES as facts. For Chinese
          TAILOR_NEW outputs, include a short section named
          "## 事实边界 / 不编造说明" stating that only user-provided facts were
          used and missing details are marked as gaps or placeholders.
          Keep the full output concise enough to complete in one turn. Do not
          include self-referential truncation notes such as "output truncated"
          or "系统生成". The 48-hour prep must include Day -2 and Day -1 with
          complete bullets.

          If the user wants to keep this somewhere (Notion / Google Doc
          / personal knowledge base), they can copy the markdown
          directly from this output — this is read-only and
          does not push to any external surface.

          End with a single line:
          PACK_MODE: {{ outputs.mode }}
    - id: store_pack
      kind: agent
      skill: memory
      depends_on: [deliver_jobpack, mode, job_clarify]
    - id: export_docx
      kind: skill_exec
      skill: docx
      depends_on: [deliver_jobpack, job_clarify]
      when: "(inputs.get('collected', {}).get('job_clarify', {}).get('export_docx', 'NO') == 'YES') or ('EXPORT_DOCX_REQUESTED: yes' in outputs.get('preferences', ''))"
      with:
        markdown: "{{ outputs.deliver_jobpack }}"
        output_path: "/tmp/jobpack_{{ inputs.get('collected', {}).get('job_clarify', {}).get('target_company', 'untitled') | slugify }}.docx"
---

# meta-job-search-pipeline

Self-improver persona meta-skill. Handles 4 modes via an `llm_classify`
router — `TAILOR_NEW` (the default, pastes-JD-gets-application-pack
flow), `INTERVIEW_PREP`, `COMPARE_ROLES`, and `STATUS_DIGEST`. Each
mode unlocks only its relevant steps via `when:` conditions on the
classifier output, so a single composition handles all four without
forking the DAG into separate skills.

## Composition philosophy — multi-skill bundled orchestration

This meta-skill uses **only OpenSquilla-bundled atomic skills** plus the
five built-in step kinds — no external dependencies. The point of a
meta-skill is to *orchestrate* multiple skills, so this DAG calls into
**7 distinct bundled atomic skills**, each at the right point in the
pipeline:

| Skill | Step(s) | Role in the DAG |
|---|---|---|
| `multi-search-engine` | `web_research` | Web research per target company |
| `deep-research` | `deep_research` | Extra-context round for `INTERVIEW_PREP` only |
| `memory` | `recall_company`, `store_pack` | Cross-session memory of past company research and prior application packs — recalled before web research, stored after deliverable |
| `pptx` | `interview_deck` | Generate an interview-prep slide deck when `INTERVIEW_PREP` and the user mentions "deck" / "slides" / "幻灯" |
| `xlsx` | `tracker_xlsx` | Export the application ledger as a spreadsheet when `STATUS_DIGEST` |
| `docx` | `export_docx` | Optional final-deliverable export when the user picks `EXPORT_DOCX: YES` |

Step kinds used: `llm_chat`, `llm_classify`, `user_input`, `skill_exec`,
`agent`.

## What got dropped from the original 17-step design

The original draft had two ClawHub-shaped `skill_exec` steps that
turned out to be unnecessary:

- A `skill_exec: lead-enrichment` step that produced a structured
  company brief. The current `enrich_company` step (an `llm_chat`
  reading `outputs.web_research`) covers exactly the same contract
  with no external dependency. The original was the substitute path;
  it's now the primary path.
- A `skill_exec: notion-api-skill` step that POSTed the application
  pack to Notion. The deliverable is the markdown emitted by
  `deliver_jobpack`; the user copies it wherever they want.
  Convenience does not justify the dependency.

## Honest limitations

- **No application-ledger persistence.** `STATUS_DIGEST` mode is
  paste-driven: the user pastes their current ledger every turn. Once
  the proposed `state:` primitive ships, the ledger can persist across
  turns automatically.
- **No auto-apply.** The skill produces text for the user to send;
  there is no LinkedIn / job-board posting integration. This is a
  deliberate read-only design.
- **`COMPARE_ROLES` is text-based.** Without a `foreach` primitive,
  the matrix is one llm_chat call with multiple roles in the same
  prompt; per-role isolation would need `foreach`.
- **Interview prep depth.** `INTERVIEW_PREP` mode runs one
  `deep-research` round; a multi-round interview-loop would benefit
  from cross-turn state.
