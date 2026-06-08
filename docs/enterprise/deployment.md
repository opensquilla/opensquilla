# 企业级部署指南

本指南帮助企业在生产环境中部署和管理 OpenSquilla，涵盖多租户、权限管理、审计合规等企业级需求。

## 🏗️ 架构概览

### 企业部署架构

```
┌─────────────────────────────────────────────────────────────┐
│                        负载均衡层                            │
│                    (Nginx/HAProxy/ALB)                     │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    OpenSquilla 网关集群                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Gateway  │  │ Gateway  │  │ Gateway  │  │ Gateway  │   │
│  │   #1     │  │   #2     │  │   #3     │  │   #4     │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      共享存储层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ PostgreSQL│  │   Redis  │  │  Vector  │  │   S3     │   │
│  │  (元数据) │  │  (缓存)  │  │   DB     │  │ (文件)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      LLM 提供商层                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ OpenAI   │  │Anthropic │  │  Azure   │  │  本地    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 👥 多租户配置

### 租户隔离策略

OpenSquilla 支持以下隔离级别：

| 隔离级别 | 范围 | 适用场景 |
|---------|------|----------|
| **完全隔离** | 独立网关实例 | 大企业、安全要求高 |
| **逻辑隔离** | 共享网关，租户标识 | 中小企业、成本敏感 |
| **混合模式** | 核心租户隔离，其他共享 | 混合场景 |

### 逻辑隔离配置

```bash
# 创建租户配置文件
mkdir -p /etc/opensquilla/tenants

# 租户 A 配置
cat > /etc/opensquilla/tenants/tenant-a.yaml <<EOF
tenant_id: "tenant-a"
name: "Company A"
provider:
  type: "openai"
  api_key_env: "TENANT_A_OPENAI_KEY"
  model: "gpt-4o"
quotas:
  max_tokens_per_day: 1000000
  max_requests_per_minute: 100
features:
  memory: true
  search: true
  mcp_servers:
    - github
    - filesystem
restrictions:
  allowed_domains:
    - "*.company-a.com"
  denied_tools:
    - shell_execute
EOF

# 租户 B 配置
cat > /etc/opensquilla/tenants/tenant-b.yaml <<EOF
tenant_id: "tenant-b"
name: "Company B"
provider:
  type: "anthropic"
  api_key_env: "TENANT_B_ANTHROPIC_KEY"
  model: "claude-3-5-sonnet-20250114"
quotas:
  max_tokens_per_day: 500000
  max_requests_per_minute: 50
EOF
```

### 租户路由配置

```bash
# 启用租户路由
opensquilla configure gateway \
  --tenant-mode multi-tenant \
  --tenant-header "X-Tenant-ID" \
  --tenant-config-path "/etc/opensquilla/tenants"
```

---

## 🔐 权限管理

### RBAC 权限模型

```
┌─────────────────────────────────────────────────────────────┐
│                           角色                               │
├─────────────────────────────────────────────────────────────┤
│  管理员 (admin)   │ 运维管理员 (ops)   │ 用户 (user)         │
│  - 所有权限       │  - 网关管理        │  - 基础对话         │
│  - 租户管理       │  - 监控查看        │  - 技能使用         │
│  - 用户管理       │  - 日志查看        │  - 历史记录         │
│                   │                    │                     │
│  开发者 (dev)     │ 审计员 (audit)     │                     │
│  - 技能开发       │  - 只读日志        │                     │
│  - MCP 配置       │  - 合规检查        │                     │
│  - 测试调试       │                    │                     │
└─────────────────────────────────────────────────────────────┘
```

### 权限配置

```yaml
# /etc/opensquilla/permissions/rbac.yaml
roles:
  admin:
    permissions:
      - "tenant:*"
      - "user:*"
      - "gateway:*"
      - "skill:*"
      - "mcp:*"
      - "log:*"

  ops:
    permissions:
      - "gateway:read"
      - "gateway:start"
      - "gateway:stop"
      - "gateway:restart"
      - "log:read"
      - "metrics:read"

  user:
    permissions:
      - "chat:*"
      - "agent:run"
      - "skill:use"
      - "session:read"

  dev:
    permissions:
      - "skill:*"
      - "mcp:*"
      - "agent:test"
      - "log:read"

  audit:
    permissions:
      - "log:read"
      - "tenant:read"
      - "user:read"
      - "compliance:check"

users:
  - username: "admin@company.com"
    roles: ["admin"]
    tenant_id: "tenant-a"

  - username: "ops@company.com"
    roles: ["ops"]
    tenant_id: "tenant-a"

  - username: "dev@company.com"
    roles: ["dev"]
    tenant_id: "tenant-a"
```

### 应用权限配置

```bash
opensquilla configure auth \
  --type rbac \
  --config-file /etc/opensquilla/permissions/rbac.yaml \
  --default-role user
```

---

## 📝 审计日志

### 日志配置

```yaml
# /etc/opensquilla/logging/audit.yaml
audit:
  enabled: true
  level: "INFO"
  output:
    - type: "file"
      path: "/var/log/opensquilla/audit.log"
      rotation: "daily"
      retention: 90
    - type: "syslog"
      facility: "local0"
    - type: "elasticsearch"
      hosts: ["https://elasticsearch.internal:9200"]
      index: "opensquilla-audit"

  events:
    - "user.login"
    - "user.logout"
    - "agent.run"
    - "tool.use"
    - "file.read"
    - "file.write"
    - "api.call"
    - "error"
    - "permission.denied"

  fields:
    - "timestamp"
    - "tenant_id"
    - "user_id"
    - "session_id"
    - "event_type"
    - "resource"
    - "result"
    - "duration_ms"
    - "ip_address"
    - "user_agent"
```

### 启用审计

```bash
opensquilla configure logging \
  --audit-config /etc/opensquilla/logging/audit.yaml \
  --audit-format json
```

### 审计查询

```bash
# 查询用户活动
opensquilla audit query --user "user@company.com" --since "2025-01-01"

# 查询敏感操作
opensquilla audit query --events "file.write,api.call" --tenant "tenant-a"

# 导出审计报告
opensquilla audit export \
  --since "2025-01-01" \
  --format csv \
  --output /tmp/audit_report.csv
```

---

## 🛡️ 安全合规

### 数据脱敏

```yaml
# /etc/opensquilla/security/masking.yaml
masking:
  enabled: true
  rules:
    - name: "PII - Email"
      pattern: "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b"
      replacement: "***@***.***"

    - name: "PII - Phone"
      pattern: "\\b\\d{3}-?\\d{3}-?\\d{4}\\b"
      replacement: "***-***-****"

    - name: "PII - SSN"
      pattern: "\\b\\d{3}-?\\d{2}-?\\d{4}\\b"
      replacement: "***-**-****"

    - name: "API Key"
      pattern: "\\b(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36,})\\b"
      replacement: "***REDACTED***"

    - name: "Credit Card"
      pattern: "\\b\\d{4}[ -]?\\d{4}[ -]?\\d{4}[ -]?\\d{4}\\b"
      replacement: "****-****-****-****"

  apply_to:
    - "logs"
    - "audit"
    - "responses"
    - "memory"
```

### 敏感词过滤

```yaml
# /etc/opensquilla/security/content-filter.yaml
content_filter:
  enabled: true
  mode: "block"  # block | warn | log

  categories:
    - name: "profanity"
      dictionary: "/etc/opensquilla/security/profanity.txt"
      action: "warn"

    - name: "hate_speech"
      dictionary: "/etc/opensquilla/security/hate_speech.txt"
      action: "block"

    - name: "proprietary_info"
      patterns:
        - "\\bConfidential\\b"
        - "\\bInternal Only\\b"
        - "\\bDo Not Distribute\\b"
      action: "block"

    - name: "competitor"
      keywords:
        - "CompetitorA"
        - "CompetitorB"
      action: "log"
```

---

## 📊 SLA 监控

### SLA 定义

```yaml
# /etc/opensquilla/sla/service-levels.yaml
sla:
  availability:
    target: 99.9%
    measurement: "monthly"

  performance:
    p50_latency: 500ms
    p95_latency: 2000ms
    p99_latency: 5000ms

  capacity:
    max_concurrent_requests: 1000
    queue_size: 100

  recovery:
    max_downtime: "1h"
    recovery_time_objective: "15m"
```

### 监控配置

```bash
# 启用 SLA 监控
opensquilla configure sla \
  --config-file /etc/opensquilla/sla/service-levels.yaml \
  --alert-threshold 95

# 配置告警
opensquilla configure alerts \
  --type slack \
  --webhook "https://hooks.slack.com/services/..." \
  --alerts "availability,performance,capacity"
```

---

## 🚀 生产部署清单

### 部署前检查

- [ ] 多租户配置已验证
- [ ] RBAC 权限已测试
- [ ] 审计日志已启用
- [ ] 数据脱敏已配置
- [ ] SLA 监控已设置
- [ ] 备份策略已制定
- [ ] 灾难恢复已测试
- [ ] 安全扫描已完成
- [ ] 性能基准已建立
- [ ] 文档已更新

### 生产配置

```bash
# 生产模式启动
opensquilla gateway run \
  --mode production \
  --workers 4 \
  --port 18791 \
  --log-level WARNING \
  --audit-enabled \
  --sla-enabled

# 或使用 systemd
sudo systemctl start opensquilla-gateway
sudo systemctl enable opensquilla-gateway
```

### systemd 服务配置

```ini
# /etc/systemd/system/opensquilla-gateway.service
[Unit]
Description=OpenSquilla Gateway
After=network.target

[Service]
Type=notify
User=opensquilla
Group=opensquilla
WorkingDirectory=/opt/opensquilla
Environment="PATH=/opt/opensquilla/venv/bin"
Environment="OPENSQUILLA_CONFIG=/etc/opensquilla/config.yaml"
Environment="OPENSQUILLA_MODE=production"
ExecStart=/opt/opensquilla/venv/bin/opensquilla gateway run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 🔄 备份与恢复

### 备份策略

```bash
# 每日备份脚本
cat > /etc/cron.daily/opensquilla-backup.sh <<'EOF'
#!/bin/bash
BACKUP_DIR="/backup/opensquilla/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# 备份配置
tar -czf "$BACKUP_DIR/config.tar.gz" /etc/opensquilla

# 备份数据库
pg_dump opensquilla > "$BACKUP_DIR/database.sql"

# 备份向量数据
curl -X POST "http://localhost:18791/admin/backup/vector" \
  -o "$BACKUP_DIR/vectors.tar.gz"

# 上传到 S3
aws s3 sync "$BACKUP_DIR" s3://company-backups/opensquilla/$(date +%Y%m%d)/

# 清理 30 天前的备份
find /backup/opensquilla -type d -mtime +30 -exec rm -rf {} \;
EOF

chmod +x /etc/cron.daily/opensquilla-backup.sh
```

### 恢复流程

```bash
# 1. 停止服务
systemctl stop opensquilla-gateway

# 2. 恢复配置
tar -xzf /backup/opensquilla/20250101/config.tar.gz -C /

# 3. 恢复数据库
psql opensquilla < /backup/opensquilla/20250101/database.sql

# 4. 恢复向量数据
curl -X POST "http://localhost:18791/admin/restore/vector" \
  -F "file=@/backup/opensquilla/20250101/vectors.tar.gz"

# 5. 启动服务
systemctl start opensquilla-gateway
```

---

## 🧪 测试与验证

### 压力测试

```bash
# 使用 hey 进行压力测试
hey -n 10000 -c 100 -m POST \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: tenant-a" \
  -d '{"message": "测试消息"}' \
  http://localhost:18791/api/agent

# 检查 SLA 合规性
opensquilla sla check --threshold 95
```

### 安全测试

```bash
# 权限测试
opensquilla security test-permissions \
  --user "test@example.com" \
  --tenant "tenant-a"

# 数据脱敏测试
opensquilla security test-masking \
  --input "john@example.com called 555-123-4567"

# 内容过滤测试
opensquilla security test-filter \
  --input "测试敏感内容"
```

---

## 📞 企业支持

### 支持等级

| 等级 | 响应时间 | 可用性 | 包含服务 |
|------|---------|--------|----------|
| **Basic** | 48 小时 | 最佳努力 | 社区支持 |
| **Business** | 24 小时 | 99.5% SLA | 邮件支持 |
| **Enterprise** | 4 小时 | 99.9% SLA | 专属支持 + 现场 |

### 联系方式

- 📧 邮件：enterprise@opensquilla.ai
- 💬 Slack：join.opensquilla.ai
- 📞 电话：+1 (888) OPEN-SQUILLA

---

## 相关资源

- [安全指南](./security.md)
- [监控指南](./monitoring.md)
- [备份策略](./backup.md)
- [故障排查](../troubleshooting.md)
