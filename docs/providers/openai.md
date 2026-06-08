# OpenAI 提供商配置

OpenAI 是领先的大模型提供商，提供 GPT-4o、GPT-4o-mini、o1 等模型。

## 配置步骤

### 1. 获取 API Key

访问 [OpenAI Platform](https://platform.openai.com/) 注册并获取 API Key。

### 2. 环境变量配置

```bash
# Linux/macOS
export OPENAI_API_KEY="sk-..."

# Windows PowerShell
$env:OPENAI_API_KEY="sk-..."

# Windows 持久化
setx OPENAI_API_KEY "sk-..."
```

### 3. OpenSquilla 配置

```bash
opensquilla onboard --provider openai --api-key-env OPENAI_API_KEY
```

### 4. 模型选择

```bash
# GPT-4o (最新旗舰)
opensquilla configure provider --provider openai --model gpt-4o

# GPT-4o-mini (高性价比)
opensquilla configure provider --provider openai --model gpt-4o-mini

# o1 (推理强化)
opensquilla configure provider --provider openai --model o1-preview

# o1-mini (快速推理)
opensquilla configure provider --provider openai --model o1-mini
```

## 可用模型

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `gpt-4o` | GPT-4 Omni | 通用、多模态、旗舰 |
| `gpt-4o-mini` | GPT-4o Mini | 高性价比、快速 |
| `gpt-4-turbo` | GPT-4 Turbo | 复杂推理 |
| `gpt-3.5-turbo` | GPT-3.5 Turbo | 简单任务、低成本 |
| `o1-preview` | o1 预览版 | 复杂推理、数学、编程 |
| `o1-mini` | o1 迷你版 | 快速推理 |

## 价格参考

| 模型 | 输入 (美元/百万 Token) | 输出 (美元/百万 Token) |
|------|---------------------|---------------------|
| GPT-4o | $5.00 | $15.00 |
| GPT-4o-mini | $0.15 | $0.60 |
| GPT-4-turbo | $10.00 | $30.00 |
| GPT-3.5-turbo | $0.50 | $1.50 |
| o1-preview | $15.00 | $60.00 |
| o1-mini | $1.00 | $4.00 |

*价格仅供参考，以官方为准*

## 特色功能

### 多模态支持

GPT-4o 支持图像和音频输入：

```bash
opensquilla agent -m "描述这张图片：path/to/image.jpg"
```

### 函数调用

OpenAI 原生支持函数调用（Function Calling）：

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {"type": "string"}
          }
        }
      }
    }
  ]
}
```

### 结构化输出

强制模型输出符合 JSON Schema：

```json
{
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "calendar_event",
      "schema": {
        "type": "object",
        "properties": {
          "title": {"type": "string"},
          "date": {"type": "string"}
        }
      }
    }
  }
}
```

## 优势

- ✅ 最强的通用能力
- ✅ 多模态支持（图像、音频）
- ✅ 函数调用原生支持
- ✅ 结构化输出
- ✅ 128K 上下文 (GPT-4o)
- ✅ 推理能力强（o1 系列）

## 常见问题

### Q: 如何查看用量？

访问 [OpenAI Platform > Usage](https://platform.openai.com/usage) 查看详细用量。

### Q: 速率限制是多少？

不同模型不同套餐有不同限制，详见 [Rate Limits](https://platform.openai.com/docs/guides/rate-limits)。

### Q: 支持流式输出吗？

✅ 支持，OpenSquilla 默认启用 Stream 模式。

### Q: 如何设置 Base URL？

```bash
export OPENAI_BASE_URL="https://api.openai.com/v1"
# 或使用代理
export OPENAI_BASE_URL="https://your-proxy.com/v1"
```

### Q: 支持 Azure OpenAI 吗？

✅ 支持，需要配置 Azure 相关环境变量：

```bash
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_API_VERSION="2024-02-01"
```

## 相关资源

- [OpenAI 官网](https://openai.com/)
- [OpenAI Platform](https://platform.openai.com/)
- [OpenAI API 文档](https://platform.openai.com/docs/api-reference)
- [定价页面](https://openai.com/pricing)
- [OpenSquilla 配置文档](../configuration.md)
