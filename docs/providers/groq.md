# Groq 提供商配置

Groq 提供超低延迟的 LLM 推理服务，支持 Llama、Mixtral 等开源模型。

## 配置步骤

### 1. 获取 API Key

访问 [GroqCloud](https://groq.com/) 注册并获取 API Key。

### 2. 环境变量配置

```bash
# Linux/macOS
export GROQ_API_KEY="gsk_..."

# Windows PowerShell
$env:GROQ_API_KEY="gsk_..."

# Windows 持久化
setx GROQ_API_KEY "gsk_..."
```

### 3. OpenSquilla 配置

```bash
opensquilla onboard --provider groq --api-key-env GROQ_API_KEY
```

### 4. 模型选择

```bash
# Llama 3.3 70B (最新旗舰)
opensquilla configure provider --provider groq --model llama-3.3-70b-versatile

# Llama 3.1 70B
opensquilla configure provider --provider groq --model llama-3.1-70b-versatile

# Mixtral 8x7b
opensquilla configure provider --provider groq --model mixtral-8x7b-32768

# Gemma 2 9B
opensquilla configure provider --provider groq --model gemma2-9b-it
```

## 可用模型

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `llama-3.3-70b-versatile` | Llama 3.3 70B | 通用、推理（推荐） |
| `llama-3.1-70b-versatile` | Llama 3.1 70B | 通用、推理 |
| `llama-3.1-8b-instant` | Llama 3.1 8B | 快速响应 |
| `mixtral-8x7b-32768` | Mixtral 8x7b | 多语言、代码 |
| `gemma2-9b-it` | Gemma 2 9B | 轻量任务 |
| `qwen-2.5-32b` | Qwen 2.5 32B | 中文优化 |

## 价格参考

| 模型 | 输入 (美元/百万 Token) | 输出 (美元/百万 Token) |
|------|---------------------|---------------------|
| Llama 3.3 70B | $0.59 | $0.79 |
| Llama 3.1 70B | $0.59 | $0.79 |
| Llama 3.1 8B | $0.05 | $0.08 |
| Mixtral 8x7b | $0.24 | $0.24 |
| Gemma 2 9B | $0.08 | $0.08 |

*价格仅供参考，以官方为准*

## 特色功能

### 超低延迟

Groq 使用自研 LPU™ 推理引擎：

- **首 Token 时间**：< 10ms
- **吞吐量**：> 300 tokens/s
- **延迟稳定性**：P99 延迟 < 100ms

### 函数调用

支持原生函数调用：

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_current_weather",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {"type": "string"},
            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
          }
        }
      }
    }
  ]
}
```

### 结构化输出

支持 JSON Schema 约束：

```json
{
  "response_format": {
    "type": "json_object",
    "schema": {
      "name": "weather_response",
      "schema": {
        "temperature": {"type": "number"},
        "unit": {"type": "string"}
      }
    }
  }
}
```

## 优势

- ✅ 超低延迟（< 10ms 首Token）
- ✅ 高吞吐量（> 300 tokens/s）
- ✅ 支持多种开源模型
- ✅ 函数调用支持
- ✅ 价格亲民
- ✅ 无速率限制（付费用户）

## 常见问题

### Q: Groq 为什么这么快？

Groq 使用自研 LPU™（Language Processing Unit）推理引擎，专为 Transformer 架构优化。

### Q: 如何查看用量？

访问 [GroqCloud Console](https://console.groq.com/) 查看使用情况。

### Q: 支持流式输出吗？

✅ 支持，OpenSquilla 默认启用 Stream 模式。

### Q: 有速率限制吗？

- 免费用户：60 requests/minute
- 付费用户：无限制

### Q: Llama 3.3 和 3.1 有什么区别？

Llama 3.3 在以下方面有所改进：
- 更好的推理能力
- 更强的代码生成
- 更低的延迟
- 更好的多语言支持

## 性能对比

| 提供商 | 模型 | 首Token | 价格/百万Token |
|--------|------|---------|---------------|
| Groq | Llama 3.3 70B | < 10ms | $0.59/$0.79 |
| Groq | Llama 3.1 8B | < 5ms | $0.05/$0.08 |
| Anthropic | Claude 3.5 Sonnet | ~1s | $3.00/$15.00 |
| OpenAI | GPT-4o | ~500ms | $5.00/$15.00 |

## 使用场景

### 实时对话

```bash
opensquilla agent -m "进行实时对话，需要快速响应"
```

### 批量处理

```bash
opensquilla agent -m "批量处理这些文档，关注速度"
```

### 函数调用

```bash
opensquilla agent -m "调用天气查询函数，获取北京天气"
```

## 相关资源

- [Groq 官网](https://groq.com/)
- [GroqCloud Console](https://console.groq.com/)
- [Groq API 文档](https://console.groq.com/docs)
- [定价页面](https://groq.com/pricing)
- [OpenSquilla 配置文档](../configuration.md)
