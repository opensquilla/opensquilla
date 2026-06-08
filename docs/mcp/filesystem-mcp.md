# Filesystem MCP 集成指南

Filesystem MCP 让 AI Agent 能够安全地读写文件系统，支持文件操作、目录遍历、文件监控等功能。

## 简介

Filesystem MCP 提供以下能力：

- 📁 **文件读写** - 读取、创建、修改文件
- 📂 **目录操作** - 列出、创建、删除目录
- 🔍 **文件搜索** - 按模式搜索文件
- 👀 **文件监控** - 监控文件变化
- 📊 **文件信息** - 获取文件元数据

## 安装

### 方法一：通过 MCP CLI 安装（推荐）

```bash
claude mcp add filesystem --scope user npx -y @modelcontextprotocol/server-filesystem
```

### 方法二：手动配置

编辑 `~/.claude.json`（Windows 为 `C:\Users\<用户名>\.claude.json`）：

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
      "env": {}
    }
  }
}
```

### 方法三：允许多个路径

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path1", "/path2"],
      "env": {}
    }
  }
}
```

### Windows 路径配置

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Projects", "D:\\Documents"],
      "env": {}
    }
  }
}
```

## 安全配置

### 允许的路径

Filesystem MCP **只能访问明确允许的路径**，这是安全特性。

### 推荐配置

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/home/user/projects",
        "/home/user/documents",
        "/tmp/ai-workspace"
      ],
      "env": {}
    }
  }
}
```

### 禁止访问的路径

以下路径不应被允许：
- 系统目录（`/etc`, `/system`, `C:\Windows`）
- 其他用户的 home 目录
- 敏感配置目录（除非必要）

## 与 OpenSquilla 集成

### 1. 确认 MCP 已安装

```bash
# 检查 MCP 服务器是否已配置
opensquilla mcp list

# 应该看到 filesystem 在列表中
```

### 2. 创建使用文件系统的技能

创建 `skills/file-operations.md`：

```markdown
---
name: file-operations
description: 文件系统操作技能
---

# 文件操作技能

## 批量处理

处理多个文件：
- 遍历目录
- 按模式筛选
- 批量修改

## 文件分析

分析文件内容：
- 读取文件
- 分析结构
- 生成报告

## 文件组织

整理文件：
- 按类型分类
- 重命名规范
- 清理重复
```

### 3. 配置 OpenSquilla 使用该技能

```bash
opensquilla skills add skills/file-operations.md
```

## 使用示例

### 示例 1：批量重命名

```bash
opensquilla agent -m "将 ./photos 目录下所有文件按日期重命名"
```

### 示例 2：代码统计

```bash
opensquilla agent -m "统计项目中 Python 代码行数"
```

### 示例 3：文件分类

```bash
opensquilla agent -m "将下载文件夹按文件类型分类整理"
```

### 示例 4：日志分析

```bash
opensquilla agent -m "分析 ./logs/app.log 中的错误模式"
```

## Filesystem MCP 工具列表

### 文件读取

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件内容 |
| `read_multiple_files` | 批量读取文件 |
| `list_directory` | 列出目录内容 |
| `search_files` | 搜索文件 |

### 文件写入

| 工具 | 说明 |
|------|------|
| `write_file` | 写入文件 |
| `create_directory` | 创建目录 |
| `move_file` | 移动文件 |
| `copy_file` | 复制文件 |

### 文件信息

| 工具 | 说明 |
|------|------|
| `get_file_info` | 获取文件元数据 |
| `calculate_hash` | 计算文件哈希 |
| `get_allowed_directories` | 获取允许访问的目录 |

### 文件操作

| 工具 | 说明 |
|------|------|
| `delete_file` | 删除文件 |
| `delete_directory` | 删除目录 |
| `compress_files` | 压缩文件 |
| `decompress_files` | 解压文件 |

## 高级用法

### 批量处理技能

```markdown
---
name: batch-processor
description: 批量文件处理
---

# 批量处理技能

## 模式

1. 扫描目录
2. 应用筛选
3. 执行操作
4. 生成报告

## 支持的操作

- 批量重命名
- 批量转换
- 批量压缩
- 批量分析
```

### 文件监控技能

```markdown
---
name: file-monitor
description: 监控文件变化
---

# 文件监控技能

## 监控类型

- 文件创建
- 文件修改
- 文件删除
- 权限变更

## 响应动作

- 记录日志
- 触发处理
- 发送通知
```

## 注意事项

### 安全考虑

- ⚠️ 只允许必要的目录
- ⚠️ 定期审查允许的路径列表
- ⚠️ 谨慎执行删除操作
- ⚠️ 重要文件操作前备份

### 性能优化

- 大文件使用流式处理
- 批量操作控制并发数
- 搜索时使用合适的深度
- 缓存频繁访问的文件信息

### 路径处理

- Windows 路径使用 `\\` 或 `/`
- 相对路径相对于允许的目录
- 特殊字符需要正确转义
- 路径长度限制（Windows 260 字符）

## 常见问题

### Q: 为什么访问被拒绝？

路径不在允许列表中。需要更新 MCP 配置：

```json
"args": ["-y", "@modelcontextprotocol/server-filesystem", "你的路径"]
```

### Q: 如何处理大文件？

使用流式处理或分块读取，避免一次性加载整个文件。

### Q: 支持符号链接吗？

支持，但需要确保符号链接目标也在允许路径内。

### Q: 如何监控文件变化？

使用 `watch_directory` 工具，设置回调函数处理变化事件。

## 相关链接

- [Filesystem MCP GitHub](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem)
- [MCP 规范](https://modelcontextprotocol.io/)
- [OpenSquilla MCP 文档](./mcp-server.md)
