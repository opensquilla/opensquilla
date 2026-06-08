# 月之暗面 (Moonshot) 提供商配置

月之暗面提供 Kimi 系列大模型，支持长文本上下文。

## 配置步骤

### 1. 获取 API Key

访问 [月之暗面开放平台](https://platform.moonshot.cn/) 注册并获取 API Key。

### 2. 环境变量配置

```bash
# Linux/macOS
export MOONSHOT_API_KEY="sk-..."

# Windows PowerShell
$env:MOONSHOT_API_KEY="sk-..."

# Windows 持久化
setx MOONSHOT_API_KEY "sk-..."
```

### 3. OpenSquilla 配置

```bash
opensquilla onboard --provider moonshot --api-key-env MOONSHOT_API_KEY
```

### 4. 模型选择

```bash
# Kimi (moonshot-v1-8k)
opensquilla configure provider --provider moonshot --model moonshot-v1-8k

# Kimi (moonshot-v1-32k)
opensquilla configure provider --provider moonshot --model moonshot-v1-32k

# Kimi (moonshot-v1-128k)
opensquilla configure provider --provider moonshot --model moonshot-v1-128k
```

## 可用模型

| 模型 | 上下文长度 | 适用场景 |
|------|-----------|----------|
| `moonshot-v1-8k` | 8K | 短对话、快速响应 |
| `moonshot-v1-32k` | 32K | 长文档处理 |
| `moonshot-v1-128k` | 128K | 超长文本分析 |

## 特色功能

### 文件上传

Kimi 支持直接上传文件进行分析：

```bash
opensquilla agent -m "分析这个文件：path/to/document.pdf"
```

### 网页搜索

Kimi 内置联网搜索能力，可获取最新信息。

## 优势

- ✅ 超长上下文 (128K)
- ✅ 文件解析能力强
- ✅ 联网搜索
- ✅ 中文理解优秀

## 常见问题

### Q: 如何查看用量？

访问 [月之暗面控制台](https://platform.moonshot.cn/console) 查看用量和余额。

### Q: 免费额度是多少？

新用户可获得一定免费额度，具体以平台公告为准。
