# Codex 对齐的 Guardian 自动审批热路径实施计划

> 目标：在不使用快速模型的前提下，通过预热、稳定缓存前缀、最小低风险直答和严格结构化输出缩短自动提权审批延迟。

## 1. 固定行为测试

修改：

- `tests/test_engine/test_guardian_prompt.py`
- `tests/test_engine/test_guardian_session.py`

新增失败测试，验证策略包含最小 allow 契约、Guardian schema 与缓存断点配置、`prewarm()` 幂等且首审复用已创建主干。

## 2. Provider 结构化输出测试

修改：

- `tests/test_provider_openai_compat_payloads.py`
- `tests/test_provider_openai_responses.py`

新增失败测试，验证 OpenRouter/OpenAI-compatible 请求在配置 schema 时发送 `response_format`，OpenAI Responses 发送 `text.format`，普通请求不发送这些字段。

## 3. Agent 透传与递归保护测试

修改：

- `tests/test_engine/test_guardian_session.py`
- 必要时补充 Agent 配置相关测试

验证 `AgentConfig.output_json_schema` 进入每次 provider `ChatConfig`，关闭 thinking 的 fallback 不丢失 schema，主 Agent 首轮预热而 Guardian Agent 跳过。

## 4. 最小实现

修改：

- `src/opensquilla/engine/guardian_prompt.py`
- `src/opensquilla/engine/guardian_session.py`
- `src/opensquilla/engine/types.py`
- `src/opensquilla/engine/agent.py`
- `src/opensquilla/provider/types.py`
- `src/opensquilla/provider/openai.py`
- `src/opensquilla/provider/openai_responses.py`

实现 schema 常量、配置透传、OpenAI-compatible payload 映射、Guardian 固定缓存断点、幂等预热和主 Agent 启动调用。

## 5. 验证

依次运行：

1. Guardian prompt/session/review 定向测试；
2. OpenAI-compatible payload 定向测试；
3. Agent 交互审批与 prompt cache 回归测试；
4. 相关 provider 和 sandbox 自动审批测试；
5. lint/type check（以仓库现有命令为准）；
6. gateway 实际低风险提权 smoke test，比较 provider 调用轮数和 wall-clock 延迟。
