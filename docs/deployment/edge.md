# 边缘计算与离线部署指南

在受限环境、离线场景和边缘节点部署 OpenSquilla Agent。

## 🎯 适用场景

| 场景 | 特点 | 典型环境 |
|------|------|----------|
| **完全离线** | 无外网连接 | 军事、政府、工业控制 |
| **受限网络** | 低带宽、高延迟 | 远程站点、海上平台 |
| **数据敏感** | 数据不出域 | 金融、医疗、政务 |
| **边缘计算** | 低延迟要求 | 工厂、零售门店、自动驾驶 |
| **混合部署** | 云边协同 | 分布式企业 |

---

## 📦 离线部署

### 准备工作

```bash
# 1. 在有网络的机器上下载离线包
opensquilla offline download \
  --version latest \
  --output ./opensquilla-offline.tar.gz

# 2. 下载模型文件
opensquilla models download \
  --models llama-3.1-8b,qwen-7b \
  --output ./models/

# 3. 打包知识库
opensquilla kb export \
  --name production_kb \
  --output ./kb-export.tar.gz

# 4. 传输到目标环境
scp opensquilla-offline.tar.gz user@target-server:/tmp/
scp -r models/ user@target-server:/opt/opensquilla/
scp kb-export.tar.gz user@target-server:/tmp/
```

### 完全离线安装

```bash
# 在目标服务器上
cd /tmp

# 解压离线包
tar -xzf opensquilla-offline.tar.gz
cd opensquilla-offline

# 安装（无需网络）
./install.sh \
  --offline \
  --model-path /opt/opensquilla/models \
  --data-path /opt/opensquilla/data

# 导入知识库
opensquilla kb import \
  --input /tmp/kb-export.tar.gz \
  --offline

# 启动服务
opensquilla server start --offline
```

### 离线配置

```yaml
# config/offline.yaml
mode:
  type: "offline"
  air_gapped: true

# 模型配置（本地加载）
models:
  default: "llama-3.1-8b"
  local:
    - name: "llama-3.1-8b"
      path: "/opt/opensquilla/models/llama-3.1-8b.gguf"
      backend: "llama.cpp"
      quantization: "q4_k_m"
      context_size: 8192

    - name: "qwen-7b"
      path: "/opt/opensquilla/models/qwen-7b.gguf"
      backend: "llama.cpp"
      quantization: "q4_k_m"

# 禁用在线服务
providers:
  openai:
    enabled: false
  anthropic:
    enabled: false

# 知识库（本地向量存储）
knowledge_base:
  storage: "local"
  path: "/opt/opensquilla/data/vectors"
  index_type: "hnsw"

# 日志（本地文件）
logging:
  output: "file"
  path: "/var/log/opensquilla/"
```

---

## 🏢 本地部署

### Docker Compose 部署

```yaml
# docker-compose-offline.yml
version: '3.8'

services:
  opensquilla:
    image: opensquilla/offline:latest
    container_name: opensquilla
    ports:
      - "18791:18791"
    volumes:
      # 模型文件
      - ./models:/models:ro
      # 数据目录
      - ./data:/data
      # 配置文件
      - ./config:/config:ro
      # 日志
      - ./logs:/logs
    environment:
      - OPENQUILLA_MODE=offline
      - OPENQUILLA_MODEL_PATH=/models
      - OPENQUILLA_DATA_PATH=/data
      - OPENQUILLA_LOG_LEVEL=info
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:18791/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          memory: 16G
          cpus: '8'
        reservations:
          memory: 8G
          cpus: '4'

  # 可选：向量数据库
  qdrant:
    image: qdrant/qdrant:v1.7.0
    container_name: qdrant
    ports:
      - "6333:6333"
    volumes:
      - ./qdrant-storage:/qdrant/storage
    restart: unless-stopped
```

### Kubernetes 离线部署

```yaml
# k8s/offline-deployment.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opensquilla-config
data:
  config.yaml: |
    mode:
      type: "offline"
    models:
      default: "llama-3.1-8b"
      local:
        - name: "llama-3.1-8b"
          path: "/models/llama-3.1-8b.gguf"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: models-pvc
spec:
  accessModes:
    - ReadOnlyMany
  resources:
    requests:
      storage: 50Gi
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: opensquilla
spec:
  serviceName: opensquilla
  replicas: 1
  selector:
    matchLabels:
      app: opensquilla
  template:
    metadata:
      labels:
        app: opensquilla
    spec:
      containers:
      - name: opensquilla
        image: opensquilla/offline:latest
        ports:
        - containerPort: 18791
        volumeMounts:
        - name: config
          mountPath: /config
        - name: models
          mountPath: /models
          readOnly: true
        - name: data
          mountPath: /data
        resources:
          requests:
            memory: "8Gi"
            cpu: "4"
          limits:
            memory: "16Gi"
            cpu: "8"
        env:
        - name: OPENQUILLA_MODE
          value: "offline"
      volumes:
      - name: config
        configMap:
          name: opensquilla-config
      - name: models
        persistentVolumeClaim:
          claimName: models-pvc
      - name: data
        emptyDir: {}
```

---

## 🌐 边缘部署

### 边缘设备配置

```yaml
# config/edge.yaml
deployment:
  mode: "edge"
  location: "factory_floor_01"

# 轻量级配置
models:
  default: "llama-3.1-8b"
  quantization: "q4_k_m"  # 平衡性能和大小
  context_size: 4096      # 减少内存使用

# 边缘特化
edge:
  # 本地缓存
  cache:
    enabled: true
    path: "/var/cache/opensquilla"
    max_size: "5GB"

  # 断网模式
  disconnected_mode:
    enabled: true
    fallback_to_local: true
    sync_when_online: true

  # 资源限制
  resource_guard:
    max_memory: "4GB"
    max_cpu: "2"
    gpu_enabled: false
```

### 边缘节点管理

```bash
# 注册边缘节点
opensquilla edge register \
  --name factory-01 \
  --location "Beijing Factory" \
  --tags "manufacturing,assembly"

# 查看节点状态
opensquilla edge list

# 远程部署
opensquilla edge deploy \
  --node factory-01 \
  --config ./edge-config.yaml

# 同步更新
opensquilla edge sync \
  --node factory-01 \
  --include models,knowledge_base

# 远程监控
opensquilla edge monitor factory-01
```

---

## 🔒 安全加固

### 数据不出域

```yaml
# config/data-sovereignty.yaml
security:
  # 数据主权
  data_sovereignty:
    enabled: true
    storage_location: "local"
    prevent_egress: true

  # 网络隔离
  network:
    allow_internet: false
    allowed_hosts:
      - "localhost"
      - "*.internal.local"

  # 审计
  audit:
    log_all_access: true
    log_data_movement: true
    alert_on_egress: true

# 模型安全
models:
  # 使用本地模型
  use_local_only: true

  # 模型验证
  verify_checksum: true
  expected_checksums:
    llama-3.1-8b: "sha256:abc123..."
```

### 物理安全

```yaml
# config/physical-security.yaml
physical_security:
  # TPM 支持
  tpm:
    enabled: true
    use_for_secrets: true

  # 硬件加密
  hardware_encryption:
    enabled: true
    encrypt_at_rest: true
    encrypt_in_transit: true

  # 安全启动
  secure_boot:
    enabled: true
    verify_signature: true
```

---

## 🔄 云边协同

### 混合架构

```yaml
# config/hybrid.yaml
deployment:
  mode: "hybrid"

# 云端配置
cloud:
  enabled: true
  endpoint: "https://cloud.example.com"
  sync_interval: 300  # 5 分钟

# 边缘配置
edge:
  enabled: true
  local_first: true

# 数据同步
sync:
  # 上传策略
  upload:
    - type: "metrics"
      frequency: "hourly"
      compress: true

    - type: "logs"
      frequency: "daily"
      level: "error"

  # 下载策略
  download:
    - type: "models"
      frequency: "weekly"
      auto_update: false

    - type: "knowledge_base"
      frequency: "daily"
      delta: true

# 故障转移
failover:
  cloud_unavailable:
    action: "local_only"
    notify: true
```

### 智能路由

```yaml
# config/smart-routing.yaml
routing:
  strategy: "smart"

  rules:
    # 简单查询 → 本地
    - condition: "complexity < 5"
      destination: "local"
      reason: "低复杂度，本地处理足够"

    # 敏感数据 → 本地
    - condition: "data_sensitivity == 'high'"
      destination: "local"
      reason: "数据不出域"

    # 复杂任务 → 云端
    - condition: "complexity >= 8"
      destination: "cloud"
      reason: "需要更强算力"

    # 云端不可用 → 本地
    - condition: "cloud_available == false"
      destination: "local"
      reason: "故障转移"
```

---

## 📊 性能优化

### 硬件加速

```yaml
# config/hardware-acceleration.yaml
acceleration:
  # GPU 支持
  gpu:
    enabled: true
    backend: "cuda"  # cuda | rocm | metal
    device_id: 0
    memory_fraction: 0.9

  # CPU 优化
  cpu:
    num_threads: 8
    use_mmap: true
    use_mlock: true

  # 内存映射
  mmap:
    enabled: true
    lock_memory: true
```

### 量化配置

| 量化等级 | 大小 | 性能 | 精度 | 适用场景 |
|---------|------|------|------|----------|
| Q8_0 | 8.5 GB | 1.0x | 高 | 算力充足 |
| Q6_K | 6.5 GB | 0.9x | 高 | 平衡 |
| Q4_K_M | 4.7 GB | 0.7x | 中 | **推荐** |
| Q4_K_S | 4.3 GB | 0.65x | 中 | 内存受限 |
| Q3_K_M | 3.5 GB | 0.5x | 低 | 极限压缩 |

```yaml
# config/quantization.yaml
quantization:
  # 选择量化等级
  level: "q4_k_m"

  # 混合精度
  mixed_precision:
    enabled: false

  # 动态量化
  dynamic:
    enabled: false
```

---

## 🧪 测试和验证

### 离线环境测试

```bash
# 启动离线模式测试
opensquilla test --offline

# 测试模型加载
opensquilla models test --model llama-3.1-8b

# 测试知识库
opensquilla kb test --kb production_kb

# 性能基准
opensquilla benchmark \
  --model llama-3.1-8b \
  --iterations 100 \
  --offline
```

### 连通性测试

```bash
# 测试云边连接
opensquilla edge test-connection factory-01

# 测试同步
opensquilla edge test-sync factory-01

# 模拟断网
opensquilla simulate disconnect --duration 300
```

---

## 📞 相关资源

- [企业部署](../enterprise/deployment.md)
- [安全指南](../enterprise/security.md)
- [工作流自动化](../workflows/automation.md)
- [监控指南](../enterprise/monitoring.md)
