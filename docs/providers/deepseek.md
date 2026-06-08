# DeepSeek 提供商配置

DeepSeek 是国内领先的大模型提供商，支持 DeepSeek-V3 和 DeepSeek-Coder 等模型。

## 配置步骤

### 1. 获取 API Key

访问 [DeepSeek 开放平台](https://platform.deepseek.com/) 注册并获取 API Key。

### 2. 环境变量配置

```bash
# Linux/macOS
export DEEPSEEK_API_KEY="sk-..."

# Windows PowerShell
$env:DEEPSEEK_API_KEY="sk-..."

# Windows 持久化
setx DEEPSEEK_API_KEY "sk-..."
```

### 3. OpenSquilla 配置

```bash
opensquilla onboard --provider deepseek --api-key-env DEEPSEEK_API_KEY
```

### 4. 模型选择

```bash
# 使用 DeepSeek-V3
opensquilla configure provider --provider deepseek --model deepseek-chat

# 使用 DeepSeek-Coder
opensquilla configure provider --provider deepseek --model deepseek-coder
```

## 可用模型

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `deepseek-chat` | DeepSeek-V3 | 通用对话、推理 |
| `deepseek-coder` | 代码专用模型 | 代码生成、调试 |

## 价格参考

| 模型 | 输入 (元/百万 Token) | 输出 (元/百万 Token) |
|------|---------------------|---------------------|
| DeepSeek-V3 | 1.0 | 2.0 |
| DeepSeek-Coder | 1.0 | 2.0 |

*价格仅供参考，以官方为准*

## 优势

- ✅ 国内访问稳定
- ✅ 价格亲民
- ✅ 支持函数调用
- ✅ 128K 上下文

## 常见问题

### Q: 如何检查余额？

访问 [DeepSeek 控制台](https://platform.deepseek.com/) 查看余额和使用情况。

### Q: 速率限制是多少？

- 免费用户：30 requests/minute
- 付费用户：200 requests/minute

### Q: 支持 Stream 模式吗？

✅ 支持，OpenSquilla 默认启用 Stream 模式。
