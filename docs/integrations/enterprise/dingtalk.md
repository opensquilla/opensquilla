# 钉钉集成指南

将 OpenSquilla Agent 集成到钉钉，让企业用户通过钉钉机器人使用 AI 能力。

## 🎯 集成架构

```
┌─────────────────────────────────────────────────────────────┐
│                        钉钉                                 │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  用户消息 → 群机器人/企业应用 → Webhook               │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   OpenSquilla Gateway                         │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  接收 Webhook → 验证签名 → 路由 Agent → 返回结果     │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     钉钉 API                                 │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  发送消息 → 群聊/单聊 → 卡片/按钮                       │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 1. 创建钉钉机器人

#### 方式一：群机器人（适合快速测试）

1. 打开钉钉群设置
2. 点击 "智能群助手" → "添加机器人" → "自定义"
3. 设置机器人名称和头像
4. 选择安全设置（推荐加签）
5. 复制 Webhook 地址

#### 方式二：企业应用（适合生产环境）

1. 登录 [钉钉开放平台](https://open.dingtalk.com/)
2. 创建企业内部应用
3. 在 "应用开发" → "机器人" 配置
4. 获取 AppKey 和 AppSecret
5. 设置消息接收地址

### 2. 配置 OpenSquilla

#### 群机器人配置

```bash
# 添加群机器人
opensquilla integrations create dingtalk-bot \
  --webhook "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." \
  --secret "SEC..." \
  --agent "general_assistant"

# 发送测试消息
opensquilla integrations test dingtalk-bot \
  --message "测试消息"
```

#### 企业应用配置

```bash
# 添加企业应用
opensquilla integrations create dingtalk-app \
  --app-key "ding..." \
  --app-secret "..." \
  --agent-key "..." \
  --callback-url "https://your-domain.com/dingtalk/callback"

# 配置事件订阅
opensquilla integrations configure dingtalk-app \
  --events "chat,conversation"
```

---

## 📋 消息类型

### 文本消息

```yaml
message_types:
  text:
    enabled: true
    max_length: 2048
    markdown: true
```

### Markdown 消息

```yaml
markdown:
  enabled: true
  title: "AI 助手"
  text: |
    ## 查询结果

    **问题**：{{user_query}}

    **答案**：{{agent_response}}

    ---
    *由 OpenSquilla 提供*
```

### 卡片消息

```yaml
card:
  enabled: true

  # 卡片模板
  templates:
    - name: "answer_card"
      title: "AI 回答"
      content:
        - type: "markdown"
          text: "{{answer}}"

      - type: "button"
        text: "继续提问"
        action: "continue"

      - type: "button"
        text: "查看详情"
        action: "details"

    - name: "code_card"
      title: "代码生成"
      content:
        - type: "markdown"
          text: |
            ```{{language}}
            {{code}}
            ```

      - type: "button"
        text: "复制代码"
        action: "copy"
```

### Feed 卡片

```yaml
feed_card:
  enabled: true

  items:
    - title: "{{title}}"
      description: "{{description}}"
      url: "{{link}}"
      image: "{{thumbnail}}"
```

---

## 🤖 对话模式

### 单轮对话

```yaml
single_turn:
  enabled: true
  trigger: "直接消息"
  agent: "general_assistant"
  timeout: 30
```

### 多轮对话

```yaml
multi_turn:
  enabled: true
  session_timeout: 300  # 5 分钟
  max_turns: 10
  context_persistence: true
```

### 知识问答

```yaml
knowledge_qa:
  enabled: true
  knowledge_base: "company_kb"
  trigger_keywords:
    - "查询"
    - "搜索"
    - "查找"
  retrieval:
    top_k: 3
    show_sources: true
```

---

## 🔧 高级功能

### 消息分流

```yaml
routing:
  # 基于关键词分流
  keyword_routes:
    - keywords: ["bug", "错误", "故障"]
      agent: "technical_support"
      priority: high

    - keywords: ["发票", "报销", "费用"]
      agent: "finance_assistant"
      priority: normal

    - keywords: ["代码", "开发", "部署"]
      agent: "dev_assistant"
      priority: normal

  # 基于部门分流
  department_routes:
    - department: "研发部"
      agent: "dev_assistant"
      skills:
        - "code_review"
        - "debugging"

    - department: "市场部"
      agent: "marketing_assistant"
      skills:
        - "content_generation"
        - "market_analysis"
```

### 群协作

```yaml
group_chat:
  enabled: true

  # @机器人触发
  mention_trigger:
    enabled: true
    patterns:
      - "@AI助手"
      - "@opensquilla"

  # 群命令
  commands:
    - command: "/summarize"
      description: "总结群聊内容"
      agent: "summarizer"
      params:
        - name: "messages"
          type: "recent"
          count: 50

    - command: "/action-items"
      description: "提取行动项"
      agent: "task_extractor"

  # 群协作模式
  collaboration:
    enabled: true
    auto_assign: true
    mention_users: true
```

### 文件处理

```yaml
file_handling:
  enabled: true

  # 支持的文件类型
  types:
    - "document"  # 文档
    - "image"     # 图片
    - "code"      # 代码

  # 文件处理工作流
  workflows:
    - trigger: "document.uploaded"
      agent: "document_analyzer"
      actions:
        - "extract_text"
        - "summarize"
        - "extract_keywords"

    - trigger: "image.uploaded"
      agent: "image_analyzer"
      actions:
        - "ocr"
        - "detect_objects"
        - "generate_caption"
```

---

## 🔐 安全配置

### 验证签名

```yaml
security:
  # 签名验证
  signature_verification:
    enabled: true
    algorithm: "HMAC-SHA256"

  # IP 白名单
  ip_whitelist:
    - "47.97.0.0/16"
    - "47.98.0.0/16"

  # 加密
  encryption:
    enabled: true
    algorithm: "AES-256-GCM"
```

### 权限控制

```yaml
permissions:
  # 用户权限
  user_permissions:
    - user_id: "..."
      allowed_commands:
        - "ask"
        - "search"
      denied_commands:
        - "admin"

  # 部门权限
  department_permissions:
    - department: "研发部"
      allowed_agents:
        - "code_assistant"
        - "reviewer"

  # 时间限制
  time_restrictions:
    - department: "客服部"
      work_hours:
        start: "09:00"
        end: "18:00"
      timezone: "Asia/Shanghai"
```

---

## 📊 监控和分析

### 使用统计

```bash
# 查看使用统计
opensquilla integrations stats dingtalk \
  --period "7 days" \
  --group-by department,user

# 导出对话记录
opensquilla integrations export dingtalk \
  --since "2025-01-01" \
  --format json \
  --output dingtalk-logs.json
```

### 自定义分析

```yaml
analytics:
  events:
    - name: "message_received"
      properties:
        - "sender_id"
        - "department"
        - "message_type"
        - "timestamp"

    - name: "agent_response"
      properties:
        - "agent_id"
        - "response_time"
        - "token_count"
        - "satisfaction"

    - name: "file_processed"
      properties:
        - "file_type"
        - "file_size"
        - "processing_time"
```

---

## 🧪 测试和调试

### 本地测试

```bash
# 启动测试服务
opensquilla integrations test dingtalk \
  --webhook-url "https://your-domain.com/dingtalk/callback"

# 发送测试消息
opensquilla integrations test dingtalk \
  --chatbot "your-chatbot-id" \
  --message "测试消息"

# 测试文件处理
opensquilla integrations test dingtalk \
  --file-upload "test.pdf" \
  --agent "document_analyzer"
```

### 调试模式

```bash
# 启用调试日志
opensquilla gateway run \
  --integrations dingtalk \
  --log-level DEBUG \
  --log-format json

# 查看实时日志
opensquilla integrations logs dingtalk --follow
```

---

## 🚨 故障排查

### 常见问题

**问题：签名验证失败**

```bash
# 检查签名配置
opensquilla integrations verify dingtalk \
  --app-secret "..."

# 重新配置
opensquilla integrations update dingtalk \
  --app-secret "new-secret"
```

**问题：消息发送失败**

```bash
# 检查 API 限流
opensquilla integrations check dingtalk \
  --rate-limit

# 重试发送
opensquilla integrations retry dingtalk \
  --message-id "..."
```

**问题：文件处理失败**

```bash
# 检查文件权限
opensquilla integrations check dingtalk \
  --media-id "..."

# 查看处理日志
opensquilla integrations logs dingtalk \
  --filter "file_processing"
```

---

## 📞 支持和资源

- [钉钉开放平台](https://open.dingtalk.com/)
- [钉钉机器人文档](https://open.dingtalk.com/document/robots/custom-robot-access)
- [企业应用开发文档](https://open.dingtalk.com/document/org-app-development)
- [OpenSquilla 集成文档](../README.md)
