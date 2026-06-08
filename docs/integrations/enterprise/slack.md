# Slack 集成指南

将 OpenSquilla Agent 集成到 Slack，让用户可以通过对话界面使用 AI 能力。

## 🎯 集成架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Slack                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  用户消息 → Slack Bot → Webhook                        │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   OpenSquilla Gateway                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  接收 Webhook → 路由到 Agent → 返回结果               │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Slack API                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  发送响应 → 更新消息 → 发布文件                        │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 1. 创建 Slack App

1. 访问 [Slack API](https://api.slack.com/apps)
2. 点击 "Create New App"
3. 选择 "From scratch"
4. 输入 App 名称和选择工作区

### 2. 配置权限

在 "OAuth & Permissions" 页面添加以下 Bot Token Scopes：

| Scope | 说明 |
|-------|------|
| `chat:write` | 发送消息 |
| `chat:write.public` | 发送公共频道消息 |
| `channels:read` | 读取频道列表 |
| `groups:read` | 读取私有群组 |
| `im:write` | 发送私信 |
| `mpim:write` | 发送群组消息 |
| `files:write` | 上传文件 |

### 3. 安装 App

1. 点击 "Install to Workspace"
2. 复制 "Bot User OAuth Token" (`xoxb-...`)

### 4. 启用事件订阅

在 "Event Subscriptions" 页面：

1. 启用 Events
2. 设置 Request URL：`https://your-domain.com/slack/events`
3. 订阅以下事件：
   - `message_channels`
   - `message_groups`
   - `message_im`

### 5. 配置 OpenSquilla

```bash
# 创建 Slack 集成
opensquilla integrations create slack \
  --bot-token "xoxb-..." \
  --signing-secret "..." \
  --webhook-url "https://your-domain.com/slack/events"

# 配置频道映射
opensquilla integrations configure slack \
  --channel "C123456" \
  --agent "customer-service" \
  --context "slack-channel"

# 启动服务
opensquilla gateway run --integrations slack
```

---

## 📋 频道配置

### 单频道配置

```yaml
# integrations/slack/channels.yaml
channels:
  - channel_id: "C123456"
    channel_name: "#ai-help"
    agent: "general_assistant"
    context:
      company: "MyCompany"
      language: "zh-CN"
    features:
      - "chat"
      - "search"
      - "code_execution"

  - channel_id: "C789012"
    channel_name: "#dev-support"
    agent: "code_assistant"
    context:
      language: "python"
      framework: "fastapi"
    features:
      - "code_review"
      - "debugging"
      - "documentation"
```

### 私信配置

```yaml
dm:
  enabled: true
  agent: "personal_assistant"
  context:
    per_user: true
  features:
    - "task_management"
    - "calendar"
    - "email"
```

---

## 🤖 Agent 模式

### 模式 1：对话模式

用户直接与 Agent 对话：

```bash
opensquilla agent -m "Slack 消息内容" \
  --channel "C123456" \
  --user "U123456"
```

### 模式 2：命令模式

用户使用 `/` 命令触发特定功能：

```yaml
slack_commands:
  - command: "/ask"
    description: "向 AI 提问"
    agent: "general_assistant"
    params:
      - name: "question"
        type: "text"
        required: true

  - command: "/review"
    description: "代码审查"
    agent: "code_reviewer"
    params:
      - name: "code"
        type: "text"
        required: true

  - command: "/summarize"
    description: "总结文档"
    agent: "summarizer"
    params:
      - name: "file"
        type: "file"
        required: true
```

### 模式 3：提及触发

Bot 被提及时响应：

```yaml
mentions:
  enabled: true
  trigger: "@opensquilla"
  agent: "general_assistant"
  context_aware: true
```

---

## 🔧 高级功能

### 文件处理

```yaml
file_handling:
  enabled: true

  # 支持的文件类型
  supported_types:
    - "text"
    - "pdf"
    - "code"
    - "image"

  # 处理工作流
  workflows:
    - trigger: "file.uploaded"
      agent: "file_analyzer"
      action: "analyze"

    - trigger: "code.submitted"
      agent: "code_reviewer"
      action: "review"

  # 文件大小限制
  limits:
    max_size: 10485760  # 10MB
    max_files: 5
```

### 交互式组件

```yaml
interactive_components:
  # 快捷回复
  quick_actions:
    - label: "继续"
      action: "continue"
    - label: "重新生成"
      action: "regenerate"
    - label: "详细说明"
      action: "elaborate"

  # 按钮菜单
  buttons:
    - label: "查看代码"
      action: "show_code"
      style: "primary"
    - label: "复制"
      action: "copy"
      style: "default"

  # 下拉菜单
  select_menus:
    - label: "选择模型"
      options:
        - value: "gpt-4o"
          text: "GPT-4o"
        - value: "claude-3-5-sonnet"
          text: "Claude 3.5 Sonnet"
```

### 线程对话

```yaml
threading:
  enabled: true
  auto_reply_in_thread: true
  max_thread_length: 50
  context_persistence: true
```

---

## 🔐 安全配置

### 权限控制

```yaml
security:
  # 用户白名单
  user_whitelist:
    - "U123456"
    - "U789012"

  # 频道白名单
  channel_whitelist:
    - "C123456"
    - "C789012"

  # 命令权限
  command_permissions:
    "/admin":
      allowed_users:
        - "U123456"
    "/deploy":
      allowed_channels:
        - "C_DEV_OPS"

  # 内容过滤
  content_filter:
    enabled: true
    block_patterns:
      - "\\bpassword\\b"
      - "\\bapi_key\\b"
```

### 数据脱敏

```yaml
data_protection:
  # 消息脱敏
  message_masking:
    enabled: true
    patterns:
      - regex: "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b"
        replacement: "***@***.***"

  # 日志脱敏
  log_masking:
    enabled: true
    mask_user_ids: true
    mask_tokens: true
```

---

## 📊 监控和分析

### 使用分析

```bash
# 查看使用统计
opensquilla integrations stats slack \
  --period "7 days" \
  --group-by channel,user

# 导出对话日志
opensquilla integrations export slack \
  --since "2025-01-01" \
  --format json \
  --output slack-logs.json
```

### 自定义事件

```yaml
analytics:
  events:
    - name: "agent_message_sent"
      properties:
        - "agent_id"
        - "channel_id"
        - "user_id"
        - "response_time"
        - "token_count"

    - name: "command_used"
      properties:
        - "command"
        - "user_id"
        - "channel_id"

    - name: "file_processed"
      properties:
        - "file_type"
        - "file_size"
        - "processing_time"
```

---

## 🧪 测试

### 本地测试

```bash
# 启动测试服务
opensquilla integrations test slack \
  --webhook-url "https://your-domain.com/slack/events"

# 发送测试消息
opensquilla integrations test slack \
  --channel "C123456" \
  --message "测试消息"

# 测试命令
opensquilla integrations test slack \
  --command "/ask" \
  --params '{"question": "测试问题"}'
```

### 调试模式

```bash
# 启用调试日志
opensquilla gateway run \
  --integrations slack \
  --log-level DEBUG \
  --log-format json
```

---

## 🚨 故障排查

### 常见问题

**问题：Webhook 验证失败**

```bash
# 检查 Signing Secret
opensquilla integrations verify slack \
  --signing-secret "your-secret"

# 重新配置
opensquilla integrations update slack \
  --signing-secret "new-secret"
```

**问题：消息不显示**

```bash
# 检查 Bot 权限
opensquilla integrations check slack \
  --scope "chat:write,channels:read"

# 检查频道访问
opensquilla integrations check slack \
  --channel "C123456"
```

**问题：响应缓慢**

```bash
# 检查 Agent 性能
opensquilla agent benchmark \
  --agent "general_assistant" \
  --iterations 10
```

---

## 📞 支持和资源

- [Slack API 文档](https://api.slack.com/)
- [Slack SDK 文档](https://slack.dev/python-slack-sdk/)
- [OpenSquilla 集成文档](../README.md)
- [故障排查指南](../../troubleshooting.md)
