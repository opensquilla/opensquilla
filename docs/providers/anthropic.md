# Anthropic (Claude) 提供商配置

Anthropic 提供 Claude 系列大模型，包括 Claude 3.5 Sonnet、Claude 3 Opus 等。

## 配置步骤

### 1. 获取 API Key

访问 [Anthropic Console](https://console.anthropic.com/) 注册并获取 API Key。

### 2. 环境变量配置

```bash
# Linux/macOS
export ANTHROPIC_API_KEY="sk-ant-..."

# Windows PowerShell
$env:ANTHROPIC_API_KEY="sk-ant-..."

# Windows 持久化
setx ANTHROPIC_API_KEY "sk-ant-..."
```

### 3. OpenSquilla 配置

```bash
opensquilla onboard --provider anthropic --api-key-env ANTHROPIC_API_KEY
```

### 4. 模型选择

```bash
# Claude 3.5 Sonnet (推荐，高性价比)
opensquilla configure provider --provider anthropic --model claude-3-5-sonnet-20241022

# Claude 3.5 Sonnet (最新)
opensquilla configure provider --provider anthropic --model claude-3-5-sonnet-20250114

# Claude 3 Opus (最强能力)
opensquilla configure provider --provider anthropic --model claude-3-opus-20240229

# Claude 3 Haiku (最快速度)
opensquilla configure provider --provider anthropic --model claude-3-haiku-20240307
```

## 可用模型

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `claude-3-5-sonnet-20250114` | Claude 3.5 Sonnet 最新 | 通用、编程、分析（推荐） |
| `claude-3-5-sonnet-20241022` | Claude 3.5 Sonnet | 通用、编程、分析 |
| `claude-3-opus-20240229` | Claude 3 Opus | 复杂推理、创意写作 |
| `claude-3-sonnet-20240229` | Claude 3 Sonnet | 平衡性能和成本 |
| `claude-3-haiku-20240307` | Claude 3 Haiku | 快速响应、批量处理 |

## 价格参考

| 模型 | 输入 (美元/百万 Token) | 输出 (美元/百万 Token) |
|------|---------------------|---------------------|
| Claude 3.5 Sonnet | $3.00 | $15.00 |
| Claude 3 Opus | $15.00 | $75.00 |
| Claude 3 Sonnet | $3.00 | $15.00 |
| Claude 3 Haiku | $0.25 | $1.25 |

*价格仅供参考，以官方为准*

## 特色功能

### 扩展上下文

Claude 支持 200K Token 上下文：

```bash
# Claude 3.5 Sonnet 和 Opus 支持 200K 上下文
opensquilla agent -m "分析这个长文档的内容" --context-file large_document.txt
```

### 视觉能力

Claude 3.5 Sonnet 支持图像输入：

```bash
opensquilla agent -m "描述这张图片的内容：path/to/image.png"
```

### Artifacts（代码预览）

Claude 3.5 Sonnet 可以生成可预览的内容块：

- HTML/CSS/JavaScript 组件
- SVG 图形
- React 组件
- Mermaid 图表
- 数学公式

### 智能体风格指令

Claude 原生支持系统提示和风格指令：

```json
{
  "system": "你是一个专业的代码审查员，专注于安全性和性能优化。",
  "thinking": "intermediate" // 显示思考过程
}
```

## 优势

- ✅ 强大的分析和推理能力
- ✅ 200K 超长上下文
- ✅ 原生支持多种模态
- ✅ 安全性和对齐性优秀
- ✅ 编程能力强
- ✅ 支持显示思考过程

## 常见问题

### Q: 如何查看用量？

访问 [Anthropic Console > Usage](https://console.anthropic.com/settings/usage) 查看详细用量。

### Q: 速率限制是多少？

不同套餐有不同限制，详见官方文档。

### Q: 支持流式输出吗？

✅ 支持，OpenSquilla 默认启用 Stream 模式。

### Q: Claude 和 GPT-4 怎么选？

| 维度 | Claude 3.5 Sonnet | GPT-4o |
|------|------------------|--------|
| 编程 | 更强 | 强 |
| 分析 | 更强 | 强 |
| 创意写作 | 强 | 更强 |
| 视觉 | 强 | 更强 |
| 价格 | $3/$15 | $5/$15 |
| 上下文 | 200K | 128K |

### Q: 如何启用思考模式？

```bash
export ANTHROPIC_THINKING="intermediate"  # 显示简要思考
export ANTHROPIC_THINKING="detailed"     # 显示详细思考
```

## 最佳实践

### 选择合适的模型

- **日常任务**：Claude 3.5 Sonnet（性价比最高）
- **复杂推理**：Claude 3 Opus（能力最强）
- **批量处理**：Claude 3 Haiku（速度最快、成本最低）

### 优化成本

- 使用 Haiku 处理简单任务
- 使用 Sonnet 处理中等复杂度任务
- 仅在必要时使用 Opus
- 启用缓存减少重复输入成本

### 提示词技巧

Claude 对以下格式响应更好：

- 使用明确的角色定位
- 提供示例（few-shot）
- 使用 XML 标签分隔内容
- 启用思考模式处理复杂任务

## 相关资源

- [Anthropic 官网](https://www.anthropic.com/)
- [Anthropic Console](https://console.anthropic.com/)
- [Claude API 文档](https://docs.anthropic.com/claude/reference/)
- [定价页面](https://www.anthropic.com/pricing)
- [OpenSquilla 配置文档](../configuration.md)
