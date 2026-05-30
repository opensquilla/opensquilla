---
name: meta-document-to-decision
description: "Use this meta-skill instead of answering directly when the user gives PDFs, DOCX files, spreadsheets, pasted contracts, quotes, school notices, medical paperwork, or business documents and needs a decision-ready analysis through multi-skill orchestration."
kind: meta
meta_priority: 67
always: false
final_text_mode: "step:decision_brief_audit"
triggers:
  - "document decision"
  - "看下这个文件"
  - "帮我判断这个文档"
  - "合同风险"
  - "报价单分析"
  - "文件里我该注意什么"
  - "读完告诉我怎么做"
  - "供应商续费"
  - "续费材料"
  - "报价单"
  - "自动续约"
  - "付款期限"
  - "要不要签"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: medium
    capabilities: [filesystem-read, filesystem-write]
    clawhub_top100_composition:
      - skill: "Word / DOCX"
        local_skill: docx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 28
        role: "Inspect Word contracts, notices, and decision documents."
      - skill: "Excel / XLSX"
        local_skill: xlsx
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 31
        role: "Inspect spreadsheet quotes, totals, dates, and formula outputs."
      - skill: "Pdf"
        local_skill: pdf-toolkit
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 36
        role: "Extract PDF text, tables, titles, and page references."
composition:
  steps:
    - id: intake
      kind: llm_chat
      with:
        system: "You classify document decision requests and preserve every path, URL, excerpt, and decision question."
        task: |
          Parse the request into a decision-analysis contract.

          Request:
          {{ inputs.user_message | xml_escape | truncate(4000) }}

          Return exactly:
          DOCUMENT_TYPES:
            - <pdf|docx|xlsx|pasted_text|unknown>
          SOURCES:
            - <path/url/excerpt label>
          DECISION_QUESTION: <question or ASSUMED: what should the user do next>
          RISK_DOMAIN: <contract|finance|school|medical|operations|other>
          NEEDS_CLARIFICATION: <yes|no>
          MISSING_FIELDS:
            - <source_material|decision_question|none>
          OUTPUT_LANGUAGE: <language>
          Set NEEDS_CLARIFICATION: no when SOURCES has at least one path, URL,
          or pasted excerpt and DECISION_QUESTION is explicit or can be safely
          assumed from the user's ask. In that case MISSING_FIELDS must be
          exactly "- none".
    - id: clarify
      kind: user_input
      depends_on: [intake]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.intake and '- none' not in outputs.intake"
      clarify:
        mode: form
        intro: "文档决策分析缺少材料或问题。请补齐后我会继续。"
        nl_extract: true
        fields:
          - name: source_material
            type: string
            required: true
            prompt: "文件路径、URL 或摘录 / Source material"
            max_chars: 3000
          - name: decision_question
            type: string
            prompt: "你要做的决定 / Decision question"
            max_chars: 300
        cancel_keywords: ["取消", "算了", "cancel", "stop"]
        timeout_hours: 24
    - id: pdf_extract
      kind: skill_exec
      skill: pdf-toolkit
      depends_on: [intake, clarify]
      when: "'pdf' in (outputs.intake | lower)"
      on_failure: pdf_extract_fallback
      with:
        task: "Extract text, tables, document title, and page references for this decision analysis: {{ outputs.intake | truncate(1200) }}"
    - id: docx_extract
      kind: skill_exec
      skill: docx
      depends_on: [intake, clarify]
      when: "'docx' in (outputs.intake | lower) or 'word' in (outputs.intake | lower)"
      on_failure: docx_extract_fallback
      with:
        task: "Inspect document text, headings, tracked-change hints, tables, and clauses for this decision analysis."
    - id: xlsx_extract
      kind: skill_exec
      skill: xlsx
      depends_on: [intake, clarify]
      when: "'xlsx' in (outputs.intake | lower) or 'spreadsheet' in (outputs.intake | lower)"
      on_failure: xlsx_extract_fallback
      with:
        task: "Inspect sheets, tables, totals, formula outputs, and anomalies for this decision analysis."
    - id: pasted_text_extract
      kind: llm_chat
      depends_on: [intake, clarify]
      when: "'pasted_text' in (outputs.intake | lower) or 'unknown' in (outputs.intake | lower)"
      with:
        system: "You turn pasted document excerpts into a source-labeled evidence packet without inventing missing clauses."
        task: |
          Build an evidence packet from the user's pasted materials only.
          Preserve source labels such as quote, contract excerpt, email,
          notice, spreadsheet excerpt, or unknown excerpt. Extract exact
          money amounts, dates, obligations, contradictions, and missing facts.

          Intake:
          {{ outputs.intake | truncate(1200) }}

          Request:
          {{ inputs.user_message | xml_escape | truncate(6000) }}
    - id: pdf_extract_fallback
      kind: llm_chat
      with:
        system: "You build a limited PDF evidence packet from only the user's pasted text and explicit file names."
        task: |
          Return a PDF evidence packet. Mark unavailable file extraction clearly.

          Request:
          {{ inputs.user_message | xml_escape | truncate(5000) }}
    - id: docx_extract_fallback
      kind: llm_chat
      with:
        system: "You build a limited DOCX evidence packet from only the user's pasted text and explicit file names."
        task: |
          Return a DOCX evidence packet. Mark unavailable file extraction clearly.

          Request:
          {{ inputs.user_message | xml_escape | truncate(5000) }}
    - id: xlsx_extract_fallback
      kind: llm_chat
      with:
        system: "You build a limited spreadsheet evidence packet from only the user's pasted text and explicit file names."
        task: |
          Return a spreadsheet evidence packet. Mark unavailable file extraction clearly.

          Request:
          {{ inputs.user_message | xml_escape | truncate(5000) }}
    - id: risk_review
      kind: llm_chat
      depends_on: [pdf_extract, docx_extract, xlsx_extract, pasted_text_extract]
      with:
        system: "You identify document risks and decision-relevant evidence without giving regulated professional advice."
        task: |
          Extract:
          - key facts with evidence source/page/sheet when available
          - money/date/obligation/risk clauses
          - inconsistencies and missing information
          - decisions the user can safely make
          - items requiring lawyer/doctor/accountant/professional review
          Compare dates against the current runtime date when available. Do
          not mark a payment deadline, cancellation window, or event as
          overdue unless the date is actually before the current date; when
          uncertain, call it "upcoming/待确认" instead of expired. Do not
          infer that a cancellation window has passed from a payment due date
          alone; require an explicit contract end, renewal effective date, or
          cancellation deadline.
          Do not derive cancellation deadlines by subtracting days from invoice or payment due dates.
          If the contract end date or renewal effective date is missing, mark the
          cancellation deadline unknown / 待确认 and avoid saying the notice window has passed.

          Intake:
          {{ outputs.intake | truncate(1200) }}
          PDF:
          {{ outputs.pdf_extract | truncate(3000) }}
          DOCX:
          {{ outputs.docx_extract | truncate(3000) }}
          XLSX:
          {{ outputs.xlsx_extract | truncate(3000) }}
          Pasted text:
          {{ outputs.pasted_text_extract | truncate(4000) }}
    - id: decision_brief
      kind: llm_chat
      depends_on: [risk_review]
      with:
        system: "You write decision briefs for ordinary users and managers."
        task: |
          Return a decision-ready brief:
          1. Bottom-line recommendation / 底线推荐
             Start with a one-paragraph boss-forwardable summary that states
             sign / negotiate first / reject, the decisive reason, money/date
             exposure, and the next owner/action.
          2. Evidence table. Use the literal section title "Evidence table /
             证据表" and cite each row's source as quote/contract/email/page/
             sheet/excerpt when available.
          3. Risks ranked high/medium/low
          4. Questions to ask the other party
          5. What to do next in 24 hours
          6. Professional-review caveats where needed. For contract,
             finance, medical, school, or regulated decisions, include an
             explicit "Professional-review caveat / 专业复核提醒" section
             naming the right reviewer, such as lawyer/律师, accountant/会计,
             doctor/医生, school administrator, or compliance owner. Do not
             bury this inside the risk table.
          Do not claim to create, save, export, download, or attach a file
          unless an explicit export step ran. Return the usable brief inline.
          Preserve date status accurately: if a deadline is after the current
          date, describe it as upcoming, not overdue.
          Do not say a cancellation window has already passed unless the
          evidence includes the contract end date, renewal effective date, or
          cancellation deadline.
          If the only known future date is a payment deadline, do not compute
          a cancellation deadline from that date. Say the cancellation window
          is "unknown / 待确认" and ask the supplier to confirm whether the
          30-day notice period is measured from contract end, renewal start,
          invoice due date, or another date.
          Do not derive cancellation deadlines by subtracting days from invoice or payment due dates.
          If the contract end date or renewal effective date is missing, keep the
          cancellation deadline unknown and avoid saying the notice window has passed.
          Do not speculate that the notice period may already be too short
          unless the evidence contains the date from which the notice period
          runs. Phrase unknown notice status as a negotiation question, not as
          a likely risk conclusion.
          Keep the brief boss-forwardable: no workflow commentary, no meta-skill
          names, no private reasoning, and no broad legal lecture. Do not invent
          exact reply deadlines such as "16:00" unless the user provided that
          time; use natural windows like today, tomorrow morning, or before the
          payment due date. Do not cite statutes or legal article numbers unless
          they appear in the provided materials. Prefer practical negotiation
          language over categorical legal conclusions.

          Risk review:
          {{ outputs.risk_review | truncate(7000) }}
    - id: decision_brief_audit
      kind: llm_chat
      depends_on: [decision_brief, risk_review]
      with:
        system: "You are the final quality gate for a document-to-decision brief. Return only the cleaned final answer the user should read. Do not explain the audit. Keep it boss-forwardable and source-faithful."
        task: |
          Clean the draft decision brief below.

          Draft brief:
          {{ outputs.get('decision_brief', '') | truncate(9000) }}

          Risk review:
          {{ outputs.get('risk_review', '') | truncate(5000) }}

          Original request:
          {{ inputs.user_message | xml_escape | truncate(5000) }}

          Required audit rules:
          - Remove statutes, legal article numbers, and law-name citations
            such as Civil Code, 民法典, article numbers, court standards, or
            specific legal doctrines unless they appear in the provided
            materials. Replace them with "ask counsel to review enforceability".
          - Do not invent today's date or the current calendar date. If the
            runtime date is not explicitly present in the source material, use
            relative wording such as today or before the payment due date.
          - If the source says sales email, do not call it oral or verbal.
            Treat it as a written sales email that conflicts with the contract
            excerpt, not as a spoken promise.
          - Do not say an email promise is legally invalid, almost invalid, or
            unenforceable as a categorical conclusion. Say it may be weaker
            than a signed contract amendment and should be confirmed in a
            contract addendum or signed written clarification.
          - Remove categorical Chinese legal phrases such as 效力弱于合同 or
            书面条款优先 unless the provided material says so. Prefer "销售邮件
            与合同摘录冲突，需要供应商用补充协议或签字书面澄清确认".
          - Preserve the user's requested structure: recommendation, evidence
            table, high/medium/low risks, supplier questions, next 24 hours,
            and professional-review caveat.
          - Use these exact section titles so the brief is easy to scan:
            "Bottom-line recommendation / 底线推荐",
            "Evidence table / 证据表",
            "Risks ranked high/medium/low / 高中低风险",
            "Questions to ask the supplier / 要问供应商的问题",
            "What to do next in 24 hours / 接下来 24 小时",
            and "Professional-review caveat / 专业复核提醒".
          - Preserve date status accurately: payment due 2026-06-03 is an
            upcoming payment deadline, not overdue. Do not infer any
            cancellation deadline from that payment due date.
          - Keep the answer concise and directly forwardable to a boss. Remove
            workflow commentary, meta-skill names, runtime details, and private
            reasoning.
---

# Document To Decision

Converts mixed business and life documents into evidence-backed decision briefs.
