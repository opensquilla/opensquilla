---
name: meta-safe-skill-installer
description: "Use this meta-skill instead of answering directly when the user wants to evaluate, install, update, compare, or trust a ClawHub/GitHub/local skill and the task needs multi-skill orchestration across source inspection, risk review, backup planning, and install guidance."
kind: meta
meta_priority: 70
always: false
final_text_mode: "step:safety_decision_audit"
triggers:
  - "install this skill safely"
  - "skill vetting"
  - "安全安装 skill"
  - "审计这个 skill"
  - "ClawHub skill 安全"
  - "这个 skill 能装吗"
  - "vet skill"
  - "能不能装"
  - "这个插件能不能装"
  - "只做审计"
  - "权限清单"
  - "读取 `~/.ssh`"
  - "curl -fsSL"
  - "install.sh | bash"
provenance:
  origin: opensquilla-original
  license: Apache-2.0
metadata:
  opensquilla:
    risk: medium
    capabilities: [network, filesystem-read, filesystem-write]
    clawhub_top100_composition:
      - skill: "Skill Vetter"
        local_skill: "internal vetting frame"
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 3
        role: "Security-first review before trusting community skills."
      - skill: "Find Skills Skill"
        local_skill: "source lookup via multi-search-engine"
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 42
        role: "Discover public source, registry metadata, and reputation signals."
      - skill: "Multi Search Engine"
        local_skill: multi-search-engine
        rank_source: "Top ClawHub Skills downloads top100, 2026-05-28"
        rank: 11
        role: "Search registry/source evidence without installing."
composition:
  steps:
    - id: intake
      kind: llm_chat
      with:
        system: "You parse skill installation and vetting requests conservatively."
        task: |
          Extract the skill vetting contract.

          Request:
          {{ inputs.user_message | xml_escape | truncate(2500) }}

          Return exactly:
          SOURCE_KIND: <clawhub|github|local_path|unknown>
          SOURCE_REF: <slug/url/path or unknown>
          USER_INTENT: <install|update|compare|audit_only>
          RISK_TOLERANCE: <low|medium|high|unknown>
          NEEDS_CLARIFICATION: <yes|no>
          MISSING_FIELDS:
            - <source_ref|intent|none>
          Set NEEDS_CLARIFICATION: no when the request already includes
          installer notes, permission lists, shell commands, URLs, code
          snippets, or concrete suspicious behavior. In that case use the
          pasted evidence even if the public source/repository is unknown,
          set SOURCE_REF to the best URL/slug/path if present otherwise
          unknown, and put "- none" under MISSING_FIELDS. Clarify only when
          there is neither a source reference nor enough pasted evidence to
          make an audit-only trust decision.
    - id: pasted_evidence
      kind: llm_chat
      depends_on: [intake]
      with:
        system: "You extract only visible installer evidence from the user's request."
        task: |
          Build a source-of-truth evidence ledger from the user's request.
          This ledger is authoritative when external lookup, source fetch, or
          sub-agent inspection is unavailable, skipped, or ambiguous.

          Request:
          {{ inputs.user_message | xml_escape | truncate(4000) }}

          Return exactly:
          USER_GOAL: <what the user wants to accomplish>
          INSTALL_STATE: <not_installed|already_installed|unknown>
          INSTALL_COMMANDS:
            - <verbatim command fragments visible in the request, or none>
          URLS_OR_SOURCES:
            - <visible URLs, domains, paths, slugs, or unknown>
          REQUESTED_CAPABILITIES:
            - <filesystem_read|filesystem_write|network|shell|postinstall|secret_access|persistence|unknown, with short evidence>
          SECRET_OR_IDENTITY_ACCESS:
            - <visible secret/account paths such as ~/.ssh, ~/.aws, ~/.config/gh, tokens, keys, or none>
          SUSPICIOUS_PATTERNS:
            - <curl_pipe_bash|remote_shell_installer|postinstall_execution|secret_directory_read|broad_file_write|unknown_source|persistence|none, with evidence>
          EVIDENCE_BOUNDARY: <pasted_evidence_only|pasted_plus_source_lookup|unknown>

          Rules:
          - Preserve concrete risky fragments such as curl-pipe-bash,
            install.sh | bash, ~/.ssh, "read and write files", "use the
            network", "run shell commands", and postinstall/auto-run wording.
          - Do not reinterpret the meta-skill's own sub-agent or workflow as
            the object being audited.
          - Do not say "none described" for a category when the request names
            it in different words.
    - id: clarify
      kind: user_input
      depends_on: [intake, pasted_evidence]
      when: "'NEEDS_CLARIFICATION: yes' in outputs.intake and 'curl' not in (inputs.user_message | lower) and '~/.ssh' not in (inputs.user_message | lower) and '权限清单' not in inputs.user_message and '执行 shell' not in inputs.user_message"
      clarify:
        mode: form
        intro: "安装或审计 skill 前需要明确来源。"
        nl_extract: true
        fields:
          - name: source_ref
            type: string
            required: true
            prompt: "ClawHub slug、GitHub URL 或本地路径 / Source"
            max_chars: 300
          - name: intent
            type: enum
            choices: [audit_only, install, update, compare]
            default: audit_only
            prompt: "目标 / Intent"
        cancel_keywords: ["取消", "算了", "cancel", "stop"]
        timeout_hours: 24
    - id: source_lookup
      kind: skill_exec
      skill: multi-search-engine
      depends_on: [intake, pasted_evidence, clarify]
      when: "'http' in outputs.intake or 'github' in (outputs.intake | lower) or 'clawhub' in (outputs.intake | lower)"
      on_failure: source_lookup_fallback
      with:
        query: "{{ outputs.intake | truncate(300) }} skill security permissions source repository"
        engines: [duckduckgo, brave, github]
        max_results: 10
    - id: source_lookup_fallback
      kind: llm_chat
      with:
        system: "You summarize that no external source lookup was performed or available."
        task: |
          Return a short source-evidence note. Do not claim the domain,
          repository, package, or author was verified. Use only the user's
          pasted installer notes and mark external reputation as unknown.
          Apply this evidence boundary in every step, not only the final answer:
          Search failure, missing lookup output, or absent public reputation is not proof of NXDOMAIN,
          dead domains, malware, abandonment, or malicious authorship.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}
    - id: source_inspection
      kind: llm_chat
      depends_on: [pasted_evidence, source_lookup]
      with:
        system: "You inspect the candidate skill or installer from visible evidence only."
        task: |
          Inspect the available source evidence for the skill. If the skill
          contents are not available locally, do not invent files. Produce a
          risk inventory based only on manifest, README, code snippets, URLs,
          and user-provided text.
          Treat the pasted evidence ledger as the primary source of truth for
          installer commands and permissions. If source lookup contradicts or
          omits it, preserve the pasted evidence and mark lookup as unverified.
          Source inspection must pass through only visible evidence and unknowns.
          Do not call a domain dead, unreachable, unresolvable, NXDOMAIN, or verified-bad
          unless the provided lookup evidence explicitly contains that result.
          Search failure, missing lookup output, or absent public reputation is not proof of NXDOMAIN
          or maliciousness.
          Do not expose tool parameter errors, fetch failures, connector wording, or internal audit mechanics.
          Do not claim zero public footprint, no GitHub record, or no security-community record
          unless the output cites the checked sources or says these checks were not verified.
          Do not audit the meta-skill's own "sub-agent" machinery. The audited
          object is the skill/helper/plugin/installer described by the user.

          Request:
          {{ inputs.user_message | xml_escape | truncate(3000) }}

          Pasted evidence ledger:
          {{ outputs.pasted_evidence | truncate(4000) }}

          Search/source evidence:
          {{ outputs.source_lookup | truncate(5000) }}
    - id: vetting_frame
      kind: llm_chat
      depends_on: [source_inspection]
      with:
        system: "You apply a security-first ClawHub skill-vetting frame."
        task: |
          Apply a conservative Skill Vetter style review. Score only from
          available evidence, never from trust-by-popularity.

          Check:
          - purpose/capability fit
          - requested filesystem, shell, network, secret, and persistence access
          - installer and postinstall behavior
          - unknown source or author blockers
          - whether audit-only is safer than install
          If the inspection contains curl-pipe-bash, shell execution,
          postinstall execution, secret-directory access such as ~/.ssh, or
          broad filesystem write access, produce a decision-ready risk review
          from that pasted evidence even when the public repository or author
          cannot be verified. Missing source reputation is an additional
          blocker, not a reason to ask the user another question.
          Vetting and backup steps must not add new reputation or DNS claims.
          Do not call a domain dead, unreachable, unresolvable, NXDOMAIN, or verified-bad
          unless the inspection text contains visible lookup evidence for that
          exact claim. Missing source evidence should be "external source not
          verified", not a stronger claim.
          Do not expose tool parameter errors, fetch failures, connector wording, or internal audit mechanics.
          Do not claim zero public footprint, no GitHub record, or no security-community record
          unless the output cites the checked sources or says these checks were not verified.

          Inspection:
          {{ outputs.source_inspection | truncate(6000) }}
    - id: backup_plan
      kind: llm_chat
      depends_on: [vetting_frame]
      with:
        system: "You design reversible install and rollback plans for skills."
        task: |
          Produce a backup and rollback plan. Include what to copy, what not
          to copy, how to avoid secrets, and how to restore. Do not execute it.
          Vetting and backup steps must not add new reputation or DNS claims.
          For not-yet-installed tools, keep this concise: pre-install baseline,
          what not to copy, and what to rotate if the user accidentally runs
          the installer. Do not expand into a full incident-response runbook
          unless the vetting text says the tool was already installed.

          Vetting:
          {{ outputs.vetting_frame | truncate(5000) }}
    - id: safety_decision
      kind: llm_chat
      depends_on: [pasted_evidence, source_inspection, vetting_frame, backup_plan]
      with:
        system: "You make conservative skill installation decisions."
        task: |
          Return:
          - VERDICT: install / install with sandbox / audit only / reject
          - one-line threat model: what could go wrong if this installer is malicious
          - risk table: file access, shell, network, secrets, persistence
          - suspicious patterns
          - immediate action plan: what to do now, what not to run, what to
            tell the sender/vendor, and what to do if it was already installed
          - required manual checks, including download-without-running,
            signature/hash/release verification, static review, and isolated
            sandbox observation
          - isolated audit recipe: disposable VM/container or throwaway user,
            dummy SSH keys only, no real home directory, process/file/network
            observation, and clear stop conditions
          - backup/rollback plan, including baseline inventory, uninstall
            checks, persistence checks, and credential/key rotation if secrets
            may have been exposed
          - what evidence would change the verdict, such as public source,
            signed immutable release, least-privilege permissions, no secret
            reads, no postinstall execution, and documented uninstall
          - safer alternatives that match the user's goal without broad shell,
            secret, or postinstall access
          - short message the user can send back to the friend/sender
          - exact install/update commands only if safe enough
          - unknowns that block trust
          For suspicious installers, use the phrase "download without executing"
          and make the order explicit: fetch to a file, inspect it, verify
          signature/hash/source, and do not run bash install.sh until static review passes.
          Download commands are for isolated audit only and must not be run on the real machine.
          Never show invalid container flags such as --network=host=NO. Use --network=none for offline container inspection, or a disposable VM when network observation is required.
          Keep the final answer concise enough to finish in one turn.
          Do not include a long incident-response runbook unless the user says it was already installed.
          For not-yet-installed tools, keep rollback to pre-install backup and what to rotate if accidentally run.
          Keep the answer directly usable and inline. Do not claim that
          external searches, domain checks, repository inspections, or source
          fetches succeeded unless the inspection text contains visible source
          evidence. If the only evidence is the user's pasted installer notes,
          say "external source not verified / 外部来源未验证" and base the
          verdict on the pasted risks. Never say the domain is unreachable,
          unresolvable, inaccessible, dead, or verified-bad unless visible
          source evidence explicitly proves that in the inspection text; prefer
          "external source not verified" for missing public evidence.
          Do not expose tool parameter errors, fetch failures, connector wording, or internal audit mechanics.
          Do not claim zero public footprint, no GitHub record, or no security-community record
          unless the output cites the checked sources or says these checks were not verified.
          Do not say the domain is unreachable based only on missing lookup evidence. Do not
          infer that a project is not well-known, unpopular, abandoned, or
          malicious from missing evidence alone. Do not promote unrelated
          products; safer alternatives should be generic local workflows such
          as a small local script, read-only git log summary, or manual template.
          For curl-pipe-bash plus SSH-directory access, default to reject
          install and allow only isolated audit.

          Pasted evidence ledger:
          {{ outputs.pasted_evidence | truncate(4000) }}
          Inspection:
          {{ outputs.source_inspection | truncate(7000) }}
          Vetting:
          {{ outputs.vetting_frame | truncate(5000) }}
          Backup:
          {{ outputs.backup_plan | truncate(2500) }}
    - id: safety_decision_audit
      kind: llm_chat
      depends_on: [pasted_evidence, safety_decision]
      with:
        system: "You audit and repair the final installer-safety answer against the evidence ledger."
        task: |
          Rewrite the final answer only as needed so it is faithful to the
          user's pasted installer evidence. Preserve the user's language where
          practical.

          Pasted evidence ledger:
          {{ outputs.pasted_evidence | truncate(4000) }}

          Draft answer:
          {{ outputs.safety_decision | truncate(7000) }}

          Hard requirements:
          - If the ledger contains curl-pipe-bash, install.sh | bash, remote
            shell installer, ~/.ssh/secret access, broad file read/write,
            network access, shell execution, postinstall execution, or unknown
            source, these must appear in the verdict, risk table, suspicious
            patterns, and manual checks.
          - If both remote shell installer and secret/account-directory access
            are present, the verdict must be reject install / audit only in an
            isolated environment. Do not recommend normal install or "no
            action".
          - Never say "none described", "not applicable", or "no installer" for
            a category that is present in the ledger.
          - Do not audit or mention the meta-skill's internal workflow,
            sub-agent, or source-inspection mechanics.
          - Keep source boundaries: say "external source not verified / 外部来源未验证"
            when no verified source evidence is present. Do not claim the
            domain is dead, unreachable, unpopular, malicious, or reputationless
            unless visible evidence proves it.
          - For a user who has not installed it yet, keep rollback concise:
            pre-install backup/baseline, do not execute on the real machine,
            and rotate credentials only if it was accidentally run or secrets
            may have been exposed.
          - Include practical safer alternatives for the user's actual goal,
            such as a local read-only daily-report script/template that does
            not read ~/.ssh, run postinstall hooks, or need broad shell access.
---

# Safe Skill Installer

Evaluates skill sources before install or update and returns a conservative
trust decision plus rollback plan.
