# Tavily MCP 集成指南

Tavily MCP 是一个强大的网络搜索 MCP 服务器，为 AI Agent 提供实时网络搜索能力。

## 简介

Tavily MCP 提供：

- 🔍 **实时搜索** - 获取最新网络信息
- 📰 **新闻检索** - 按时间范围筛选新闻
- 📊 **深度搜索** - 更全面的搜索结果
- 🌐 **多语言支持** - 支持全球搜索

## 安装

### 方法一：通过 MCP CLI 安装（推荐）

```bash
claude mcp add tavily --scope user npx -y @tavily/mcp-server
```

### 方法二：手动配置

编辑 `~/.claude.json`（Windows 为 `C:\Users\<用户名>\.claude.json`）：

```json
{
  "mcpServers": {
    "tavily": {
      "command": "npx",
      "args": ["-y", "@tavily/mcp-server"],
      "env": {
        "TAVILY_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### 方法三：通过环境变量配置

```bash
# Linux/macOS
export TAVILY_API_KEY="tvly-..."

# Windows PowerShell
$env:TAVILY_API_KEY="tvly-..."

# Windows 持久化
setx TAVILY_API_KEY "tvly-..."
```

## 获取 API Key

1. 访问 [Tavily 官网](https://tavily.com/)
2. 注册账号
3. 在控制台获取 API Key
4. 免费套餐包含每月 1000 次搜索

## 与 OpenSquilla 集成

### 1. 确认 MCP 已安装

```bash
# 检查 MCP 服务器是否已配置
opensquilla mcp list

# 应该看到 tavily 在列表中
```

### 2. 创建使用 Tavily 的技能

创建 `skills/web-search.md`：

```markdown
---
name: web-search
description: 使用 Tavily 进行实时网络搜索
---

# 网络搜索技能

当用户需要获取最新信息时，使用 Tavily MCP 工具：

### 新闻搜索

搜索最近新闻：
- 设置时间范围为 day/week/month
- 限制结果数量
- 优先显示权威来源

### 通用搜索

搜索网络信息：
- 使用高级搜索语法
- 筛选特定域名
- 排除无关结果

### 研究模式

深度研究主题：
- 多轮搜索扩大范围
- 综合多个来源
- 提供完整分析
```

### 3. 配置 OpenSquilla 使用该技能

```bash
opensquilla skills add skills/web-search.md
```

## 使用示例

### 示例 1：搜索最新科技新闻

```bash
opensquilla agent -m "搜索今天的人工智能新闻"
```

### 示例 2：研究特定主题

```bash
opensquilla agent -m "研究量子计算的最新进展，包括主要公司和突破"
```

### 示例 3：获取实时数据

```bash
opensquilla agent -m "查询当前比特币价格和近期走势"
```

## Tavily 搜索参数

### 基础参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `query` | 搜索查询 | 必填 |
| `max_results` | 最大结果数 | 10 |
| `search_depth` | 搜索深度 | basic |
| `time_range` | 时间范围 | 无 |

### 搜索深度

- `basic` - 快速搜索，适合简单查询
- `advanced` - 深度搜索，更全面
- `fast` - 极速搜索，优化延迟
- `ultra-fast` - 超高速，仅结果

### 时间范围

- `day` - 最近 24 小时
- `week` - 最近一周
- `month` - 最近一月
- `year` - 最近一年
- 不设置 - 无时间限制

### 域名筛选

```python
# 仅搜索特定域名
include_domains = ["github.com", "stackoverflow.com"]

# 排除特定域名
exclude_domains = ["spam-site.com"]
```

## 高级用法

### 创建专业搜索技能

```markdown
---
name: academic-search
description: 学术论文搜索
---

# 学术搜索技能

使用 Tavily 搜索学术论文和研究：

## 搜索策略

1. 优先搜索 .edu 域名
2. 包含 "paper"、"research"、"study" 关键词
3. 使用引号查找精确匹配

## 输出格式

- 论文标题
- 作者信息
- 发布时间
- 核心发现
- 链接
```

### 结合其他 MCP

Tavily 可以与其他 MCP 配合使用：

- **Tavily + GitHub** - 搜索 GitHub 上的代码
- **Tavily + Filesystem** - 搜索后保存结果
- **Tavily + Chrome DevTools** - 搜索后验证页面

## 注意事项

### API 限制

| 套餐 | 每月搜索次数 | 并发 |
|------|-------------|------|
| 免费 | 1,000 | 1 |
| Pro | 15,000 | 5 |
| Enterprise | 自定义 | 自定义 |

### 最佳实践

- 缓存常见查询结果
- 使用 `search_depth` 参数平衡速度和质量
- 对时间敏感查询设置 `time_range`
- 验证搜索结果来源可信度

### 错误处理

```python
# API Key 无效
{"error": "Invalid API key"}

# 超出限额
{"error": "Rate limit exceeded"}

# 无结果
{"results": []}
```

## 常见问题

### Q: 如何检查余额？

访问 [Tavily 控制台](https://tavily.com/home) 查看使用情况。

### Q: 搜索结果延迟多少？

- `basic`: 1-3 秒
- `advanced`: 3-8 秒
- `fast`: <1 秒
- `ultra-fast`: <0.5 秒

### Q: 支持哪些语言？

支持所有语言，但非英文搜索可能效果稍降。

### Q: 可以搜索付费内容吗？

不支持搜索需要付费才能访问的内容。

## 相关链接

- [Tavily 官网](https://tavily.com/)
- [Tavily 文档](https://docs.tavily.com/)
- [Tavily GitHub](https://github.com/tavily/mcp-server)
- [OpenSquilla MCP 文档](./mcp-server.md)
