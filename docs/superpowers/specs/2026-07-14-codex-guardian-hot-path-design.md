# Codex 对齐的 Guardian 自动审批热路径设计

## 背景

OpenSquilla 已具备 Codex 风格的独立 Guardian、只读调查工具、会话主干复用、增量 transcript 和失败关闭，但首次提权审批仍可能耗时四十余秒。日志显示实际越权命令只执行了约 11ms，主要延迟来自 Guardian 首次懒初始化、模型多轮调查和无效 JSON 后的重试。

本阶段不更换审批模型，也不增加绕过模型审查的本地低风险白名单。目标是完整复刻 Codex 除专用快速模型外的审批热路径，使相同模型下的请求更少、更稳定、更容易命中提示词缓存。

## 目标

1. 主 Agent 开始处理首轮请求时预热 Guardian 会话主干，审批发生时不再临时构造 Guardian Agent、工具表和固定系统提示词。
2. 固定 Guardian 策略作为稳定缓存前缀；后续审批继续复用主干并只发送新增 transcript。
3. 明显低风险操作允许 Guardian 直接返回最小结果 `{"outcome":"allow"}`，不为四字段解释和无必要调查增加生成时延。
4. Provider 请求携带 JSON Schema 结构化输出约束，要求至少返回 `outcome`，同时兼容需要完整风险解释的四字段结果。
5. 保持现有安全边界：Guardian 仍是独立审查者，仍可使用七个只读工具，现有阈值强制、超时、重试和失败关闭逻辑不变。

## 方案

### 启动预热

`GuardianReviewSessionManager.prewarm()` 幂等创建主干 Agent，但不调用模型。主 Agent 在一轮开始、进入正常模型处理前调用它。Guardian 自身通过 `metadata.agent_role == "guardian"` 跳过预热，避免递归创建。

预热失败只记录警告并保留现有审批时的失败关闭路径，不阻断普通对话。审批配置变化时，原有 session key 仍会重建 manager 和新主干。

### 直接低风险结果

Guardian 固定策略明确要求：低风险动作直接返回 `{"outcome":"allow"}`；其他情况返回完整的 `risk_level`、`user_authorization`、`outcome`、`rationale`。现有解析器继续将最小 allow 规范化为低风险、高授权缺省解释，后续阈值强制逻辑不变。

只读工具继续可用。模型只在风险依赖本地状态时调查；不会通过首轮禁用工具来人为改变判断能力。

### 结构化输出

`AgentConfig` 和 `ChatConfig` 增加可选 `output_json_schema`，由 Agent 完整透传。Guardian 使用与 Codex 相同的 schema：

- 根对象禁止额外字段；
- `outcome` 必填且只能为 `allow` 或 `deny`；
- 其余三个字段可选，但出现时必须符合现有枚举或字符串约束。

由于三个解释字段是可选的，Guardian 按 Codex 的实现将 provider strict 标志设为 `false`；“最终消息必须是严格 JSON”仍由输出契约明确要求。OpenAI-compatible Chat Completions 将它映射为 `response_format.type = "json_schema"`，OpenAI Responses 将它映射为 `text.format.type = "json_schema"`。未设置 schema 的普通 Agent 请求保持原样，其他 provider 仍依赖固定提示词和现有解析/重试，不降低失败关闭能力。

### 缓存稳定性

Guardian 配置把完整固定策略同时设置为 `system_prompt` 和唯一 `cache_breakpoints` 文本，沿用父 Agent 的 `cache_mode`。审批动作、transcript delta 和重试原因只进入用户消息，不污染固定策略前缀。

## 验收标准

- Guardian manager 可在没有模型调用的情况下预热一次，第一次审批复用该主干。
- Guardian 自身不会递归预热另一个 Guardian。
- 固定策略包含 Codex 的低风险最小直答契约。
- Guardian ChatConfig 始终携带 Codex schema，OpenRouter/OpenAI-compatible wire payload 正确生成 `response_format`，OpenAI Responses 正确生成 `text.format`。
- 普通请求不新增 `response_format`。
- 既有 Guardian 会话复用、并发 fork、七工具只读限制、风险阈值和失败关闭测试全部通过。
- 使用脚本 provider 的低风险审批只产生一次 provider 调用且无需工具；实际模型延迟由 gateway smoke test 复测。

## 非目标

- 不切换到专用快速审批模型。
- 不用静态命令规则直接放行提权。
- 不放宽沙箱、可写根目录或高风险审批策略。
- 不取消 Guardian 调查工具或失败关闭重试。
