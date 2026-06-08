# 企业应用集成总览

将 OpenSquilla Agent 集成到企业日常使用的通讯和协作平台。

## 🌐 支持的平台

| 平台 | 类型 | 文档 | 适用场景 |
|------|------|------|----------|
| **Slack** | 即时通讯 | [slack.md](./slack.md) | 国际化企业、科技公司 |
| **钉钉** | 企业协作 | [dingtalk.md](./dingtalk.md) | 国内企业、制造业 |
| **飞书** | 企业协作 | [feishu.md](./feishu.md) | 互联网企业、初创公司 |
| **Teams** | 企业协作 | [teams.md](./teams.md) | Microsoft 生态企业 |
| **企业微信** | 企业通讯 | [wechat-work.md](./wechat-work.md) | 传统企业、服务业 |

---

## 🎯 集成模式

### 模式对比

| 模式 | 部署难度 | 功能丰富度 | 成本 | 适用场景 |
|------|---------|-----------|------|----------|
| **Webhook** | 低 | 低 | 低 | 简单通知、单向推送 |
| **Bot** | 中 | 中 | 中 | 对话、命令、简单交互 |
| **应用** | 高 | 高 | 高 | 复杂交互、企业级功能 |

### Webhook 模式

```yaml
# 最简单的集成方式
webhook:
  url: "https://platform.example.com/webhook"
  events:
    - "agent.response"
    - "task.completed"

  payload:
    message: "{{agent_response}}"
    metadata:
      timestamp: "{{timestamp}}"
      user: "{{user_id}}"
```

### Bot 模式

```yaml
# 机器人集成
bot:
  type: "group_robot"  # 群机器人
  platform: "dingtalk"

  commands:
    - name: "/ask"
      handler: "query_agent"

  interactions:
    - type: "button"
      actions:
        - "continue"
        - "regenerate"
```

### 应用模式

```yaml
# 企业应用集成
app:
  type: "enterprise_app"
  platform: "feishu"

  features:
    - "multi_tenant"
    - "user_auth"
    - "data_sync"
    - "admin_console"
```

---

## 📋 集成清单

### 部署前检查

- [ ] 已在目标平台创建应用/Bot
- [ ] 已获取必要的 API Key/Secret
- [ ] 已配置回调 URL
- [ ] 已设置必要的权限
- [ ] 已测试基础连通性

### 功能测试

- [ ] 消息接收正常
- [ ] 消息发送正常
- [ ] 命令响应正常
- [ ] 文件处理正常
- [ ] 卡片交互正常
- [ ] 权限控制有效

### 生产就绪

- [ ] 错误处理完善
- [ ] 监控告警配置
- [ ] 日志记录完整
- [ ] 性能测试通过
- [ ] 安全审查完成

---

## 🔧 通用配置

### Webhook 处理

```yaml
webhook:
  # 验证
  verification:
    enabled: true
    method: "signature"  # signature | token | hmac

  # 重试
  retry:
    max_attempts: 3
    backoff: "exponential"
    delays: [1, 5, 15]  # 秒

  # 超时
  timeout:
    connect: 5
    read: 30
```

### 消息模板

```yaml
message_templates:
  # 文本模板
  text:
    default: "{{response}}"
    error: "抱歉，处理您的请求时出错：{{error}}"

  # 卡片模板
  card:
    title: "{{title}}"
    content: "{{content}}"
    actions:
      - label: "继续"
        type: "postback"
        data: "continue"

  # 富文本模板
  rich_text:
    sections:
      - type: "markdown"
        text: "{{markdown_content}}"
```

### 错误处理

```yaml
error_handling:
  # 用户友好错误
  user_facing:
    timeout: "请求超时，请稍后重试"
    rate_limit: "请求过于频繁，请稍后再试"
    error: "系统错误，请联系管理员"

  # 运维告警
  ops_alerts:
    critical:
      - "webhook_failed"
      - "auth_error"
    warning:
      - "high_latency"
      - "rate_limit_approaching"
```

---

## 🔐 安全最佳实践

### 验证和授权

```yaml
security:
  # 来源验证
  source_verification:
    - type: "ip_whitelist"
      ips: ["platform.ip.range"]

    - type: "signature"
      secret: "${WEBHOOK_SECRET}"

  # 用户授权
  user_authorization:
    method: "oauth2"  # oauth2 | jwt | saml
    provider: "company_sso"

  # 权限控制
  permissions:
    default: "user"
    admin_users: ["user1", "user2"]
    command_permissions:
      "/admin": ["admin"]
```

### 数据保护

```yaml
data_protection:
  # 敏感信息过滤
  sensitive_filter:
    enabled: true
    patterns:
      - "\\bpassword\\b"
      - "\\bapi_key\\b"
      - "\\bsk-[^\\s]+\\b"

  # 日志脱敏
  log_masking:
    enabled: true
    mask_patterns:
      - "user_id"
      - "token"

  # 加密
  encryption:
    in_transit: true  # TLS
    at_rest: true     # 加密存储
```

---

## 📊 监控和指标

### 核心指标

| 指标 | 说明 | 告警阈值 |
|------|------|---------|
| `integration_requests_total` | 总请求数 | - |
| `integration_requests_duration` | 请求延迟 | > 5s |
| `integration_errors_total` | 错误数 | > 10/min |
| `integration_rate_limit_hits` | 限流命中 | > 5/min |

### 告警配置

```yaml
alerts:
  - name: "HighErrorRate"
    condition: "rate(integration_errors_total[5m]) > 0.1"
    severity: critical

  - name: "SlowResponse"
    condition: "integration_requests_duration > 5s"
    severity: warning

  - name: "RateLimit"
    condition: "integration_rate_limit_hits > 10"
    severity: warning
```

---

## 🚀 快速开始

### Slack 快速集成

```bash
# 1. 创建 Slack App
# 2. 配置 OpenSquilla
opensquilla integrations create slack \
  --bot-token "xoxb-..." \
  --signing-secret "..."

# 3. 测试
opensquilla integrations test slack --message "测试"
```

### 钉钉快速集成

```bash
# 1. 创建群机器人
# 2. 配置 OpenSquilla
opensquilla integrations create dingtalk-bot \
  --webhook "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."

# 3. 测试
opensquilla integrations test dingtalk-bot --message "测试"
```

### 飞书快速集成

```bash
# 1. 创建飞书应用
# 2. 配置 OpenSquilla
opensquilla integrations create feishu \
  --app-id "... " \
  --app-secret "..."

# 3. 测试
opensquilla integrations test feishu --message "测试"
```

---

## 📞 支持和资源

### 平台文档

- [Slack API](https://api.slack.com/)
- [钉钉开放平台](https://open.dingtalk.com/)
- [飞书开放平台](https://open.feishu.cn/)
- [Teams 开发平台](https://dev.teams.microsoft.com/)
- [企业微信开发文档](https://developer.work.weixin.qq.com/)

### OpenSquilla 资源

- [集成指南](../README.md)
- [API 文档](../../api/README.md)
- [故障排查](../../troubleshooting.md)
- [企业部署](../enterprise/deployment.md)
