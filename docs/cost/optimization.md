# 成本优化与监控指南

企业级 AI Agent 成本管理是商用成功的关键。本指南介绍如何优化和监控 OpenSquilla 的 Token 使用成本。

## 💰 成本构成

### 成本分解

```
┌─────────────────────────────────────────────────────────────┐
│                    总成本结构                                │
├─────────────────────────────────────────────────────────────┤
│  LLM 调用成本 ████████████████████ 70-80%                  │
│  - 输入 Token                                              │
│  - 输出 Token                                              │
│  - 不同提供商价格差异                                        │
├─────────────────────────────────────────────────────────────┤
│  向量检索成本 ██████ 5-10%                                  │
│  - 嵌入成本                                                │
│  - 存储成本                                                │
├─────────────────────────────────────────────────────────────┤
│  工具调用成本 ███ 5%                                        │
│  - API 调用                                               │
│  - 数据传输                                               │
├─────────────────────────────────────────────────────────────┤
│  基础设施成本 ████ 5-10%                                   │
│  - 计算                                                   │
│  - 存储                                                   │
│  - 网络                                                   │
└─────────────────────────────────────────────────────────────┘
```

### 提供商价格对比（2026）

| 提供商 | 模型 | 输入 ($/M) | 输出 ($/M) | 相对成本 |
|--------|------|-----------|-----------|----------|
| OpenAI | GPT-4o | $5.00 | $15.00 | 1.0x (基准) |
| Anthropic | Claude 3.5 Sonnet | $3.00 | $15.00 | 0.9x |
| DeepSeek | DeepSeek-V3 | $1.00 | $2.00 | 0.25x |
| Groq | Llama 3.3 70B | $0.59 | $0.79 | 0.1x |
| SiliconFlow | Qwen 2.5 72B | $0.50 | $0.50 | 0.08x |

---

## 🎯 成本优化策略

### 1. 智能路由

使用 SquillaRouter 自动选择最优模型：

```yaml
router:
  enabled: true
  strategy: "cost_optimized"  # quality | speed | cost_optimized

  rules:
    # 简单任务 → 便宜模型
    - condition: "complexity < 3"
      provider: groq
      model: llama-3.1-8b-instant

    # 中等任务 → 中档模型
    - condition: "complexity >= 3 AND complexity < 7"
      provider: deepseek
      model: deepseek-chat

    # 复杂任务 → 高级模型
    - condition: "complexity >= 7"
      provider: openai
      model: gpt-4o

    # 代码任务 → 专业模型
    - condition: "task_type == 'coding'"
      provider: anthropic
      model: claude-3-5-sonnet-20250114
```

### 2. Token 预算管理

```yaml
budget:
  enabled: true

  # 全局预算
  global:
    daily_limit: 100  # 美元
    monthly_limit: 2000

  # 租户预算
  per_tenant:
    default:
      daily_limit: 10
      monthly_limit: 200

    premium:
      daily_limit: 100
      monthly_limit: 2000

  # 用户预算
  per_user:
    default:
      daily_limit: 1
      request_limit: 100

  # 超限处理
  over_limit:
    action: "throttle"  # block | throttle | alert
    throttle_rate: 0.1
```

### 3. 上下文压缩

```yaml
context:
  # 自动压缩
  compression:
    enabled: true
    threshold: 8000  # 超过此 Token 数触发压缩

    strategy: "semantic"  # semantic | recent | summary

    # 语义压缩（保留关键信息）
    semantic:
      keep_first: 1000
      keep_last: 1000
      summarize_middle: true

  # Token 预算分配
  budgeting:
    system: 500
    history: 2000
    retrieval: 3000
    user_input: 1000
    output: 2000
```

### 4. 缓存策略

```yaml
cache:
  # 语义缓存
  semantic:
    enabled: true
    similarity_threshold: 0.95
    max_entries: 10000
    ttl: 86400

  # 提示词缓存
  prompts:
    enabled: true
    cache_system_prompt: true
    cache_skill_templates: true

  # 嵌入缓存
  embeddings:
    enabled: true
    cache_size: 100000
```

### 5. 批量处理

```bash
# 批量请求
opensquilla batch run \
  --input-file queries.txt \
  --batch-size 10 \
  --concurrency 5 \
  --provider groq \
  --model llama-3.1-8b-instant
```

---

## 📊 成本监控

### 实时监控

```yaml
monitoring:
  # Prometheus 指标
  metrics:
    - name: "opensquilla_tokens_total"
      type: counter
      labels: ["provider", "model", "tenant_id", "user_id"]

    - name: "opensquilla_cost_total"
      type: gauge
      labels: ["provider", "model", "tenant_id"]

    - name: "opensquilla_budget_utilization"
      type: gauge
      labels: ["tenant_id", "user_id"]

  # 告警规则
  alerts:
    - name: "HighCostRate"
      condition: "rate(opensquilla_cost_total[5m]) > 1"
      severity: warning

    - name: "BudgetExceeded"
      condition: "opensquilla_budget_utilization > 1"
      severity: critical

    - name: "UnusualUsage"
      condition: "rate(opensquilla_tokens_total[1h]) > 10000"
      severity: warning
```

### 成本分析

```bash
# 查看实时成本
opensquilla cost current

# 查看历史成本
opensquilla cost history --since "2025-01-01" --group-by tenant

# 成本预测
opensquilla cost forecast --days 30

# 成本分解
opensquilla cost breakdown --by provider,model,tenant
```

### 成本报告

```bash
# 生成日报
opensquilla cost report --period daily --output cost-daily.pdf

# 生成月报
opensquilla cost report --period monthly --output cost-monthly.pdf

# 发送邮件
opensquilla cost report \
  --period monthly \
  --email finance@company.com \
  --subject "OpenSquilla 月度成本报告"
```

---

## 🎛️ 成本控制

### 配额管理

```yaml
quotas:
  # Token 配额
  tokens:
    daily: 1000000
    weekly: 5000000
    monthly: 20000000

  # 请求配额
  requests:
    per_minute: 100
    per_hour: 5000
    per_day: 50000

  # 并发配额
  concurrency:
    max_concurrent_requests: 50
    max_concurrent_sessions: 100

  # 租户配额
  per_tenant:
    free_tier:
      tokens_daily: 100000
      requests_daily: 100

    standard_tier:
      tokens_daily: 1000000
      requests_daily: 1000

    enterprise_tier:
      unlimited: true
```

### 速率限制

```yaml
rate_limiting:
  # 租户级别
  per_tenant:
    default:
      requests_per_second: 10
      tokens_per_second: 10000

    premium:
      requests_per_second: 100
      tokens_per_second: 100000

  # 用户级别
  per_user:
    requests_per_minute: 60
    tokens_per_minute: 10000

  # API Key 级别
  per_api_key:
    requests_per_day: 10000
    tokens_per_day: 1000000
```

---

## 🧪 成本优化实验

### A/B 测试

```bash
# 测试不同模型的成本效果
opensquilla cost test \
  --task "客服问答" \
  --models "gpt-4o,claude-3-5-sonnet,deepseek-chat" \
  --test-questions questions.txt \
  --measure cost,quality,latency
```

### 成本模拟

```bash
# 模拟成本
opensquilla cost simulate \
  --scenario "增加 1000 用户" \
  --current-usage 10000000 \
  --growth-rate 2 \
  --period 90
```

---

## 📈 成本优化案例

### 案例 1：智能路由节省 40%

```yaml
# 优化前
全部使用 GPT-4o
月成本：$10,000

# 优化后
简单任务 (60%) → Groq Llama 8B    $100
中等任务 (30%) → DeepSeek-V3      $600
复杂任务 (10%) → GPT-4o           $1000
月成本：$1,700
节省：83%
```

### 案例 2：缓存节省 25%

```yaml
# 优化前
每次请求重新计算
重复请求率：40%
月成本：$10,000

# 优化后
语义缓存命中率：35%
月成本：$7,500
节省：25%
```

### 案例 3：上下文压缩节省 30%

```yaml
# 优化前
完整上下文传递
平均 Token：8000
月成本：$10,000

# 优化后
压缩上下文
平均 Token：5000
月成本：$7,000
节省：30%
```

---

## 🔧 工具和命令

### 成本相关命令

```bash
# 查看当前成本
opensquilla cost show

# 设置预算
opensquilla budget set --tenant tenant-a --daily 100

# 查看配额
opensquilla quota show

# 测试路由
opensquilla router test --query "测试问题"

# 优化建议
opensquilla cost analyze --suggest
```

### 成本可视化

```bash
# Grafana 仪表板
opensquilla dashboard export cost > cost-dashboard.json

# 成本趋势图
curl -X GET "http://localhost:18791/api/cost/trend?days=30"

# 成本分布图
curl -X GET "http://localhost:18791/api/cost/distribution"
```

---

## 💡 最佳实践

### 1. 分层策略

```
简单任务   → 超低成本模型  (Groq/SiliconFlow)
  ↓
中等任务   → 中等成本模型  (DeepSeek/Qwen)
  ↓
复杂任务   → 高级模型      (GPT-4o/Claude)
  ↓
专业任务   → 专业模型      (Claude 代码/GPT-4o 视觉)
```

### 2. 预算规划

- **测试环境**：使用免费/低成本模型
- **开发环境**：使用中档模型
- **生产环境**：根据任务复杂度选择

### 3. 监控告警

- 设置成本告警阈值
- 每日成本报告
- 异常使用检测

### 4. 定期审查

- 每月审查成本报告
- 分析高成本租户/用户
- 优化低效查询

---

## 🔗 相关资源

- [企业监控指南](../enterprise/monitoring.md)
- [SquillaRouter 配置](../configuration/router.md)
- [提供商价格](../providers/README.md)
- [性能优化](../performance/index.md)
