# 企业安全指南

本指南涵盖 OpenSquilla 在企业环境中的安全最佳实践，包括数据保护、访问控制、合规要求等。

## 🔐 安全架构

### 安全分层

```
┌─────────────────────────────────────────────────────────────┐
│                   应用安全层                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  身份认证 (OAuth2/SAML/LDAP)                            │ │
│  │  授权 (RBAC/ABAC)                                       │ │
│  │  审计日志                                               │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                   数据安全层                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  加密 (TLS/AES-256)                                     │ │
│  │  脱敏 (PII/敏感数据)                                     │ │
│  │  DLP (数据泄露防护)                                      │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                   网络安全层                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  防火墙规则                                             │ │
│  │  VPC 隔离                                              │ │
│  │  DDoS 防护                                             │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛡️ 身份认证

### SSO 集成

#### SAML 2.0 集成

```yaml
# /etc/opensquilla/auth/saml.yaml
saml:
  enabled: true
  idp_metadata_url: "https://idp.company.com/metadata"
  sp_entity_id: "https://opensquilla.company.com"
  sp_acs_url: "https://opensquilla.company.com/saml/acs"
  sp_sls_url: "https://opensquilla.company.com/saml/sls"

  attributes:
    email: "emailAddress"
    first_name: "firstName"
    last_name: "lastName"
    groups: "groups"

  role_mapping:
    "opensquilla-admins": "admin"
    "opensquilla-ops": "ops"
    "opensquilla-users": "user"
```

#### OAuth 2.0 / OpenID Connect

```yaml
# /etc/opensquilla/auth/oauth.yaml
oauth:
  enabled: true
  provider: "azure-ad"  # azure-ad | google | okta

  client_id: "your-client-id"
  client_secret: "${OAUTH_CLIENT_SECRET}"
  redirect_uri: "https://opensquilla.company.com/oauth/callback"

  scopes:
    - "openid"
    - "profile"
    - "email"

  issuer: "https://login.microsoftonline.com/{tenant-id}/v2.0"
  jwks_uri: "https://login.microsoftonline.com/{tenant-id}/discovery/v2.0/keys"
```

#### LDAP 集成

```yaml
# /etc/opensquilla/auth/ldap.yaml
ldap:
  enabled: true
  url: "ldap://ldap.company.com:389"
  bind_dn: "cn=admin,dc=company,dc=com"
  bind_password: "${LDAP_BIND_PASSWORD}"

  user_search:
    base_dn: "ou=users,dc=company,dc=com"
    filter: "(uid={username})"
    attributes:
      - "uid"
      - "mail"
      - "cn"
      - "memberOf"

  group_search:
    base_dn: "ou=groups,dc=company,dc=com"
    filter: "(member={user_dn})"
```

### 应用认证配置

```bash
opensquilla configure auth \
  --type saml \
  --config-file /etc/opensquilla/auth/saml.yaml
```

---

## 🔐 数据保护

### 加密配置

```yaml
# /etc/opensquilla/security/encryption.yaml
encryption:
  # 传输加密
  tls:
    enabled: true
    min_version: "TLSv1.3"
    ciphers:
      - "TLS_AES_256_GCM_SHA384"
      - "TLS_CHACHA20_POLY1305_SHA256"
    certificates:
      cert: "/etc/opensquilla/certs/server.crt"
      key: "/etc/opensquilla/certs/server.key"
      ca: "/etc/opensquilla/certs/ca.crt"

  # 静态加密
  at_rest:
    algorithm: "AES-256-GCM"
    key_source: "vault"  # env | vault | kms
    key_id: "opensquilla-master-key"

  # API 密钥加密
  api_keys:
    encryption_key: "${API_ENCRYPTION_KEY}"
    rotation_days: 90
```

### 敏感数据保护

```yaml
# /etc/opensquilla/security/data-protection.yaml
data_protection:
  # PII 检测和脱敏
  pii_detection:
    enabled: true
    types:
      - "email"
      - "phone"
      - "ssn"
      - "credit_card"
      - "ip_address"
      - "bank_account"

    action: "mask"  # mask | redact | hash

  # DLP 规则
  dlp_rules:
    - name: "Confidential Documents"
      pattern: "\\b(C|Confidential|Internal Only|Proprietary)\\b"
      action: "alert"

    - name: "Source Code"
      pattern: "(function|class|def |public |private ).*\\{"
      action: "log"

  # 数据分类
  classification:
    public:
      handling: "none"
    internal:
      handling: "log"
    confidential:
      handling: "encrypt"
    restricted:
      handling: "block"
```

---

## 🚦 访问控制

### IP 白名单

```yaml
# /etc/opensquilla/security/access-control.yaml
access_control:
  ip_whitelist:
    enabled: true
    default: "deny"

    rules:
      - cidr: "10.0.0.0/8"
        action: "allow"
        description: "Internal network"

      - cidr: "203.0.113.0/24"
        action: "allow"
        description: "Partner network"

      - cidr: "0.0.0.0/0"
        action: "deny"
        description: "Default deny"

  geo_fencing:
    enabled: true
    allowed_countries:
      - "US"
      - "UK"
      - "DE"
      - "JP"
      - "CN"
    action: "deny"
```

### 速率限制

```yaml
# /etc/opensquilla/security/rate-limiting.yaml
rate_limiting:
  # 全局限制
  global:
    requests_per_second: 1000
    burst: 100

  # 租户限制
  per_tenant:
    default:
      requests_per_minute: 100
      tokens_per_minute: 100000

    premium:
      requests_per_minute: 1000
      tokens_per_minute: 1000000

  # 用户限制
  per_user:
    requests_per_minute: 60
    concurrent_requests: 5

  # API 密钥限制
  per_api_key:
    requests_per_day: 10000
    tokens_per_day: 10000000
```

---

## 🔍 安全监控

### 入侵检测

```yaml
# /etc/opensquilla/security/intrusion-detection.yaml
intrusion_detection:
  # 异常检测
  anomaly_detection:
    enabled: true
    metrics:
      - "login_failures"
      - "api_errors"
      - "unusual_tools"
      - "data_exfiltration"

    threshold: 3  # 标准差倍数
    action: "alert"

  # 威胁规则
  threat_rules:
    - name: "Brute Force Attack"
      condition: "login_failures > 10 in 1m"
      action: "block_ip"

    - name: "Data Exfiltration"
      condition: "outbound_bytes > 1GB in 5m"
      action: "alert_and_block"

    - name: "Privilege Escalation"
      condition: "user_role_changed AND NOT approved"
      action: "alert"

  # 安全事件响应
  incident_response:
    auto_block: true
    notification:
      - type: "slack"
        webhook: "${SECURITY_SLACK_WEBHOOK}"
      - type: "email"
        recipients: ["security@company.com"]
```

### 合规审计

```bash
# 生成合规报告
opensquilla compliance report \
  --framework iso27001 \
  --output /tmp/compliance_report.pdf

# 检查 GDPR 合规性
opensquilla compliance check \
  --framework gdpr \
  --tenant "tenant-a"

# 检查 SOC 2 合规性
opensquilla compliance check \
  --framework soc2 \
  --controls "access_control,encryption,logging"
```

---

## 🧪 安全测试

### 渗透测试

```bash
# 运行安全扫描
opensquilla security scan \
  --target https://opensquilla.company.com \
  --type full

# 检查常见漏洞
opensquilla security check \
  --cve-database \
  --severity "critical,high"

# 测试认证绕过
opensquilla security test-auth \
  --scenario "token_expiration" \
  --scenario "role_escalation"
```

### 依赖安全

```bash
# 扫描依赖漏洞
opensquilla security audit-dependencies \
  --format json \
  --output /tmp/dependency-audit.json

# 更新有漏洞的依赖
opensquilla security update-dependencies \
  --fix "critical,high"
```

---

## 📋 安全清单

### 部署前检查

- [ ] 所有 API 端点已启用认证
- [ ] 敏感数据已启用加密
- [ ] TLS 1.3 已配置
- [ ] IP 白名单已配置
- [ ] 速率限制已启用
- [ ] 审计日志已启用
- [ ] DLP 规则已配置
- [ ] 安全扫描已完成
- [ ] 渗透测试已完成
- [ ] 合规检查已通过

### 定期检查

- [ ] 每月：审查安全日志
- [ ] 每月：更新依赖和补丁
- [ ] 每季度：渗透测试
- [ ] 每季度：合规审计
- [ ] 每年：安全培训

---

## 🔗 相关资源

- [企业部署指南](./deployment.md)
- [审计日志指南](../logging/audit.md)
- [监控指南](../monitoring/README.md)
- [合规框架](../compliance/README.md)
