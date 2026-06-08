# 工作流自动化指南

让 OpenSquilla Agent 按计划执行任务、响应事件、编排复杂流程。

## 🎯 核心概念

### 工作流类型

| 类型 | 触发方式 | 适用场景 | 示例 |
|------|---------|----------|------|
| **定时任务** | Cron 表达式 | 周期性任务 | 每日报表生成、数据同步 |
| **事件驱动** | 外部事件 | 响应式处理 | Webhook 接收、文件变化 |
| **条件触发** | 状态变化 | 状态机 | 审批流转、SLA 触发 |
| **编排流** | 手动/API | 复杂流程 | 多步骤处理、并行任务 |

---

## ⏰ 定时任务

### Cron 表达式

```
┌───────────────── 分钟 (0 - 59)
│ ┌─────────────── 小时 (0 - 23)
│ │ ┌────────────── 日期 (1 - 31)
│ │ │ ┌──────────── 月份 (1 - 12)
│ │ │ │ ┌────────── 星期 (0 - 6, 周日=0)
│ │ │ │ │
* * * * *
```

### 基础配置

```yaml
# workflows/daily-report.yaml
name: "daily_sales_report"
description: "每日销售报告生成"

schedule:
  cron: "0 2 * * *"  # 每天凌晨 2 点
  timezone: "Asia/Shanghai"

# Agent 配置
agent:
  name: "data_analyst"
  model: "claude-3-5-sonnet-20250114"

# 执行参数
params:
  date_range: "yesterday"
  output_format: "pdf"
  recipients:
    - "sales@company.com"
    - "management@company.com"

# 失败重试
retry:
  max_attempts: 3
  backoff: "exponential"
```

### 高级调度

```yaml
# workflows/complex-schedule.yaml
schedule:
  # 工作日每天 9am 和 5pm
  cron: "0 9,17 * * 1-5"
  timezone: "Asia/Shanghai"

  # 或者使用间隔
  interval:
    value: 30
    unit: "minutes"  # seconds, minutes, hours, days

  # 或者使用一次性执行
  once:
    at: "2026-06-01T10:00:00+08:00"

# 排除日期
exclude:
  dates:
    - "2026-12-25"  # 圣诞节
    - "2026-02-10"  # 春节

  # 排除工作日
  weekdays:
    - "saturday"
    - "sunday"
```

### 批量任务

```yaml
# workflows/batch-tasks.yaml
name: "batch_content_generation"
description: "批量生成营销内容"

schedule:
  cron: "0 3 * * 1"  # 每周一凌晨 3 点

# 任务列表
tasks:
  - name: "generate_blog_posts"
    agent: "content_writer"
    params:
      count: 10
      topics:
        - "AI 趋势"
        - "产品更新"
        - "行业洞察"

  - name: "generate_social_posts"
    agent: "social_media_manager"
    params:
      platforms:
        - "weibo"
        - "wechat"
        - "xiaohongshu"

  - name: "send_newsletter"
    agent: "email_marketer"
    depends_on:
      - "generate_blog_posts"
      - "generate_social_posts"
```

---

## 🔔 事件驱动

### Webhook 触发

```yaml
# workflows/webhook-handler.yaml
name: "github_event_handler"
description: "处理 GitHub 事件"

trigger:
  type: "webhook"
  endpoint: "/webhooks/github"

# 验证
authentication:
  method: "signature"
  header: "X-Hub-Signature-256"
  secret: "${WEBHOOK_SECRET}"

# 事件过滤
filters:
  - event: "pull_request"
    action:
      - "opened"
      - "synchronize"

  - event: "issue_comment"
    action: "created"

# 处理逻辑
handlers:
  - condition: "event == 'pull_request' and action == 'opened'"
    agent: "code_reviewer"
    params:
      auto_review: true
      notify_author: true

  - condition: "event == 'issue_comment' and body.includes('/review')"
    agent: "code_reviewer"
    params:
      trigger: "comment"
```

### 文件监控

```yaml
# workflows/file-watcher.yaml
name: "document_processor"
description: "监控文件变化并自动处理"

trigger:
  type: "file_watch"
  paths:
    - "/data/incoming/*.pdf"
    - "/data/incoming/*.docx"
    - "/uploads/documents/*"

  events:
    - "created"
    - "modified"

  # 递归监控
  recursive: true

  # 防抖动
  debounce: 5  # 秒

# 处理管道
pipeline:
  - step: "extract_text"
    agent: "document_parser"

  - step: "classify"
    agent: "content_classifier"
    params:
      categories:
        - "contract"
        - "invoice"
        - "report"

  - step: "store"
    action: "database"
    params:
      table: "processed_documents"
```

### 消息队列

```yaml
# workflows/message-consumer.yaml
name: "order_processor"
description: "处理订单消息"

trigger:
  type: "message_queue"
  provider: "kafka"
  config:
    bootstrap_servers: "${KAFKA_SERVERS}"
    topic: "orders"
    group_id: "opensquilla_processor"

# 消费者配置
consumer:
  max_poll_records: 100
  auto_commit: true
  session_timeout: 30000

# 并发处理
concurrency:
  workers: 10
  max_queue_size: 1000

# 处理逻辑
handler:
  agent: "order_assistant"
  params:
    validate_address: true
    check_inventory: true
    calculate_shipping: true
```

---

## 🔀 条件触发

### 状态机

```yaml
# workflows/approval-flow.yaml
name: "document_approval"
description: "文档审批流程"

# 状态定义
states:
  - id: "draft"
    on_enter:
      agent: "validator"
      action: "validate_format"

  - id: "pending_review"
    timeout: 259200  # 3 天
    on_timeout:
      transition: "escalate"

  - id: "approved"
    on_enter:
      agent: "publisher"
      action: "publish"

  - id: "rejected"
    on_enter:
      agent: "notifier"
      action: "notify_author"

  - id: "escalated"
    on_enter:
      agent: "escalation_manager"
      action: "escalate"

# 转换规则
transitions:
  - from: "draft"
    to: "pending_review"
    trigger: "submit"

  - from: "pending_review"
    to: "approved"
    trigger: "approve"
    condition: "reviewer_role == 'manager'"

  - from: "pending_review"
    to: "rejected"
    trigger: "reject"

  - from: "pending_review"
    to: "escalated"
    trigger: "timeout"

# 审批配置
approval:
  required_reviewers: 2
  reviewer_roles:
    - "manager"
    - "legal"
```

### SLA 触发

```yaml
# workflows/sla-monitor.yaml
name: "sla_breach_handler"
description: "SLA 违规处理"

trigger:
  type: "condition"
  check:
    metric: "ticket_age"
    operator: ">"
    threshold: 7200  # 2 小时
    interval: 60  # 每分钟检查

# 分级处理
escalation:
  levels:
    - threshold: 3600  # 1 小时
      action:
        agent: "notifier"
        recipients:
          - "team-lead@company.com"
        message: "Ticket 超过 1 小时未处理"

    - threshold: 7200  # 2 小时
      action:
        agent: "escalator"
        recipients:
          - "manager@company.com"
          - "support@company.com"
        priority: "high"

    - threshold: 14400  # 4 小时
      action:
        agent: "emergency_handler"
        recipients:
          - "cto@company.com"
        priority: "critical"
```

---

## 🔄 编排流

### 顺序流

```yaml
# workflows/sequential.yaml
name: "data_pipeline"
description: "数据处理管道"

# 定义步骤
steps:
  - id: "extract"
    agent: "data_extractor"
    params:
      source: "postgres://production_db"
      query: "SELECT * FROM orders WHERE date = TODAY"

  - id: "transform"
    agent: "data_transformer"
    depends_on: ["extract"]
    params:
      operations:
        - "normalize"
        - "enrich"
        - "validate"

  - id: "load"
    agent: "data_loader"
    depends_on: ["transform"]
    params:
      destination: "s3://data-warehouse/processed"

  - id: "notify"
    agent: "notifier"
    depends_on: ["load"]
    params:
      message: "数据处理完成"
```

### 并行流

```yaml
# workflows/parallel.yaml
name: "multi_channel_publish"
description: "多渠道发布"

# 并行任务
parallel:
  - id: "publish_wechat"
    agent: "wechat_publisher"
    params:
      account: "official_account"

  - id: "publish_weibo"
    agent: "weibo_publisher"
    params:
      account: "official_weibo"

  - id: "publish_website"
    agent: "cms_publisher"
    params:
      site: "company_website"

# 等待所有任务完成
wait_for_all: true

# 后续任务
next:
  - id: "aggregate_stats"
    agent: "analytics"
    params:
      channels: ["wechat", "weibo", "website"]
```

### 条件分支

```yaml
# workflows/conditional.yaml
name: "smart_router"
description: "智能路由任务"

# 第一步
steps:
  - id: "classify"
    agent: "classifier"
    output:
      field: "category"

# 分支
branches:
  - condition: "{{classify.category}} == 'urgent'"
    steps:
      - id: "urgent_handler"
        agent: "urgent_processor"
        params:
          priority: "critical"
          sla: 300  # 5 分钟

  - condition: "{{classify.category}} == 'routine'"
    steps:
      - id: "routine_handler"
        agent: "routine_processor"
        params:
          priority: "normal"
          batch_size: 50

  - condition: "{{classify.category}} == 'bulk'"
    steps:
      - id: "bulk_handler"
        agent: "bulk_processor"
        params:
          priority: "low"
          schedule: "night"

# 汇聚
converge:
  id: "finalize"
  agent: "finalizer"
```

### 循环

```yaml
# workflows/loop.yaml
name: "batch_processor"
description: "批量处理循环"

# 循环配置
loop:
  id: "process_items"
  over: "{{items}}"  # 数组
  steps:
    - id: "process_single"
      agent: "item_processor"
      params:
        item: "{{loop.item}}"

    - id: "validate"
      agent: "validator"
      params:
        item: "{{process_single.result}}"

  # 最大迭代次数
  max_iterations: 1000

  # 失败处理
  on_error:
    action: "continue"  # continue | break | retry

# 循环后
after:
  - id: "summarize"
    agent: "summarizer"
    params:
      total: "{{loop.total}}"
      succeeded: "{{loop.succeeded}}"
      failed: "{{loop.failed}}"
```

---

## 🔗 工作流 DSL

### 完整示例

```yaml
# workflows/complete-example.yaml
name: "customer_onboarding"
description: "客户入职自动化流程"

# 全局变量
variables:
  company_name: "{{input.company_name}}"
  contact_email: "{{input.contact_email}}"
  plan: "{{input.plan}}"

# 触发器
triggers:
  - type: "webhook"
    endpoint: "/webhooks/signup"

# 开始
start:
  - id: "create_account"
    agent: "account_creator"
    params:
      name: "{{company_name}}"
      plan: "{{plan}}"

# 主流程
workflow:
  - id: "send_welcome"
    agent: "email_sender"
    depends_on: ["create_account"]
    params:
      template: "welcome_email"
      to: "{{contact_email}}"

  # 并行设置
  parallel:
    - id: "setup_billing"
      agent: "billing_setup"
      params:
        plan: "{{plan}}"

    - id: "provision_resources"
      agent: "resource_provisioner"
      params:
        plan: "{{plan}}"

  - id: "schedule_training"
    agent: "training_scheduler"
    depends_on: ["setup_billing", "provision_resources"]
    params:
      plan: "{{plan}}"

  - id: "assign_csm"
    agent: "csm_assigner"
    depends_on: ["schedule_training"]
    params:
      tier: "{{plan}}"

  - id: "finalize"
    agent: "onboarding_finalizer"
    depends_on: ["assign_csm"]
    params:
      notify_internal: true

# 错误处理
error_handlers:
  - match: "account_creation_failed"
    action:
      agent: "error_notifier"
      params:
        severity: "critical"
        recipients: ["admin@company.com"]

  - match: "billing_setup_failed"
    action:
      agent: "retry_handler"
      params:
        max_retries: 3

# 通知
notifications:
  on_start:
    agent: "slack_notifier"
    params:
      channel: "#signups"
      message: "新客户注册: {{company_name}}"

  on_complete:
    agent: "email_sender"
    params:
      to: ["sales@company.com", "success@company.com"]
      template: "onboarding_complete"
```

---

## 🔧 管理命令

### 工作流管理

```bash
# 列出工作流
opensquilla workflows list

# 创建工作流
opensquilla workflows create workflow.yaml

# 更新工作流
opensquilla workflows update workflow.yaml

# 删除工作流
opensquilla workflows delete daily_report

# 启用/禁用
opensquilla workflows enable daily_report
opensquilla workflows disable daily_report
```

### 执行控制

```bash
# 手动触发
opensquilla workflows trigger daily_report \
  --param date=2026-06-01

# 查看执行历史
opensquilla workflows history daily_report \
  --limit 10

# 查看执行状态
opensquilla workflows status <execution_id>

# 取消执行
opensquilla workflows cancel <execution_id>

# 重试失败
opensquilla workflows retry <execution_id>
```

### 调试

```bash
# 本地测试
opensquilla workflows test workflow.yaml \
  --input test-input.json

# 验证配置
opensquilla workflows validate workflow.yaml

# 模拟执行
opensquilla workflows dry-run workflow.yaml

# 查看日志
opensquilla workflows logs <execution_id> --follow
```

---

## 📊 监控和指标

### 执行指标

| 指标 | 说明 | 告警阈值 |
|------|------|---------|
| `workflow_executions_total` | 总执行次数 | - |
| `workflow_duration_seconds` | 执行时长 | > 300s |
| `workflow_failures_total` | 失败次数 | > 5/hour |
| `workflow_queue_size` | 队列长度 | > 100 |

### 健康检查

```yaml
# workflows/health-check.yaml
name: "workflow_health_monitor"
description: "工作流健康监控"

schedule:
  cron: "*/5 * * * *"  # 每 5 分钟

checks:
  - name: "execution_queue"
    condition: "queue_size > 100"
    action:
      agent: "alert_sender"
      params:
        severity: "warning"
        message: "执行队列过长"

  - name: "failure_rate"
    condition: "failure_rate > 0.1"
    action:
      agent: "alert_sender"
      params:
        severity: "critical"
        message: "失败率过高"

  - name: "slow_workflows"
    condition: "avg_duration > 300"
    action:
      agent: "alert_sender"
      params:
        severity: "warning"
        message: "工作流执行缓慢"
```

---

## 🔐 安全和权限

### 执行权限

```yaml
# workflows/rbac.yaml
permissions:
  # 谁可以触发
  triggers:
    - workflow: "daily_report"
      users: ["admin", "ops"]
      roles: ["manager"]

    - workflow: "deploy_production"
      users: ["admin"]
      require_approval: true

  # 资源访问
  resources:
    - workflow: "sales_report"
      databases:
        - "sales_production"
      files:
        - "/data/sales/*"

  # 密钥访问
  secrets:
    - workflow: "notification"
      secrets:
        - "SLACK_TOKEN"
        - "EMAIL_PASSWORD"
```

### 审计日志

```yaml
audit:
  enabled: true

  # 记录事件
  events:
    - "workflow.started"
    - "workflow.completed"
    - "workflow.failed"
    - "workflow.approved"
    - "workflow.rejected"

  # 保留期
  retention_days: 90

  # 导出
  export:
    format: "json"
    destination: "s3://audit-logs/workflows/"
```

---

## 📞 相关资源

- [Agent Teams 编排](./agent-teams.md)
- [企业部署](../enterprise/deployment.md)
- [成本优化](../cost/optimization.md)
- [API 服务](../api/workflows.md)
