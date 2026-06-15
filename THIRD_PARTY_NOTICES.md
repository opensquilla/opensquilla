# Third Party Notices

This file records third-party attribution for assets bundled with OpenSquilla.
It covers:

- The bundled skill descriptors under `src/opensquilla/skills/bundled/`, which
  include OpenClaw-derived MIT descriptors and OpenSquilla-original descriptors.
- The bundled pptx skill references the python-pptx and PptxGenJS libraries;
  OpenSquilla does not vendor those libraries, but the skill instructs the
  agent runtime to invoke them and is documented here for transparency.
- The local SquillaRouter V4 Phase 3 model bundle under
  `src/opensquilla/squilla_router/models/v4.2_phase3_inference/`.
- The built-in tokenjuice tool-result projection backend and bundled
  reduction rules under `src/opensquilla/plugins/tokenjuice/`.
- The cron prompt-injection scanner was reviewed against Hermes Agent
  reference material; the MIT notice is reproduced below for conservative
  attribution.

## OpenClaw-derived bundled skill descriptors

- Component: SKILL.md frontmatter and instruction text for these bundled skills:
  - `sub-agent`
  - `cron`
  - `github`
  - `nano-pdf`
  - `skill-creator`
  - `summarize`
  - `tmux`
  - `weather`
- Upstream project: https://github.com/openclaw/openclaw
- License: MIT
- Copyright notice: Copyright (c) 2025 Peter Steinberger

Note: `sub-agent` was renamed from `coding-agent` on 2026-05-23; the
descriptor retains the same OpenClaw upstream lineage and MIT attribution.

The descriptor text instructs the agent runtime how to use built-in skill
surfaces and external tools; OpenSquilla does not redistribute third-party CLIs
through these descriptors. Per the MIT license, the upstream copyright and
permission notice are reproduced below in their entirety and apply to the
OpenClaw-derived bundled descriptor files.

```
MIT License

Copyright (c) 2025 Peter Steinberger

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## OpenSquilla-original bundled skills

These bundled skill descriptors are authored and maintained by OpenSquilla and
are released under OpenSquilla's repository license (Apache-2.0; see `LICENSE`):

- `cron`
- `AwesomeWebpageMetaSkill`
- `awesome-webpage-image-download`
- `awesome-webpage-research`
- `deep-research`
- `docx`
- `git-diff`
- `github`
- `history-explorer`
- `html-to-pdf`
- `http-fetch`
- `latex-compile`
- `memory`
- `meta-kid-project-planner`
- `meta-paper-write`
- `meta-short-drama`
- `meta-skill-creator`
- `multi-search-engine`
- `nano-pdf`
- `openrouter-video-generator`
- `paper-abstract-author`
- `paper-citation-planner`
- `paper-experiment-stub`
- `paper-outline-author`
- `paper-plot-stub`
- `paper-preference-planner`
- `paper-refbib-stub`
- `paper-revision-author`
- `paper-section-author`
- `paper-source-curator`
- `pdf-toolkit`
- `pptx`
- `skill-creator`
- `skill-creator-linter`
- `skill-creator-proposals`
- `skill-creator-smoke-test`
- `stack-trace-generic-probe`
- `stack-trace-go-probe`
- `stack-trace-js-probe`
- `stack-trace-python-probe`
- `stack-trace-rust-probe`
- `sub-agent`
- `srt-from-script`
- `subtitle-burner`
- `summarize`
- `text-file-read`
- `title-card-image`
- `tmux`
- `video-still-animator`
- `weather`
- `xlsx`
- `advanced-dubbing-studio`
- `music-and-singing-studio`
- `voice-clone-lab`
- `voice-conversion-studio`
- `voiceover-studio`

## tokenjuice adapted reduction rules

- Component: built-in tokenjuice tool-result projection backend and bundled
  reduction rules under `src/opensquilla/plugins/tokenjuice/`.
- Upstream project: https://github.com/vincentkoc/tokenjuice
- License: MIT
- Copyright notice: Copyright (c) 2026 Vincent Koc

OpenSquilla includes a Python adaptation of tokenjuice's rule-driven reducer
and bundles reduction rules derived from the upstream project. OpenSquilla does
not depend on the upstream tokenjuice npm package at runtime. Additional
provenance is recorded in
`src/opensquilla/plugins/tokenjuice/PROVENANCE.md`; the MIT license text is
also shipped with that package as `LICENSE.tokenjuice`.

```
MIT License

Copyright (c) 2026 Vincent Koc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Hermes Agent reference material

- Component: cron prompt-injection scanner reference material.
- Upstream project: https://github.com/NousResearch/hermes-agent
- License: MIT
- Copyright notice: Copyright (c) 2025 Nous Research

OpenSquilla does not redistribute Hermes Agent. This notice records conservative
attribution for reference material reviewed while hardening OpenSquilla's cron
prompt scanner.

```
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ClawHub-derived bundled skill descriptors

- Component: SKILL.md frontmatter and instruction text for these bundled skills:
  - `ai-video-script`
  - `audio-cog`
  - `deep-research`
  - `docx`
  - `html-coder`
  - `html-to-pdf`
  - `multi-search-engine`
  - `nano-banana-pro`
  - `nano-banana-pro-openrouter`
  - `pdf-toolkit`
  - `pptx`
  - `seedance-2-prompt`
  - `video-merger`
  - `web-search`
  - `xlsx`
- Upstream registry: https://clawhub.ai
- License: MIT-0 (Public-domain-equivalent; no attribution required, but
  each skill records its specific upstream slug in its own
  `THIRD_PARTY_NOTICES.md` for transparency)

These bundled skills record their ClawHub source slug in SKILL.md frontmatter
and, when present, the skill-local `THIRD_PARTY_NOTICES.md`. ClawHub's MIT-0
default license permits unlimited use, modification, and redistribution without
attribution.

```
MIT No Attribution

Copyright

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## ClawHub MIT bundled skill descriptors

- Component: SKILL.md frontmatter and instruction text for these bundled skills:
  - `filesystem`
- Upstream registry: https://clawhub.ai
- Upstream package: https://clawhub.ai/gtrusler/clawdbot-filesystem
- License: MIT
- Copyright notice: Copyright (c) 2026 Clawdbot Community

The `filesystem` bundled skill metadata, package manifest, and skill card
identify this upstream artifact as MIT licensed. OpenSquilla excludes
skill-local `LICENSE.md` files from wheels as non-runtime skill resources, so
the required MIT notice for this copied descriptor is reproduced here in the
top-level notices distributed with release artifacts.

```
MIT License

Copyright (c) 2026 Clawdbot Community

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## BAAI bge-small-zh-v1.5 / FlagEmbedding

- Component: BAAI/bge-small-zh-v1.5 embedding model and tokenizer assets.
- Upstream model: https://huggingface.co/BAAI/bge-small-zh-v1.5
- Upstream project: https://github.com/FlagOpen/FlagEmbedding
- License: MIT
- Copyright notice: Copyright (c) 2022 staoxiao

The bundled router contains an ONNX export and tokenizer files derived from
the BAAI bge-small-zh-v1.5 model. The upstream Hugging Face model card marks
the model as MIT licensed and states that the released models can be used for
commercial purposes free of charge.

MIT License

Copyright (c) 2022 staoxiao

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Router Artifact Safety Note

The SquillaRouter bundle contains `.pkl` and `.joblib` artifacts used by the
current V4 Phase 3 runtime. Treat these artifacts as executable-code-equivalent
inputs: load only assets shipped with a trusted OpenSquilla release or assets
whose checksums match `artifact_manifest.json`.
