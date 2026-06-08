# GitHub MCP 集成指南

GitHub MCP 让 AI Agent 能够直接操作 GitHub，包括代码搜索、Issue 管理、PR 操作等。

## 简介

GitHub MCP 提供以下能力：

- 🔍 **代码搜索** - 搜索全 GitHub 代码库
- 📝 **Issue 操作** - 创建、读取、更新 Issue
- 🔀 **PR 管理** - 创建、审查、合并 Pull Request
- 📂 **仓库操作** - Fork、克隆、管理仓库
- 👥 **协作功能** - 管理协作者、团队、评论

## 安装

### 方法一：通过 MCP CLI 安装（推荐）

```bash
claude mcp add github --scope user npx -y @modelcontextprotocol/server-github
```

### 方法二：手动配置

编辑 `~/.claude.json`（Windows 为 `C:\Users\<用户名>\.claude.json`）：

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "your_personal_access_token"
      }
    }
  }
}
```

### 方法三：通过环境变量配置

```bash
# Linux/macOS
export GITHUB_TOKEN="ghp_..."

# Windows PowerShell
$env:GITHUB_TOKEN="ghp_..."

# Windows 持久化
setx GITHUB_TOKEN "ghp_..."
```

## 获取 GitHub Token

1. 访问 [GitHub 设置 > Developer settings](https://github.com/settings/tokens)
2. 点击 "Generate new token" → "Generate new token (classic)"
3. 设置权限：
   - `repo` - 完整仓库访问权限
   - `public_repo` - 仅公共仓库（如只需访问公开代码）
4. 生成并复制 Token

## 与 OpenSquilla 集成

### 1. 确认 MCP 已安装

```bash
# 检查 MCP 服务器是否已配置
opensquilla mcp list

# 应该看到 github 在列表中
```

### 2. 创建使用 GitHub 的技能

创建 `skills/github-operations.md`：

```markdown
---
name: github-operations
description: GitHub 仓库和代码操作
---

# GitHub 操作技能

## 代码搜索

当用户需要搜索代码时：
- 使用 GitHub 代码搜索 API
- 支持精确匹配、语言筛选
- 按星标或更新排序

## Issue 管理

创建和更新 Issue：
- 自动识别问题类型（bug/feature）
- 填充 Issue 模板
- 添加标签和里程碑

## PR 操作

创建和审查 PR：
- 生成 PR 描述
- 审查代码变更
- 添加审查评论
```

### 3. 配置 OpenSquilla 使用该技能

```bash
opensquilla skills add skills/github-operations.md
```

## 使用示例

### 示例 1：搜索代码

```bash
opensquilla agent -m "在 GitHub 上搜索 Python 快速排序实现"
```

### 示例 2：创建 Issue

```bash
opensquilla agent -m "在 opensquilla/opensquilla 创建 Issue，报告文档错误"
```

### 示例 3：审查 PR

```bash
opensquilla agent -m "审查 opensquilla/opensquilla 的 PR #123"
```

### 示例 4：查找仓库

```bash
opensquilla agent -m "搜索 React 相关的高星仓库"
```

## GitHub MCP 工具列表

### 仓库操作

| 工具 | 说明 |
|------|------|
| `create_repository` | 创建新仓库 |
| `fork_repository` | Fork 仓库 |
| `get_file_contents` | 获取文件内容 |
| `create_or_update_file` | 创建/更新文件 |
| `search_repositories` | 搜索仓库 |

### Issue 操作

| 工具 | 说明 |
|------|------|
| `list_issues` | 列出 Issues |
| `get_issue` | 获取 Issue 详情 |
| `create_issue` | 创建 Issue |
| `update_issue` | 更新 Issue |
| `add_issue_comment` | 添加评论 |

### PR 操作

| 工具 | 说明 |
|------|------|
| `list_pull_requests` | 列出 PRs |
| `get_pull_request` | 获取 PR 详情 |
| `create_pull_request` | 创建 PR |
| `update_pull_request` | 更新 PR |
| `merge_pull_request` | 合并 PR |

### 代码搜索

| 工具 | 说明 |
|------|------|
| `search_code` | 搜索代码 |
| `search_issues` | 搜索 Issues |
| `search_commits` | 搜索提交 |

## 搜索语法

### 代码搜索

```
# 基础搜索
import numpy

# 精确匹配
"def quick_sort"

# 语言筛选
machine learning language:python

# 按仓库
react hooks repo:facebook/react

# 排除
authentication NOT password
```

### 仓库搜索

```
# 按星标
tensorflow stars:>10000

# 按语言
web framework language:javascript

# 按更新时间
machine learning pushed:>2024-01-01
```

### Issue 搜索

```
# 按状态
bug is:open

# 按作者
feature author:username

# 按评论数
help wanted comments:>10
```

## 高级用法

### 自动 PR 创建技能

```markdown
---
name: auto-pr-creator
description: 自动创建 Pull Request
---

# 自动 PR 创建技能

## 工作流程

1. 分析用户需求
2. 搜索相关代码
3. 生成修改方案
4. 创建分支
5. 提交变更
6. 创建 PR

## 输出

- PR 链接
- 变更摘要
- 测试建议
```

### 代码审查自动化

```markdown
---
name: code-review-bot
description: 自动代码审查
---

# 代码审查机器人

## 审查项

- 代码风格
- 安全问题
- 性能问题
- 最佳实践

## 操作

- 自动添加审查评论
- 请求修改或批准
- 添加标签
```

## 注意事项

### Token 安全

- ⚠️ **永远不要**将 Token 硬编码到代码中
- ⚠️ 使用环境变量或密钥管理工具
- ⚠️ 定期轮换 Token
- ⚠️ 仅授予必要的权限范围

### API 限制

| 认证 | 每小时请求 |
|------|-----------|
| 无认证 | 60 |
| 基础认证 | 5,000 |
| 验证应用 | 8,000+ |

### 最佳实践

- 批量操作时注意速率限制
- 使用 GraphQL 提高效率（复杂查询）
- 缓存常用数据
- 使用条件请求减少带宽

## 常见问题

### Q: Token 权限不足？

重新生成 Token 时确保勾选所需权限：
- `repo` - 仓库操作
- `read:org` - 组织访问（如需要）

### Q: 搜索返回空结果？

- 检查搜索语法是否正确
- 尝试简化查询词
- 检查是否有权限访问私有仓库

### Q: 如何提高速率限制？

- 验证账号身份
- 使用 GitHub App（更高速率限制）
- 使用缓存减少请求

## 相关链接

- [GitHub REST API](https://docs.github.com/rest)
- [GitHub GraphQL API](https://docs.github.com/graphql)
- [搜索语法](https://docs.github.com/search-github/searching-on-github)
- [个人 Token 设置](https://github.com/settings/tokens)
- [OpenSquilla MCP 文档](./mcp-server.md)
