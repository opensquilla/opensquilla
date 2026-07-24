# 术语表

本术语表用面向用户的语言解释 OpenSquilla 中的常见术语，并非运行时设计文档。

## 智能体（Agent）

一个命名的 OpenSquilla 身份，带有模型、工作区、名称、描述等默认配置。内置的 `main` 智能体始终可用。

详见：[`agents.md`](agents.md)

## 产物（Artifact）

由一次运行生成的文件或媒体输出，例如 HTML 页面、报告、图片、电子表格、PDF 或幻灯片。

详见：[`artifacts-and-media.md`](artifacts-and-media.md)

## 审批（Approval）

敏感工具动作继续前需要人类做出决定。审批行为取决于使用界面、权限配置和工具策略。

详见：[`approvals-and-permissions.md`](approvals-and-permissions.md)

## 渠道（Channel）

消息集成，例如 Telegram、Slack、飞书/Lark、Discord、钉钉、企业微信、Matrix、终端或类 WebSocket 客户端。

详见：[`channels.md`](channels.md)

## 压缩（Compaction）

在长时间会话中精简旧上下文，使智能体能够在模型的上下文预算内继续运行。

详见：[`features/compaction-and-cache.md`](features/compaction-and-cache.md)

## 诊断（Diagnostics）

运行时日志控制，用于理解路由、服务商行为、压缩、工具压缩、缓存行为和投递失败。

详见：[`diagnostics-and-replay.md`](diagnostics-and-replay.md)

## 网关（Gateway）

Web UI、渠道、会话、审批、诊断、用量和 RPC 客户端背后的本地服务器。

详见：[`gateway.md`](gateway.md)

## 记忆（Memory）

可持续的用户或项目上下文，可被搜索并在之后被召回，而不必将所有旧对话都塞进当前提示词。

详见：[`features/memory.md`](features/memory.md)

## 元技能（MetaSkill）

一种可复用、可审计的工作流协议，将多个技能、工具、LLM 调用、检查或输出步骤组合成一个可重复的能力。

详见：[`features/meta-skills.md`](features/meta-skills.md) 和
[`features/meta-skill-user-guide.md`](features/meta-skill-user-guide.md)

## 权限配置（Permission Profile）

一次运行所选择的工具访问姿态，例如 `restricted`、`on`、`bypass` 或 `full`。

详见：[`approvals-and-permissions.md`](approvals-and-permissions.md)

## 服务商（Provider）

为 OpenSquilla 配置的 LLM 后端，例如 TokenRhythm、OpenRouter、OpenAI、Anthropic、Gemini、DeepSeek、DashScope 或 Ollama。

详见：[`providers-and-models.md`](providers-and-models.md)

## 回放（Replay）

决策日志中某条已记录回合的只读视图。回放不会重新运行工具。

详见：[`diagnostics-and-replay.md`](diagnostics-and-replay.md)

## 定时任务（Scheduler）

`opensquilla cron` 功能，用于执行周期性或一次性的 OpenSquilla 运行。

详见：[`scheduling.md`](scheduling.md)

## 会话（Session）

一次可持续的对话或任务历史。会话可以被列出、恢复、导出、中止或删除。

详见：[`sessions.md`](sessions.md)

## 技能（Skill）

OpenSquilla 需要时加载的可复用任务级指导、脚本或工作流说明包。

详见：[`features/skills.md`](features/skills.md)

## SquillaRouter

OpenSquilla 的本地路由层，用于为每一轮选择合适的模型层级。

详见：[`features/squilla-router.md`](features/squilla-router.md)

## 工具压缩（Tool Compression）

一种节省上下文的功能：在把更小的摘要发给模型的同时，仍保持大工具结果可用。

详见：[`features/tool-compression.md`](features/tool-compression.md)

## 工作区（Workspace）

任务被允许或预期在其中运行的本地目录。工作区标记有助于约束文件和 shell 操作。

详见：[`tools-and-sandbox.md`](tools-and-sandbox.md)

---

[文档索引](README.md) · [产品指南](../README.product.md) · [改进本页](contributing-docs.md) · [报告文档问题](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
