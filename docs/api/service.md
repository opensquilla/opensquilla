# API 服务暴露指南

将 OpenSquilla Agent 作为 REST API、WebSocket 或 gRPC 服务暴露给外部调用。

## 🎯 服务类型

| 类型 | 协议 | 适用场景 | 实时性 |
|------|------|----------|--------|
| **REST API** | HTTP/HTTPS | 标准集成、简单调用 | 请求/响应 |
| **WebSocket** | WS/WSS | 实时对话、流式输出 | 双向实时 |
| **gRPC** | HTTP/2 | 高性能、微服务 | 双向流 |
| **Server-Sent Events** | HTTP/SSE | 单向推送 | 服务器推送 |

---

## 🚀 REST API

### 快速启动

```bash
# 启动 API 服务
opensquilla api serve \
  --host 0.0.0.0 \
  --port 18791 \
  --workers 4

# 使用 Docker
docker run -d \
  -p 18791:18791 \
  -v ~/.opensquilla:/app/config \
  opensquilla/api-server
```

### 基础配置

```yaml
# config/api/service.yaml
server:
  host: "0.0.0.0"
  port: 18791
  workers: 4
  log_level: "info"

# CORS
cors:
  enabled: true
  origins:
    - "https://app.company.com"
    - "https://*.company.com"
  methods:
    - "GET"
    - "POST"
    - "PUT"
    - "DELETE"
  credentials: true

# 限流
rate_limit:
  global:
    requests_per_minute: 1000
  per_api_key:
    requests_per_minute: 100
  per_ip:
    requests_per_minute: 10
```

### API 端点

#### Agent 调用

```http
POST /api/v1/agent/{agent_name}
Content-Type: application/json
Authorization: Bearer {api_key}

{
  "message": "用户消息",
  "context": {
    "user_id": "user123",
    "session_id": "session456"
  },
  "params": {
    "model": "claude-3-5-sonnet",
    "temperature": 0.7,
    "max_tokens": 2000
  }
}
```

**响应：**

```json
{
  "id": "req_abc123",
  "agent": "general_assistant",
  "response": "Agent 回复内容",
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 500,
    "total_tokens": 600
  },
  "latency_ms": 1234,
  "model": "claude-3-5-sonnet-20250114",
  "timestamp": "2026-06-02T10:00:00Z"
}
```

#### 流式响应

```http
POST /api/v1/agent/{agent_name}/stream
Content-Type: application/json
Authorization: Bearer {api_key}

{
  "message": "用户消息",
  "stream": true
}
```

**响应 (Server-Sent Events)：**

```
data: {"type":"start","id":"req_abc123"}

data: {"type":"token","token":"Hello"}

data: {"type":"token","token":" world"}

data: {"type":"end","usage":{"total_tokens":10}}
```

#### 批量调用

```http
POST /api/v1/agent/batch
Content-Type: application/json
Authorization: Bearer {api_key}

{
  "requests": [
    {"agent": "assistant", "message": "问题1"},
    {"agent": "assistant", "message": "问题2"},
    {"agent": "assistant", "message": "问题3"}
  ]
}
```

**响应：**

```json
{
  "results": [
    {"id": 0, "response": "回答1", "status": "success"},
    {"id": 1, "response": "回答2", "status": "success"},
    {"id": 2, "response": "回答3", "status": "success"}
  ],
  "summary": {
    "total": 3,
    "succeeded": 3,
    "failed": 0
  }
}
```

### 身份验证

#### API Key

```bash
# 创建 API Key
opensquilla api-keys create \
  --name "production-app" \
  --tenant "tenant_a" \
  --rate-limit 100/minute

# 列出 API Keys
opensquilla api-keys list --tenant "tenant_a"

# 撤销 API Key
opensquilla api-keys revoke sk_xxxxxxxxxxxxx
```

**使用方式：**

```http
# 方式一：Bearer Token
Authorization: Bearer sk_xxxxxxxxxxxxx

# 方式二：查询参数
GET /api/v1/agent/assistant?api_key=sk_xxxxxxxxxxxxx

# 方式三：请求头
X-API-Key: sk_xxxxxxxxxxxxx
```

#### JWT

```yaml
# config/api/jwt.yaml
authentication:
  type: "jwt"

  # JWT 验证
  jwt:
    # 密钥
    secret: "${JWT_SECRET}"

    # 算法
    algorithm: "HS256"

    # 签发者
    issuer: "https://auth.company.com"

    # 受众
    audience: "opensquilla-api"

    # 过期时间
    expiration: 3600  # 秒
```

**JWT Payload：**

```json
{
  "sub": "user123",
  "name": "John Doe",
  "tenant": "tenant_a",
  "roles": ["user"],
  "iat": 1234567890,
  "exp": 1234571490,
  "iss": "https://auth.company.com",
  "aud": "opensquilla-api"
}
```

#### OAuth 2.0

```yaml
# config/api/oauth.yaml
authentication:
  type: "oauth2"

  oauth2:
    # 授权端点
    authorization_endpoint: "https://auth.company.com/oauth/authorize"

    # 令牌端点
    token_endpoint: "https://auth.company.com/oauth/token"

    # 客户端配置
    client_id: "${OAUTH_CLIENT_ID}"
    client_secret: "${OAUTH_CLIENT_SECRET}"

    # 作用域
    scopes:
      - "agent:call"
      - "agent:stream"

    # 资源服务器配置
    introspection_endpoint: "https://auth.company.com/oauth/introspect"
```

---

## 🔌 WebSocket

### 连接

```javascript
// 客户端连接
const ws = new WebSocket('wss://api.example.com/ws?token=xxx');

// 消息格式
ws.send(JSON.stringify({
  type: 'message',
  agent: 'assistant',
  content: '你好',
  session_id: 'session123'
}));
```

### 消息协议

**客户端 → 服务器：**

```json
{
  "type": "message",
  "agent": "assistant",
  "content": "用户消息",
  "session_id": "session123",
  "params": {
    "temperature": 0.7
  }
}
```

**服务器 → 客户端：**

```json
{
  "type": "delta",
  "content": "Hello",
  "done": false
}
```

```json
{
  "type": "complete",
  "response": "Hello, how can I help?",
  "usage": {"total_tokens": 10},
  "done": true
}
```

### 服务端配置

```yaml
# config/api/websocket.yaml
websocket:
  enabled: true
  path: "/ws"

  # 心跳
  heartbeat:
    interval: 30  # 秒
    timeout: 60

  # 消息大小限制
  max_message_size: 10485760  # 10MB

  # 会话管理
  session:
    timeout: 3600  # 1 小时
    max_connections: 1000

  # 压缩
  compression:
    enabled: true
    level: 6
```

---

## 🌐 gRPC

### 定义服务

```protobuf
// api/proto/opensquilla.proto
syntax = "proto3";

package opensquilla;

service AgentService {
  // 简单调用
  rpc Call(CallRequest) returns (CallResponse);

  // 流式响应
  rpc Stream(CallRequest) returns (stream StreamResponse);

  // 双向流
  rpc Chat(stream ChatRequest) returns (stream ChatResponse);
}

message CallRequest {
  string agent = 1;
  string message = 2;
  map<string, string> context = 3;
  CallParams params = 4;
}

message CallResponse {
  string response = 1;
  Usage usage = 2;
  int64 latency_ms = 3;
}

message StreamResponse {
  oneof content {
    string delta = 1;
    CallResponse complete = 2;
  }
}

message Usage {
  int32 prompt_tokens = 1;
  int32 completion_tokens = 2;
  int32 total_tokens = 3;
}

message CallParams {
  string model = 1;
  float temperature = 2;
  int32 max_tokens = 3;
}
```

### 服务端配置

```yaml
# config/api/grpc.yaml
grpc:
  enabled: true
  port: 18792

  # 反射（用于调试）
  reflection: true

  # 健康检查
  health_check: true

  # TLS
  tls:
    enabled: true
    cert: "/path/to/cert.pem"
    key: "/path/to/key.pem"

  # 最大并发流
  max_concurrent_streams: 1000

  # 消息大小限制
  max_message_size:
    receive: 10485760  # 10MB
    send: 10485760
```

### 客户端调用

```python
# Python 客户端
import grpc
from opensquilla.proto import opensquilla_pb2, opensquilla_pb2_grpc

# 连接
channel = grpc.insecure_channel('localhost:18792')
stub = opensquilla_pb2_grpc.AgentServiceStub(channel)

# 调用
request = opensquilla_pb2.CallRequest(
    agent='assistant',
    message='你好',
    context={'user_id': 'user123'}
)
response = stub.Call(request)

print(response.response)
```

---

## 🔐 安全配置

### TLS/SSL

```yaml
# config/api/tls.yaml
tls:
  enabled: true

  # 证书配置
  certificate:
    cert: "/path/to/cert.pem"
    key: "/path/to/key.pem"
    chain: "/path/to/chain.pem"

  # 客户端证书（mTLS）
  client_cert:
    required: false
    ca: "/path/to/ca.pem"

  # 密码套件
  cipher_suites:
    - "TLS_AES_128_GCM_SHA256"
    - "TLS_AES_256_GCM_SHA384"
    - "TLS_CHACHA20_POLY1305_SHA256"

  # 最小版本
  min_version: "TLS1.2"
```

### IP 白名单

```yaml
# config/api/security.yaml
security:
  # IP 白名单
  ip_whitelist:
    - "10.0.0.0/8"
    - "192.168.0.0/16"
    - "203.0.113.0/24"

  # 地理限制
  geo_restriction:
    allowed_countries:
      - "CN"
      - "US"
      - "JP"
```

### 内容过滤

```yaml
security:
  # 输入过滤
  input_filter:
    enabled: true
    max_length: 10000
    blocked_patterns:
      - "\\bpassword\\b"
      - "\\bapi_key\\b"

  # 输出过滤
  output_filter:
    enabled: true
    mask_patterns:
      - "\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z|a-z]{2,}\\b"

  # 敏感词检测
  content_moderation:
    enabled: true
    categories:
      - "hate_speech"
      - "violence"
      - "adult_content"
```

---

## 📊 监控和日志

### Prometheus 指标

```yaml
# config/api/monitoring.yaml
monitoring:
  prometheus:
    enabled: true
    path: "/metrics"

  # 自定义指标
  metrics:
    - name: "api_requests_total"
      type: "counter"
      labels: ["method", "endpoint", "status"]

    - name: "api_request_duration_seconds"
      type: "histogram"
      buckets: [0.1, 0.5, 1, 2, 5, 10]

    - name: "api_concurrent_connections"
      type: "gauge"
```

### 访问日志

```yaml
logging:
  # 访问日志
  access_log:
    enabled: true
    format: "json"
    output: "/var/log/opensquilla/access.log"

  # 慢查询日志
  slow_log:
    enabled: true
    threshold: 5  # 秒
    output: "/var/log/opensquilla/slow.log"

  # 审计日志
  audit_log:
    enabled: true
    events:
      - "agent.call"
      - "api_key.create"
      - "api_key.revoke"
    output: "/var/log/opensquilla/audit.log"
```

---

## 🧪 测试

### 本地测试

```bash
# 启动测试服务器
opensquilla api serve --dev

# 使用 curl 测试
curl -X POST http://localhost:18791/api/v1/agent/assistant \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test_key" \
  -d '{"message": "你好"}'

# 流式测试
curl -N http://localhost:18791/api/v1/agent/assistant/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
```

### 负载测试

```bash
# 使用 wrk
wrk -t4 -c100 -d30s \
  -H "Authorization: Bearer test_key" \
  -s post.lua \
  http://localhost:18791/api/v1/agent/assistant

# 使用 Apache Bench
ab -n 10000 -c 100 \
  -H "Authorization: Bearer test_key" \
  -p request.json \
  -T application/json \
  http://localhost:18791/api/v1/agent/assistant
```

---

## 🚀 生产部署

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  opensquilla-api:
    image: opensquilla/api-server:latest
    ports:
      - "18791:18791"
    environment:
      - OPENQUILLA_CONFIG=/app/config
      - OPENQUILLA_WORKERS=4
    volumes:
      - ./config:/app/config
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18791/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./certs:/etc/nginx/certs
    depends_on:
      - opensquilla-api
    restart: unless-stopped
```

### Kubernetes

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: opensquilla-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: opensquilla-api
  template:
    metadata:
      labels:
        app: opensquilla-api
    spec:
      containers:
      - name: api
        image: opensquilla/api-server:latest
        ports:
        - containerPort: 18791
        env:
        - name: OPENQUILLA_WORKERS
          value: "4"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 18791
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 18791
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: opensquilla-api
spec:
  selector:
    app: opensquilla-api
  ports:
  - port: 80
    targetPort: 18791
  type: LoadBalancer
```

---

## 📞 相关资源

- [工作流自动化](../workflows/automation.md)
- [企业部署](../enterprise/deployment.md)
- [成本优化](../cost/optimization.md)
- [安全指南](../enterprise/security.md)
