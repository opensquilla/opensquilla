# MCP 服务器总览

Model Context Protocol (MCP) 是 AI Agent 与外部工具和数据源通信的开放标准。

## 什么是 MCP？

MCP 让 AI Agent 能够：
- 🔌 连接外部数据源
- 🛠️ 调用外部工具
- 📡 执行远程操作
- 🔐 安全可控访问

## 可用的 MCP 服务器

### 开发工具

| MCP | 功能 | 文档 |
|-----|------|------|
| **Chrome DevTools** | 浏览器调试、DOM 操作、性能分析 | [chrome-devtools-mcp.md](./chrome-devtools-mcp.md) |
| **GitHub** | 代码搜索、PR/Issue 管理、仓库操作 | [github-mcp.md](./github-mcp.md) |
| **Filesystem** | 文件读写、目录操作、文件监控 | [filesystem-mcp.md](./filesystem-mcp.md) |
| **Git** | Git 操作、版本控制 | [git-mcp.md](./git-mcp.md) |

### 数据服务

| MCP | 功能 | 文档 |
|-----|------|------|
| **Tavily** | 网络搜索、新闻检索 | [tavily-mcp.md](./tavily-mcp.md) |
| **PostgreSQL** | 数据库查询 | [postgres-mcp.md](./postgres-mcp.md) |
| **SQLite** | 本地数据库操作 | [sqlite-mcp.md](./sqlite-mcp.md) |
| **Puppeteer** | 网页自动化、截图 | [puppeteer-mcp.md](./puppeteer-mcp.md) |

### 平台集成

| MCP | 功能 | 文档 |
|-----|------|------|
| **Google Drive** | 文件访问、协作文档 | [google-drive-mcp.md](./google-drive-mcp.md) |
| **Slack** | 消息发送、频道操作 | [slack-mcp.md](./slack-mcp.md) |
| **Notion** | 数据库操作、页面管理 | [notion-mcp.md](./notion-mcp.md) |

## 快速开始

### 安装 MCP CLI

```bash
npm install -g @modelcontextprotocol/inspector
```

### 添加 MCP 服务器

```bash
# Chrome DevTools
claude mcp add chrome-devtools --scope user npx chrome-devtools-mcp@latest

# Tavily 搜索
claude mcp add tavily --scope user npx -y @tavily/mcp-server

# GitHub
claude mcp add github --scope user npx -y @modelcontextprotocol/server-github

# Filesystem
claude mcp add filesystem --scope user npx -y @modelcontextprotocol/server-filesystem /allowed/path
```

### 检查已安装的 MCP

```bash
opensquilla mcp list
```

## 在 OpenSquilla 中使用

### 方法一：创建技能

1. 创建技能文件 `skills/my-mcp-skill.md`
2. 描述 MCP 工具的使用方式
3. 添加技能到 OpenSquilla

```bash
opensquilla skills add skills/my-mcp-skill.md
```

### 方法二：直接调用

配置后，Agent 可以直接调用 MCP 工具：

```bash
opensquilla agent -m "搜索 GitHub 上最新的 React 项目"
```

## MCP 配置文件

配置位置：`~/.claude.json`（Windows：`C:\Users\<用户>\.claude.json`）

### 示例配置

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_..."
      }
    },
    "tavily": {
      "command": "npx",
      "args": ["-y", "@tavily/mcp-server"],
      "env": {
        "TAVILY_API_KEY": "tvly-..."
      }
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
    },
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

## 安全最佳实践

### API Key 管理

- ✅ 使用环境变量存储密钥
- ✅ 定期轮换密钥
- ❌ 不要硬编码密钥
- ❌ 不要提交密钥到 Git

### 权限控制

- Filesystem：只允许必要的目录
- GitHub：使用最小必要的 Token 权限
- 数据库：使用只读用户（如只需读取）

### 审计日志

```bash
# 查看 MCP 调用日志
opensquilla logs --mcp
```

## 常见问题

### Q: MCP 无法连接？

检查：
1. MCP 服务器是否已安装
2. 配置文件格式是否正确
3. API Key/Token 是否有效
4. 网络连接是否正常

### Q: 权限错误？

- Filesystem：检查路径是否在允许列表
- GitHub：检查 Token 权限范围
- 数据库：检查用户权限

### Q: 速率限制？

- GitHub：验证账号可提高限制
- Tavily：检查套餐额度
- 其他：查看服务商文档

## 贡献新的 MCP 文档

发现新的 MCP 服务器？欢迎贡献文档！

1. 在 `docs/mcp/` 创建新的 Markdown 文件
2. 按照 `tavily-mcp.md` 的格式编写
3. 提交 PR

## 相关资源

- [MCP 官网](https://modelcontextprotocol.io/)
- [MCP GitHub](https://github.com/modelcontextprotocol)
- [OpenSquilla 文档](../README.md)
- [技能开发指南](../zh-CN/skill-template.md)
