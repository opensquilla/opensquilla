# RAG 实战指南

检索增强生成（RAG）结合知识检索和 LLM 生成，为 Agent 提供企业知识库能力。

## 🎯 什么是 RAG？

### RAG 架构

```
┌─────────────────────────────────────────────────────────────┐
│                         用户查询                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      查询处理                                │
│  - 意图识别                                                 │
│  - 查询重写                                                 │
│  - 查询扩展                                                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      向量检索                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  查询向量化 → 向量数据库 → Top-K 文档                   │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      重排序（可选）                           │
│  - 交叉编码器                                              │
│  - 相关性评分                                              │
│  - 结果筛选                                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      上下文构建                               │
│  - 文档拼接                                                │
│  - 上下文压缩                                              │
│  - 引用标注                                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      LLM 生成                                │
│  - 基于检索的问答                                           │
│  - 引用来源                                                │
│  - 答案生成                                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 基础 RAG 配置

```yaml
# config/rag/basic.yaml
rag:
  enabled: true

  # 向量数据库配置
  vector_store:
    type: "chromadb"  # chromadb | qdrant | milvus | pinecone
    host: "localhost"
    port: 8000
    collection: "documents"

  # 嵌入模型配置
  embedding:
    provider: "openai"
    model: "text-embedding-3-small"
    dimension: 1536
    batch_size: 100

  # 检索配置
  retrieval:
    top_k: 5
    score_threshold: 0.7
    search_type: "similarity"  # similarity | mmr | hybrid

  # 上下文配置
  context:
    max_tokens: 4000
    overlap: 200
    include_citations: true
```

### 启用 RAG

```bash
# 加载 RAG 配置
opensquilla configure rag --config-file config/rag/basic.yaml

# 创建知识库
opensquilla rag create collection my-knowledge-base

# 添加文档
opensquilla rag add my-knowledge-base --file documents/*.md

# 查询
opensquilla agent -m "根据知识库，产品 X 的主要功能是什么？"
```

---

## 📚 文档处理

### 支持的文档类型

| 类型 | 格式 | 分块策略 |
|------|------|----------|
| **文本** | .txt, .md | 段落/章节 |
| **PDF** | .pdf | 页面/段落 |
| **Word** | .docx | 段落/样式 |
| **HTML** | .html, .htm | 标签结构 |
| **代码** | .py, .js, .java | 函数/类 |
| **表格** | .csv, .xlsx | 行/列 |

### 文档处理流程

```bash
# 1. 文档导入
opensquilla rag import my-kb \
  --source ./documents \
  --recursive

# 2. 文档分块
opensquilla rag chunk my-kb \
  --chunk-size 1000 \
  --chunk-overlap 200 \
  --strategy semantic  # semantic | fixed | recursive

# 3. 去重
opensquilla rag deduplicate my-kb \
  --method semantic \
  --threshold 0.95

# 4. 索引
opensquilla rag index my-kb \
  --build-index
```

### 高级分块策略

```yaml
chunking:
  # 语义分块
  semantic:
    enabled: true
    min_chunk_size: 500
    max_chunk_size: 1500
    sentence_split: true
    paragraph_merge: true

  # 代码分块
  code:
    enabled: true
    split_by: "function"  # function | class | module
    include_docstrings: true
    max_lines: 100

  # 表格分块
  table:
    enabled: true
    include_headers: true
    max_rows: 50
    merge_similar: true
```

---

## 🔍 检索策略

### 基础检索

```yaml
retrieval:
  # 相似度检索
  similarity:
    enabled: true
    metric: "cosine"  # cosine | euclidean | dotproduct
    top_k: 5

  # MMR 检索（多样性）
  mmr:
    enabled: false
    k: 5
    fetch_k: 20
    lambda_mult: 0.5

  # 混合检索
  hybrid:
    enabled: false
    alpha: 0.5  # 0=关键词, 1=向量
    keyword_weight: 0.3
    vector_weight: 0.7
```

### 高级检索

```yaml
retrieval:
  # 查询扩展
  query_expansion:
    enabled: true
    methods:
      - "hyde"  # Hypothetical Document Embeddings
      - "query_rewrite"
      - "synonym_expansion"

  # 重排序
  reranking:
    enabled: true
    model: "cohere-rerank-v2"  # cohere | cross-encoder
    top_n: 3

  # 过滤
  filters:
    - field: "metadata.category"
      operator: "eq"
      value: "technical"

    - field: "metadata.date"
      operator: "gte"
      value: "2024-01-01"
```

---

## 📊 向量数据库

### ChromaDB 配置

```yaml
vector_store:
  type: chromadb
  config:
    host: localhost
    port: 8000
    persist_directory: /data/chroma
    auth:
      enabled: true
      username: admin
      password: "${CHROMA_PASSWORD}"

  collections:
    - name: documents
      metadata:
        description: "公司文档"
        version: "1.0"

      embedding_function:
        provider: openai
        model: text-embedding-3-small

      indexes:
        - field: metadata.category
        - field: metadata.date
```

### Qdrant 配置

```yaml
vector_store:
  type: qdrant
  config:
    url: http://localhost:6333
    api_key: "${QDRANT_API_KEY}"

  collections:
    - name: documents
      vector_size: 1536
      distance: Cosine
      payload:
        - name: category
          type: keyword
        - name: date
          type: date
        - name: author
          type: text

      hnsw_config:
        m: 16
        ef_construct: 100
        full_scan_threshold: 10000
```

---

## 🎯 实战案例

### 案例 1：企业知识库

```bash
# 1. 创建企业知识库
opensquilla rag create company-kb \
  --description "公司内部文档知识库"

# 2. 导入文档
opensquilla rag import company-kb \
  --source /mnt/share/documents \
  --include "*.md,*.pdf,*.docx" \
  --recursive

# 3. 配置访问权限
opensquilla rag configure company-kb \
  --access-control rbac \
  --default-role reader

# 4. 创建查询接口
opensquilla agent -m \
  "查询公司报销政策，包括差旅住宿标准"
```

### 案例 2：代码助手

```yaml
# rag/code-assistant.yaml
rag:
  collection: "codebase"

  chunking:
    code:
      split_by: function
      include_docstrings: true
      include_imports: true

  retrieval:
    filters:
      - field: metadata.language
        operator: eq
        value: "{{user.language_preference}}"

    reranking:
      enabled: true
      model: cross-encoder
      consider_recency: true

  context:
    max_functions: 10
    include_imports: true
    include_tests: true
```

```bash
# 使用代码助手
opensquilla agent -m \
  "如何使用 opensquilla 的 RAG 功能？" \
  --rag-config rag/code-assistant.yaml
```

### 案例 3：客服机器人

```yaml
# rag/customer-service.yaml
rag:
  collection: "support_docs"

  retrieval:
    query_expansion:
      enabled: true
      methods:
        - intent_detection
        - faq_mapping

    filters:
      - field: metadata.product
        operator: eq
        value: "{{user.product}}"

      - field: metadata.language
        operator: eq
        value: "{{user.language}}"

  response:
    include_citations: true
    include_related_questions: true
    suggest_actions: true
```

---

## 📈 性能优化

### 索引优化

```bash
# 创建 HNSW 索引
opensquilla rag index optimize \
  --collection my-kb \
  --index-type hnsw \
  --m 16 \
  --ef_construct 100

# 创建 payload 索引
opensquilla rag index payload \
  --collection my-kb \
  --field metadata.category \
  --type keyword
```

### 缓存策略

```yaml
cache:
  # 查询缓存
  query_cache:
    enabled: true
    ttl: 3600
    max_size: 10000

  # 文档缓存
  document_cache:
    enabled: true
    ttl: 7200
    max_size: 1000

  # 向量缓存
  embedding_cache:
    enabled: true
    ttl: 86400
```

### 批量处理

```bash
# 批量嵌入
opensquilla rag embed-batch \
  --collection my-kb \
  --batch-size 100 \
  --max-workers 4

# 批量检索
opensquilla rag search-batch \
  --collection my-kb \
  --queries queries.txt \
  --batch-size 10
```

---

## 🔧 监控和调试

### 检索质量评估

```bash
# 评估检索质量
opensquilla rag evaluate \
  --collection my-kb \
  --test-set test-queries.json \
  --metrics ndcg,precision,recall

# 分析检索结果
opensquilla rag analyze \
  --collection my-kb \
  --query "示例查询" \
  --explain
```

### 调试模式

```bash
# 查看检索详情
opensquilla agent -m "查询内容" \
  --rag-debug \
  --rag-show-scores \
  --rag-show-retrieved
```

---

## 🧪 测试和验证

### 评估指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| **Precision@K** | 前K个结果的相关性 | > 0.8 |
| **Recall@K** | 相关文档的召回率 | > 0.9 |
| **MRR** | 平均倒数排名 | > 0.7 |
| **NDCG@K** | 归一化折损累积增益 | > 0.8 |
| **Response Time** | 检索响应时间 | < 500ms |

### 测试数据集

```json
{
  "queries": [
    {
      "query": "如何申请年假？",
      "expected_docs": ["hr-policy-001.md", "employee-handbook.md"],
      "expected_answer": "年假申请需要提前..."
    }
  ]
}
```

```bash
# 运行测试
opensquilla rag test \
  --collection my-kb \
  --test-set test-queries.json
```

---

## 🔗 相关资源

- [向量化指南](./vectorization.md)
- [检索策略](./retrieval.md)
- [评估方法](./evaluation.md)
- [性能优化](../performance/index.md)
