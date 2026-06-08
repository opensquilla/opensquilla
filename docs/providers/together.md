# Together AI 提供商配置

Together AI 提供多种开源和专有模型，支持高性能推理和微调服务。

## 配置步骤

### 1. 获取 API Key

访问 [Together AI](https://together.ai/) 注册并获取 API Key。

### 2. 环境变量配置

```bash
# Linux/macOS
export TOGETHER_API_KEY="..."

# Windows PowerShell
$env:TOGETHER_API_KEY="..."

# Windows 持久化
setx TOGETHER_API_KEY "..."
```

### 3. OpenSquilla 配置

```bash
opensquilla onboard --provider together --api-key-env TOGETHER_API_KEY
```

### 4. 模型选择

```bash
# Mixtral 8x7b
opensquilla configure provider --provider together --model mistralai/Mixtral-8x7B-Instruct-v0.1

# Llama 3.1 70B
opensquilla configure provider --provider together --model meta-llama/Llama-3.1-70B-Instruct-Turbo

# Qwen 2.5 72B
opensquilla configure provider --provider together --model Qwen/Qwen2.5-72B-Instruct-Turbo

# Together 专有模型
opensquilla configure provider --provider together --model together-ai/Llama-3-8B-Instruct-Heuristics
```

## 可用模型

### Llama 系列

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `meta-llama/Llama-3.3-70B-Instruct-Turbo` | Llama 3.3 70B Turbo | 通用、快速 |
| `meta-llama/Llama-3.1-405B-Instruct-Turbo` | Llama 3.1 405B | 最强推理 |
| `meta-llama/Llama-3.1-70B-Instruct-Turbo` | Llama 3.1 70B Turbo | 平衡性能 |
| `meta-llama/Llama-3.1-8B-Instruct-Turbo` | Llama 3.1 8B Turbo | 轻量快速 |

### Mixtral 系列

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `mistralai/Mixtral-8x7B-Instruct-v0.1` | Mixtral 8x7B | 多语言、代码 |
| `mistralai/Mistral-7B-Instruct-v0.2` | Mistral 7B | 轻量任务 |

### Qwen 系列

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `Qwen/Qwen2.5-72B-Instruct-Turbo` | Qwen 2.5 72B | 中文优化 |
| `Qwen/Qwen2-72B-Instruct` | Qwen 2 72B | 中文通用 |

### Together 专有模型

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `together-ai/Llama-3-8B-Instruct-Heuristics` | 启发式优化 | 复杂推理 |
| `together-ai/RedPajama-INCITE-7B-Chat` | RedPajama | 开源替代 |

## 价格参考

| 模型 | 输入 (美元/百万 Token) | 输出 (美元/百万 Token) |
|------|---------------------|---------------------|
| Llama 3.3 70B Turbo | $0.60 | $0.60 |
| Llama 3.1 405B Turbo | $3.00 | $3.00 |
| Llama 3.1 70B Turbo | $0.60 | $0.60 |
| Mixtral 8x7B | $0.25 | $0.25 |
| Qwen 2.5 72B | $0.60 | $0.60 |

*价格仅供参考，以官方为准*

## 特色功能

### Turbo 模型

Together AI 提供 Turbo 变体，优化速度和成本：

- 更低的延迟
- 更高的吞吐量
- 更低的价格

### 模型微调

支持自定义模型微调：

```bash
# 微调自定义模型
together fine-tune create \
  --model "meta-llama/Llama-3-8b" \
  --training-data "train.jsonl" \
  --output-model "my-custom-model"
```

### 函数调用

支持原生函数调用：

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get current weather",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {"type": "string"}
          },
          "required": ["location"]
        }
      }
    }
  ]
}
```

### 批量推理

支持批量 API 调用，降低延迟：

```bash
# 批量请求
together batch inference \
  --model "meta-llama/Llama-3.1-8B-Instruct-Turbo" \
  --input "batch.jsonl"
```

## 优势

- ✅ 支持多种开源模型
- ✅ Turbo 变体优化速度和成本
- ✅ 模型微调服务
- ✅ 批量推理支持
- ✅ 高性能推理
- ✅ 价格透明

## 常见问题

### Q: 如何查看用量？

访问 [Together AI Console](https://api.together.xyz/settings/billing) 查看使用情况。

### Q: 支持流式输出吗？

✅ 支持，OpenSquilla 默认启用 Stream 模式。

### Q: 有速率限制吗？

根据套餐不同，速率限制不同。详见 [Rate Limits](https://docs.together.ai/docs/rate-limits)。

### Q: Turbo 模型有什么区别？

Turbo 模型经过优化：
- 延迟降低 50%+
- 吞吐量提升 2x
- 价格不变

### Q: 如何选择模型？

| 场景 | 推荐模型 |
|------|----------|
| 通用任务 | Llama 3.3 70B Turbo |
| 复杂推理 | Llama 3.1 405B Turbo |
| 中文任务 | Qwen 2.5 72B Turbo |
| 轻量快速 | Llama 3.1 8B Turbo |
| 成本敏感 | Mixtral 8x7B |

## 使用场景

### 实时对话

```bash
opensquilla agent -m "进行实时对话，使用 Turbo 模型"
```

### 复杂推理

```bash
opensquilla agent -m "分析这个复杂问题，使用 405B 模型"
```

### 中文任务

```bash
opensquilla agent -m "用中文回答这个问题，使用 Qwen 模型"
```

## 相关资源

- [Together AI 官网](https://together.ai/)
- [Together AI Console](https://api.together.xyz/)
- [Together AI 文档](https://docs.together.ai/)
- [定价页面](https://together.ai/pricing)
- [OpenSquilla 配置文档](../configuration.md)
