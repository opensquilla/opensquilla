# 企业监控与告警指南

本指南介绍如何在生产环境中监控 OpenSquilla，包括指标采集、告警配置、性能分析等。

## 📊 监控架构

```
┌─────────────────────────────────────────────────────────────┐
│                      OpenSquilla Gateway                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Metrics Exporter (Prometheus)                          │ │
│  │  Log Forwarder (Loki/ELK)                              │ │
│  │  Trace Exporter (Jaeger)                               │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    可观测性平台                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Prometheus   │  │   Grafana    │  │   AlertMgr   │      │
│  │ (Metrics)    │  │ (Dashboard)  │  │  (Alerts)    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │     Loki     │  │     ELK      │  │   Jaeger     │      │
│  │   (Logs)     │  │  (Logs/Audit)│  │  (Traces)    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

---

## 📈 核心指标

### 业务指标

| 指标 | 类型 | 说明 |
|------|------|------|
| `opensquilla_requests_total` | Counter | 总请求数 |
| `opensquilla_requests_duration_seconds` | Histogram | 请求延迟 |
| `opensquilla_tokens_total` | Counter | 总 Token 数 |
| `opensquilla_tokens_cost` | Gauge | Token 成本 |
| `opensquilla_agent_iterations_total` | Counter | Agent 迭代次数 |
| `opensquilla_tool_calls_total` | Counter | 工具调用次数 |

### 系统指标

| 指标 | 类型 | 说明 |
|------|------|------|
| `opensquilla_memory_usage_bytes` | Gauge | 内存使用 |
| `opensquilla_cpu_usage_percent` | Gauge | CPU 使用率 |
| `opensquilla_goroutines_count` | Gauge | 协程数量 |
| `opensquilla_queue_size` | Gauge | 请求队列长度 |
| `opensquilla_db_connections_active` | Gauge | 数据库连接数 |

### LLM 指标

| 指标 | 类型 | 说明 |
|------|------|------|
| `opensquilla_llm_requests_total` | Counter | LLM 请求数 |
| `opensquilla_llm_requests_duration_seconds` | Histogram | LLM 请求延迟 |
| `opensquilla_llm_errors_total` | Counter | LLM 错误数 |
| `opensquilla_llm_rate_limit_hits` | Counter | 速率限制命中数 |

### 安全指标

| 指标 | 类型 | 说明 |
|------|------|------|
| `opensquilla_auth_failures_total` | Counter | 认证失败数 |
| `opensquilla_permission_denials_total` | Counter | 权限拒绝数 |
| `opensquilla_security_alerts_total` | Counter | 安全告警数 |

---

## 🔧 Prometheus 配置

### Scrape 配置

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'opensquilla'
    static_configs:
      - targets: ['localhost:18791']
    scrape_interval: 15s
    scrape_timeout: 10s
    metrics_path: '/metrics'

    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        replacement: 'opensquilla-prod'
```

### Exporter 配置

```bash
# 启用 Prometheus exporter
opensquilla configure monitoring \
  --type prometheus \
  --port 18791 \
  --path /metrics
```

---

## 📊 Grafana 仪表板

### 仪表板配置

```json
{
  "dashboard": {
    "title": "OpenSquilla Overview",
    "panels": [
      {
        "title": "Request Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(opensquilla_requests_total[5m])",
            "legendFormat": "{{tenant_id}}"
          }
        ]
      },
      {
        "title": "Request Duration",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(opensquilla_requests_duration_seconds_bucket[5m]))",
            "legendFormat": "p95"
          },
          {
            "expr": "histogram_quantile(0.50, rate(opensquilla_requests_duration_seconds_bucket[5m]))",
            "legendFormat": "p50"
          }
        ]
      },
      {
        "title": "Token Usage",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(opensquilla_tokens_total[1h])",
            "legendFormat": "{{provider}}"
          }
        ]
      },
      {
        "title": "Error Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(opensquilla_llm_errors_total[5m]) / rate(opensquilla_llm_requests_total[5m])",
            "legendFormat": "Error Rate"
          }
        ]
      },
      {
        "title": "Active Sessions",
        "type": "stat",
        "targets": [
          {
            "expr": "opensquilla_sessions_active"
          }
        ]
      },
      {
        "title": "Cost per Hour",
        "type": "graph",
        "targets": [
          {
            "expr": "increase(opensquilla_tokens_cost[1h])",
            "legendFormat": "{{tenant_id}}"
          }
        ]
      }
    ]
  }
}
```

### 导入仪表板

```bash
# 导入示例仪表板
opensquilla dashboard export --format grafana > opensquilla-dashboard.json

# 或使用内置仪表板
curl -X POST http://grafana:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @opensquilla-dashboard.json
```

---

## 🚨 告警配置

### AlertManager 规则

```yaml
# /etc/prometheus/alerts/opensquilla.yml
groups:
  - name: opensquilla_alerts
    interval: 30s
    rules:
      # 可用性告警
      - alert: OpenSquillaDown
        expr: up{job="opensquilla"} == 0
        for: 1m
        labels:
          severity: critical
          team: ops
        annotations:
          summary: "OpenSquilla gateway is down"
          description: "Instance {{ $labels.instance }} has been down for more than 1 minute."

      # 性能告警
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(opensquilla_requests_duration_seconds_bucket[5m])) > 5
        for: 5m
        labels:
          severity: warning
          team: ops
        annotations:
          summary: "High request latency detected"
          description: "P95 latency is {{ $value }}s for tenant {{ $labels.tenant_id }}"

      # 错误率告警
      - alert: HighErrorRate
        expr: rate(opensquilla_llm_errors_total[5m]) / rate(opensquilla_llm_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
          team: ops
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value | humanizePercentage }} for provider {{ $labels.provider }}"

      # 速率限制告警
      - alert: RateLimitHits
        expr: rate(opensquilla_llm_rate_limit_hits[5m]) > 10
        for: 5m
        labels:
          severity: info
          team: ops
        annotations:
          summary: "Rate limit being hit frequently"
          description: "{{ $value }} rate limit hits per second"

      # 成本告警
      - alert: HighTokenCost
        expr: increase(opensquilla_tokens_cost[1h]) > 100
        for: 1h
        labels:
          severity: warning
          team: finance
        annotations:
          summary: "High token cost detected"
          description: "{{ $labels.tenant_id }} spent ${{ $value }} in the last hour"

      # 安全告警
      - alert: AuthenticationFailures
        expr: rate(opensquilla_auth_failures_total[5m]) > 10
        for: 2m
        labels:
          severity: warning
          team: security
        annotations:
          summary: "High authentication failure rate"
          description: "{{ $value }} failed auth attempts per second"

      - alert: PermissionDenials
        expr: rate(opensquilla_permission_denials_total[5m]) > 5
        for: 5m
        labels:
          severity: warning
          team: security
        annotations:
          summary: "High permission denial rate"
          description: "{{ $value }} denied requests per second"

      # 资源告警
      - alert: HighMemoryUsage
        expr: opensquilla_memory_usage_bytes / opensquilla_memory_limit_bytes > 0.9
        for: 5m
        labels:
          severity: warning
          team: ops
        annotations:
          summary: "High memory usage"
          description: "Memory usage is {{ $value | humanizePercentage }}"

      - alert: HighQueueDepth
        expr: opensquilla_queue_size > 100
        for: 5m
        labels:
          severity: warning
          team: ops
        annotations:
          summary: "High request queue depth"
          description: "{{ $value }} requests waiting in queue"
```

### 告警通知配置

```yaml
# /etc/alertmanager/alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'default'

  routes:
    - match:
        severity: critical
      receiver: 'critical'
      continue: true

    - match:
        severity: warning
      receiver: 'warnings'

    - match:
        team: ops
      receiver: 'ops-team'

    - match:
        team: security
      receiver: 'security-team'

    - match:
        team: finance
      receiver: 'finance-team'

receivers:
  - name: 'default'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_URL}'
        channel: '#alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'

  - name: 'critical'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_CRITICAL}'
        channel: '#critical-alerts'
        color: 'danger'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_SERVICE_KEY}'

  - name: 'warnings'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_URL}'
        channel: '#warnings'
        color: 'warning'

  - name: 'ops-team'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_OPS}'
        channel: '#ops-alerts'

  - name: 'security-team'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_SECURITY}'
        channel: '#security-alerts'
    email_configs:
      - to: 'security@company.com'
        send_resolved: true

  - name: 'finance-team'
    email_configs:
      - to: 'finance@company.com'
        send_resolved: true
```

---

## 🔍 日志监控

### Loki 配置

```yaml
# /etc/loki/local-config.yaml
clients:
  - url: http://localhost:3100/loki/api/v1/push

scrape_configs:
  - job_name: opensquilla
    static_configs:
      - targets:
          - localhost
        labels:
          job: opensquilla
          env: production

    pipeline_stages:
      - json:
          expressions:
            level: level
            tenant_id: tenant_id
            user_id: user_id
            trace_id: trace_id

      - labels:
          level:
          tenant_id:
          user_id:

      - output:
          source: output
```

### 日志查询示例

```bash
# 查询错误日志
{job="opensquilla"} |= "ERROR"

# 查询特定租户的日志
{job="opensquilla", tenant_id="tenant-a"}

# 查询慢请求
{job="opensquilla"} |= "duration_ms" | line_format "{{.duration_ms}} > 1000"

# 统计错误率
count_over_time({job="opensquilla"} |= "ERROR" [5m])
```

---

## 🔗 分布式追踪

### Jaeger 配置

```yaml
# /etc/opensquilla/tracing/jaeger.yaml
tracing:
  enabled: true
  type: jaeger
  endpoint: "http://jaeger:14268/api/traces"
  sampler_type: "probabilistic"
  sampler_param: 0.1  # 10% 采样

  spans:
    - "http.request"
    - "llm.request"
    - "tool.call"
    - "db.query"
```

### 追踪查询

```bash
# 查询特定 trace
curl -X GET "http://jaeger:16686/api/traces/{trace-id}"

# 查询服务的 traces
curl -X GET "http://jaeger:16686/api/traces?service=opensquilla&limit=20"

# 查询慢请求的 traces
curl -X GET "http://jaeger:16686/api/traces?service=opensquilla&lookback=1h&minDuration=1000000"
```

---

## 📉 性能分析

### Profile 采集

```bash
# 启动性能分析
opensquilla profile start --duration 30s --output /tmp/cpu-profile.pprof

# 分析性能
go tool pprof -http=:8080 /tmp/cpu-profile.pprof

# 火焰图
go tool pprof -http=:8080 -raw -output /tmp/flamegraph.svg /tmp/cpu-profile.pprof
```

### 内存分析

```bash
# 内存快照
opensquilla profile memory --output /tmp/memory-profile.pprof

# 分析内存
go tool pprof -http=:8080 /tmp/memory-profile.pprof
```

---

## 🔧 故障排查

### 常见问题诊断

```bash
# 检查服务健康
opensquilla health --verbose

# 检查最近错误
opensquilla logs --level ERROR --since "1h ago"

# 检查性能指标
opensquilla metrics --format prometheus | grep "opensquilla_.*_seconds"

# 检查依赖
opensquilla doctor --include-dependencies
```

### 性能调优

```bash
# 查看当前配置
opensquilla config show

# 调整并发
opensquilla configure gateway --workers 8 --queue-size 200

# 调整超时
opensquilla configure agent --timeout 300 --request-timeout 30

# 启用缓存
opensquilla configure cache --enable --ttl 3600
```

---

## 📞 监控联系

| 级别 | 联系方式 | 响应时间 |
|------|---------|---------|
| P0 | PagerDuty + 电话 | 15 分钟 |
| P1 | Slack #critical | 1 小时 |
| P2 | Slack #ops-alerts | 4 小时 |
| P3 | Email ops@company.com | 1 工作日 |

---

## 相关资源

- [企业部署指南](./deployment.md)
- [安全指南](./security.md)
- [审计日志](../logging/audit.md)
- [告警最佳实践](../monitoring/alerting.md)
