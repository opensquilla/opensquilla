# 数据源连接器指南

让 OpenSquilla Agent 能够访问和查询各种企业数据源，实现数据驱动的智能决策。

## 🎯 支持的数据源

### 关系型数据库

| 数据库 | 连接器 | 支持版本 |
|--------|--------|----------|
| PostgreSQL | postgres | 9.6+ |
| MySQL | mysql | 5.7+ |
| SQLite | sqlite | 3.x |
| SQL Server | mssql | 2017+ |
| Oracle | oracle | 12c+ |

### NoSQL 数据库

| 数据库 | 连接器 | 用途 |
|--------|--------|------|
| MongoDB | mongodb | 文档存储 |
| Redis | redis | 缓存/队列 |
| Elasticsearch | elasticsearch | 全文搜索 |
| DynamoDB | dynamodb | AWS 托管 |

### API 和 SaaS

| 类型 | 连接器 | 说明 |
|------|--------|------|
| REST API | http | 通用 REST API |
| GraphQL | graphql | GraphQL API |
| Salesforce | salesforce | CRM 数据 |
| Jira | jira | 项目管理 |
| Notion | notion | 文档/知识库 |
| Slack | slack | 消息/对话 |

### 文件系统

| 类型 | 连接器 | 说明 |
|------|--------|------|
| 本地文件 | file:// | 本地文件访问 |
| S3 | s3:// | AWS S3 |
| Azure Blob | azure:// | Azure 存储 |
| GCS | gcs:// | Google Cloud Storage |

---

## 🚀 快速开始

### 配置数据库连接

```yaml
# config/connectors/postgres.yaml
type: postgres
name: "company_db"

connection:
  host: "db.company.internal"
  port: 5432
  database: "production"
  username: "${DB_USER}"
  password: "${DB_PASSWORD}"
  ssl_mode: "require"

pool:
  min_size: 2
  max_size: 10
  timeout: 30

# 允许的查询
allowed_queries:
  - schema: "public"
    tables:
      - "users"
      - "orders"
      - "products"

  # 只读模式
  read_only: true

  # 查询超时
  query_timeout: 10
```

### 加载连接器

```bash
# 加载连接器配置
opensquilla connectors load postgres.yaml

# 验证连接
opensquilla connectors test company_db

# 列出可用表
opensquilla connectors list-tables company_db
```

### Agent 中使用

```yaml
# skills/data-query.md
---
name: data-query
description: 查询企业数据库
---

# 数据查询技能

## SQL 查询

当用户需要查询数据时，使用 PostgreSQL 连接器：

### 安全查询

- 仅使用 SELECT 语句
- 自动添加 LIMIT 100
- 过滤敏感字段

### 示例查询

```sql
-- 查询订单统计
SELECT 
  DATE(order_date) as date,
  COUNT(*) as orders,
  SUM(amount) as total
FROM orders
WHERE order_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE(order_date)
ORDER BY date DESC;
```

## 自然语言查询

将用户问题转换为 SQL：

"最近一个月销售额是多少？"
↓ 转换为 ↓
```sql
SELECT SUM(amount) FROM orders 
WHERE order_date >= CURRENT_DATE - INTERVAL '30 days';
```
```

---

## 📊 关系型数据库

### PostgreSQL

```yaml
# config/connectors/postgres.yaml
type: postgres
name: "postgres_production"

connection:
  host: "${PG_HOST}"
  port: 5432
  database: "${PG_DATABASE}"
  username: "${PG_USER}"
  password: "${PG_PASSWORD}"

# 安全配置
security:
  # 只读用户
  read_only_user: "readonly_user"

  # 行级安全
  row_level_security:
    enabled: true
    policy: "tenant_id = current_tenant_id()"

  # 敏感列屏蔽
  masked_columns:
    - "users.email"
    - "users.phone"
    - "orders.credit_card"

# 查询限制
limits:
  max_rows: 1000
  max_execution_time: 30
  max_complexity: 10
```

### MySQL

```yaml
# config/connectors/mysql.yaml
type: mysql
name: "mysql_production"

connection:
  host: "${MYSQL_HOST}"
  port: 3306
  database: "${MYSQL_DATABASE}"
  username: "${MYSQL_USER}"
  password: "${MYSQL_PASSWORD}"
  charset: "utf8mb4"

ssl:
  enabled: true
  ca: "/path/to/ca.pem"
  cert: "/path/to/client-cert.pem"
  key: "/path/to/client-key.pem"
```

### 查询示例

```bash
# 使用 Agent 查询数据库
opensquilla agent -m "
连接到 PostgreSQL 数据库 company_db，
查询最近 7 天每天的销售订单数量和总金额，
按日期排序，生成报表。
" --connector company_db
```

---

## 📄 NoSQL 数据库

### MongoDB

```yaml
# config/connectors/mongodb.yaml
type: mongodb
name: "mongo_production"

connection:
  uri: "mongodb://${MONGO_USER}:${MONGO_PASSWORD}@${MONGO_HOST}:27017"
  database: "production"
  auth_mechanism: "SCRAM-SHA-256"

# 集合配置
collections:
  - name: "users"
    allowed_operations: ["find", "aggregate"]
    query_filter: "{ \"deleted_at\": null }"

  - name: "orders"
    allowed_operations: ["find", "aggregate", "count"]
    max_depth: 5

# 聚合管道限制
aggregation:
  max_stages: 10
  max_memory: 100  # MB
```

### Redis

```yaml
# config/connectors/redis.yaml
type: redis
name: "redis_cache"

connection:
  host: "${REDIS_HOST}"
  port: 6379
  password: "${REDIS_PASSWORD}"
  db: 0

# 允许的操作
operations:
  - "get"
  - "set"
  - "hget"
  - "hset"
  - "lrange"
  - "zrange"

# 键命名空间
namespaces:
  - prefix: "user:"
    operations: ["get", "set", "hget", "hset"]

  - prefix: "cache:"
    operations: ["get", "set", "expire"]

  - prefix: "session:"
    operations: ["get", "set", "expire"]
```

---

## 🌐 API 连接器

### REST API

```yaml
# config/connectors/rest-api.yaml
type: rest
name: "company_api"

base_url: "https://api.company.com/v2"

authentication:
  type: "bearer"  # bearer | basic | api_key | oauth2
  token: "${API_TOKEN}"

# 端点配置
endpoints:
  - path: "/users"
    method: "GET"
    allowed_params:
      - "page"
      - "limit"
      - "sort"

  - path: "/orders"
    method: "POST"
    allowed_params:
      - "customer_id"
      - "items"
      - "shipping_address"

# 速率限制
rate_limit:
  requests_per_minute: 100
  burst: 10

# 重试策略
retry:
  max_attempts: 3
  backoff: "exponential"
  retry_on:
    - "500"
    - "502"
    - "503"
```

### GraphQL

```yaml
# config/connectors/graphql.yaml
type: graphql
name: "github_graphql"

endpoint: "https://api.github.com/graphql"

authentication:
  type: "bearer"
  token: "${GITHUB_TOKEN}"

# 允许的查询
allowed_queries:
  - name: "GetRepository"
    fields: ["name", "description", "stargazerCount"]

  - name: "SearchIssues"
    fields: ["title", "body", "state", "author"]

# 查询复杂度限制
complexity:
  max_complexity: 1000
  max_depth: 10
```

---

## 🏢 SaaS 连接器

### Salesforce

```yaml
# config/connectors/salesforce.yaml
type: salesforce
name: "salesforce_crm"

authentication:
  username: "${SF_USERNAME}"
  password: "${SF_PASSWORD}"
  security_token: "${SF_SECURITY_TOKEN}"

# 对象访问
objects:
  - name: "Account"
    fields: ["Id", "Name", "Industry", "Revenue"]

  - name: "Contact"
    fields: ["Id", "FirstName", "LastName", "Email"]

  - name: "Opportunity"
    fields: ["Id", "Name", "Amount", "StageName", "CloseDate"]

# SOQL 查询限制
soql:
  max_rows: 2000
  max_execution_time: 60
```

### Jira

```yaml
# config/connectors/jira.yaml
type: jira
name: "jira_tracker"

base_url: "https://company.atlassian.net"

authentication:
  type: "basic"
  username: "${JIRA_EMAIL}"
  api_token: "${JIRA_API_TOKEN}"

# 项目配置
projects:
  - key: "PROJ"
    allowed_issue_types: ["Story", "Bug", "Task"]

  - key: "OPS"
    allowed_issue_types: ["Incident", "Problem"]

# JQL 查询
jql:
  max_results: 100
  allowed_fields:
    - "key"
    - "summary"
    - "status"
    - "assignee"
    - "priority"
```

---

## 🗂️ 文件系统连接器

### S3

```yaml
# config/connectors/s3.yaml
type: s3
name: "s3_storage"

authentication:
  access_key_id: "${AWS_ACCESS_KEY_ID}"
  secret_access_key: "${AWS_SECRET_ACCESS_KEY}"
  region: "us-east-1"

# 存储桶配置
buckets:
  - name: "company-documents"
    allowed_operations: ["get", "list"]
    prefix: "public/"

  - name: "company-uploads"
    allowed_operations: ["get", "put", "list"]
    max_file_size: 104857600  # 100MB

# 生命周期规则
lifecycle:
  transition_to_ia: 90  # 天
  transition_to_glacier: 180
  expiration: 365
```

### 本地文件

```yaml
# config/connectors/file.yaml
type: file
name: "local_files"

# 允许的路径
allowed_paths:
  - path: "/data/documents"
    operations: ["read", "list"]

  - path: "/data/uploads"
    operations: ["read", "write", "list"]
    max_file_size: 10485760

  - path: "/tmp/opensquilla"
    operations: ["read", "write", "delete"]

# 文件类型限制
allowed_types:
  - "text/*"
  - "application/json"
  - "application/pdf"

denied_patterns:
  - "*.key"
  - "*.pem"
  - ".env"
```

---

## 🔄 数据流

### ETL 流程

```yaml
# config/connectors/etl-pipeline.yaml
name: "sales_pipeline"
type: etl

source:
  type: postgres
  name: "sales_db"
  query: |
    SELECT * FROM orders 
    WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'

transform:
  - type: "filter"
    condition: "amount > 100"

  - type: "aggregate"
    group_by: ["customer_id"]
    operations:
      - field: "amount"
        function: "sum"
        alias: "total_spent"

destination:
  type: mongodb
  name: "analytics_db"
  collection: "customer_stats"

# 调度
schedule:
  cron: "0 2 * * *"  # 每天凌晨 2 点
  timezone: "Asia/Shanghai"
```

### 实时数据流

```yaml
# config/connectors/stream-pipeline.yaml
name: "realtime_events"
type: stream

source:
  type: kafka
  name: "events"
  topic: "user_events"
  group_id: "opensquilla_processor"

processor:
  - type: "parse_json"
  - type: "extract_fields"
    fields: ["user_id", "event_type", "timestamp"]
  - type: "validate"
    schema: "event_schema.json"

destination:
  type: elasticsearch
  name: "events_index"
  index: "user_events-{{YYYY.MM.dd}}"

# 性能
performance:
  batch_size: 100
  flush_interval: 5  # 秒
  max_workers: 4
```

---

## 🔐 安全最佳实践

### 凭证管理

```bash
# 使用环境变量（推荐）
export DB_PASSWORD="..."

# 使用密钥管理服务
opensquilla connectors secret set \
  --connector postgres \
  --key password \
  --value-from-vault

# 使用密钥文件
opensquilla connectors secret set \
  --connector postgres \
  --key password \
  --value-from-file /secure/db_password.txt
```

### 查询安全

```yaml
security:
  # SQL 注入防护
  sql_injection_protection:
    enabled: true
    parametrized_queries: true

  # 查询深度限制
  query_depth:
    max_joins: 5
    max_subqueries: 3

  # 结果大小限制
  result_size:
    max_rows: 10000
    max_size_mb: 100

  # 敏感数据保护
  sensitive_data:
    auto_mask: true
    mask_patterns:
      - "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b"
      - "\\b\\d{4}-?\\d{4}-?\\d{4}-?\\d{4}\\b"
```

---

## 📊 数据虚拟化

```yaml
# config/connectors/virtual-db.yaml
name: "virtual_warehouse"
type: federated

sources:
  - name: "sales_postgres"
    type: postgres
    connection: "postgres://sales_db"

  - name: "marketing_mongo"
    type: mongodb
    connection: "mongodb://marketing_db"

  - name: "support_redis"
    type: redis
    connection: "redis://support_db"

# 联合查询
federated_queries:
  - name: "customer_360"
    sources:
      - connector: "sales_postgres"
        table: "customers"

      - connector: "marketing_mongo"
        collection: "campaign_interactions"

      - connector: "support_redis"
        key_pattern: "support:*"

    join_key: "customer_id"
```

---

## 🧪 测试连接

```bash
# 测试单个连接器
opensquilla connectors test postgres

# 测试查询
opensquilla connectors query postgres \
  --sql "SELECT COUNT(*) FROM users"

# 测试所有连接器
opensquilla connectors test-all

# 性能测试
opensquilla connectors benchmark \
  --connector postgres \
  --queries benchmark_queries.sql
```

---

## 📞 相关资源

- [数据库连接器 API](../../api/connectors.md)
- [API 集成指南](../integrations/README.md)
- [数据安全指南](../enterprise/security.md)
- [工作流自动化](../workflows/automation.md)
