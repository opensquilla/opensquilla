# Chrome DevTools MCP 集成指南

Chrome DevTools MCP 是 Google 在 I/O 2026 发布的官方工具，让 AI Agent 可以直接操控 Chrome 浏览器进行调试和自动化测试。

## 简介

Chrome DevTools MCP 提供以下能力：

- 🔍 **DOM 检查** - 读取和操作页面元素
- 📊 **性能分析** - 录制 trace 并获取性能洞察
- 🌐 **网络监控** - 查看网络请求和响应
- 🖼️ **截图和快照** - 捕获页面状态
- 🪵 **Console 日志** - 查看浏览器控制台消息
- 🤖 **浏览器自动化** - 点击、填表、导航等

## 安装

### 方法一：通过 MCP CLI 安装（推荐）

```bash
claude mcp add chrome-devtools --scope user npx chrome-devtools-mcp@latest
```

### 方法二：手动配置

编辑 `~/.claude.json`（Windows 为 `C:\Users\<用户名>\.claude.json`）：

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

### 方法三：作为 Plugin 安装（MCP + Skills）

```bash
/plugin marketplace add ChromeDevTools/chrome-devtools-mcp
/plugin install chrome-devtools-mcp@chrome-devtools-plugins
```

## 与 OpenSquilla 集成

### 1. 确认 MCP 已安装

```bash
# 检查 MCP 服务器是否已配置
opensquilla mcp list

# 应该看到 chrome-devtools 在列表中
```

### 2. 创建使用 Chrome DevTools 的技能

创建 `skills/web-debug.md`：

```markdown
---
name: web-debug
description: 使用 Chrome DevTools 进行网页调试和自动化
---

# Web 调试技能

## 启动浏览器检查

当用户要求检查网页时，使用 Chrome DevTools MCP 工具：

### 检查页面性能

1. 打开目标页面
2. 录制性能 trace
3. 分析结果并给出建议

### 检查页面元素

1. 导航到目标 URL
2. 获取页面快照
3. 分析 DOM 结构
4. 检查元素定位和样式

### 自动化测试

1. 打开页面
2. 执行用户操作（点击、填表等）
3. 验证结果
4. 截图保存
```

### 3. 配置 OpenSquilla 使用该技能

```bash
opensquilla skills add skills/web-debug.md
```

## 使用示例

### 示例 1：性能分析

```bash
opensquilla agent -m "检查 https://example.com 的性能，给出优化建议"
```

### 示例 2：自动化测试

```bash
opensquilla agent -m "打开 https://mysite.com，点击登录按钮，输入用户名和密码，验证是否成功"
```

### 示例 3：页面诊断

```bash
opensquilla agent -m "分析 https://blog.example.com 的页面结构，找出加载缓慢的原因"
```

## 工作流

### 典型调试流程

```
用户请求
  ↓
OpenSquilla 路由到 SquillaRouter
  ↓
选择合适的模型（如 DeepSeek-Coder）
  ↓
调用 Chrome DevTools MCP 工具
  ↓
获取页面数据
  ↓
分析和诊断
  ↓
生成报告
```

## 注意事项

### Chrome 版本要求

- 推荐：Chrome 144+（支持自动连接）
- 最低：Chrome Stable 当前版本

### 安全建议

⚠️ **不要在包含敏感信息的网页上使用远程调试端口**

### 性能考虑

- 首次启动浏览器会有延迟
- 建议使用 `--headless` 模式进行批量任务
- 完成后及时关闭浏览器

## 常见问题

### Q: 如何检查 Chrome DevTools MCP 是否工作？

```bash
opensquilla agent -m "打开 https://www.google.com 并截图"
```

如果成功，会看到截图输出。

### Q: 支持哪些浏览器？

官方支持：
- Google Chrome
- Chrome for Testing

其他 Chromium 浏览器可能可用，但不保证。

### Q: 如何使用无头模式？

在配置中添加：

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest", "--headless"]
    }
  }
}
```

## 相关链接

- [Chrome DevTools MCP GitHub](https://github.com/ChromeDevTools/chrome-devtools-mcp)
- [Chrome DevTools MCP 官方博客](https://developer.chrome.com/blog/chrome-devtools-mcp)
- [OpenSquilla 文档](../README.md)
