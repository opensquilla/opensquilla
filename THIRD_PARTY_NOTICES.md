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
- Static frontend vendor assets and fonts distributed with the gateway Control
  UI and generated Web UI assets.
- The built-in tokenjuice tool-result projection backend and bundled
  reduction rules under `src/opensquilla/plugins/tokenjuice/`.
- The cron prompt-injection scanner was reviewed against Hermes Agent
  reference material; the MIT notice is reproduced below for conservative
  attribution.

## Static frontend vendor assets and fonts

OpenSquilla distributes a built Control UI and selected static assets in the
gateway package. These assets are used for markdown rendering, math rendering,
syntax highlighting, sanitization, and local typography. They are not
proprietary components.

| Component | Distributed files | License and attribution |
|---|---|---|
| KaTeX | `src/opensquilla/gateway/static/vendor/katex.min.js`, `src/opensquilla/gateway/static/vendor/katex.min.css`, generated `KaTeX_*` font files under `src/opensquilla/gateway/static/dist/assets/fonts/` | MIT. Copyright (c) 2013-2020 Khan Academy and other contributors. |
| PrismJS | `src/opensquilla/gateway/static/vendor/prism-core.min.js`, `prism-autoloader.min.js`, and `prism-langs/*.min.js` | MIT. Copyright (c) 2012 Lea Verou. |
| marked | `src/opensquilla/gateway/static/vendor/marked.min.js` | MIT. Copyright (c) 2011-2025, Christopher Jeffrey. |
| DOMPurify | `src/opensquilla/gateway/static/vendor/purify.min.js` | MPL-2.0 OR Apache-2.0. OpenSquilla distributes this asset under the Apache-2.0 option. Copyright belongs to Cure53 and other contributors. |
| IBM Plex Sans and IBM Plex Mono | `opensquilla-webui/src/assets/fonts/ibm-plex-*.woff2` and generated Web UI font assets | SIL Open Font License 1.1. Copyright 2017 IBM Corp. with Reserved Font Name "Plex". |
| Space Grotesk | `opensquilla-webui/src/assets/fonts/space-grotesk-*.woff2` and generated Web UI font assets | SIL Open Font License 1.1. Copyright 2020 The Space Grotesk Project Authors. |
| Inter | `src/opensquilla/gateway/static/fonts/Inter-Variable.woff2` | SIL Open Font License 1.1. Copyright (c) 2016 The Inter Project Authors. |
| JetBrains Mono | `src/opensquilla/gateway/static/fonts/JetBrainsMono-Variable.woff2` | SIL Open Font License 1.1. Copyright 2020 The JetBrains Mono Project Authors. |

Current static vendor files are audited as distributed assets. Some manually
vendored files intentionally record their own upstream version in-file; for
example, the static `marked.min.js` header identifies marked 15.0.7,
`purify.min.js` identifies DOMPurify 3.2.5, and `katex.min.css` identifies
KaTeX 0.16.21. The Web UI npm lockfile may contain newer build-time dependency
versions. Future updates should either regenerate these files from npm or
record the exact vendored source and version here.

The MIT license text is reproduced in this file for MIT-licensed bundled
components. The Apache License 2.0 text is reproduced in the repository
`LICENSE` file. The SIL Open Font License 1.1 text for the bundled fonts is
reproduced below.

```
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any Modified
Version, except to acknowledge the contribution(s) of the Copyright
Holder(s) and the Author(s) or with their explicit written permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to remain
under this license does not apply to any document created using the Font
Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

## npm and Python dependency packaging strategy

OpenSquilla uses npm lockfiles for the Web UI and Electron shell and `uv.lock`
for Python release environments. Lockfiles pin dependency resolution for
reproducible builds, but lockfiles are not a replacement for third-party license
notices when source, minified JavaScript, fonts, model files, or adapted code
are copied into OpenSquilla release artifacts.

Build-time npm dependencies are installed from the package registry during CI.
The Electron and gateway release artifacts distribute the compiled Control UI,
selected static assets, updater metadata, and packaged runtime outputs rather
than the full npm source tree. Any static npm-derived file copied into
`src/opensquilla/gateway/static/` must be listed in this notices file or in a
component-local notice file.

Python dependencies are resolved from `pyproject.toml` and `uv.lock` during
wheel, portable, and packaged-gateway builds. Python packages remain governed by
their upstream package metadata and licenses. If OpenSquilla vendors or adapts
Python package code, model files, rule files, binary assets, or generated
runtime artifacts into the repository, the component must be recorded here or
in a package-local provenance file.

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
- `code-task`
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
- `swe-bench`
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
