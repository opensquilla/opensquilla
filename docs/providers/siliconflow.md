# 硅基流动 (SiliconFlow) 提供商配置

硅基流动提供多种国内外大模型 API，包括 Qwen、DeepSeek、GLM 等。

## 配置步骤

### 1. 获取 API Key

访问 [硅基流动开放平台](https://cloud.siliconflow.cn/) 注册并获取 API Key。

### 2. 环境变量配置

```bash
# Linux/macOS
export SILICONFLOW_API_KEY="sk-..."

# Windows PowerShell
$env:SILICONFLOW_API_KEY="sk-..."

# Windows 持久化
setx SILICONFLOW_API_KEY "sk-..."
```

### 3. OpenSquilla 配置

```bash
opensquilla onboard --provider siliconflow --api-key-env SILICONFLOW_API_KEY
```

### 4. 模型选择

```bash
# Qwen2.5 系列
opensquilla configure provider --provider siliconflow --model Qwen/Qwen2.5-7B-Instruct

# DeepSeek-V3
opensquilla configure provider --provider siliconflow --model deepseek-ai/DeepSeek-V3

# GLM-4
opensquilla configure provider --provider siliconflow --model THUDM/glm-4-9b-chat
```

## 热门模型

| 模型 ID | 说明 | 适用场景 |
|---------|------|----------|
| `Qwen/Qwen2.5-7B-Instruct` | 通义千问 2.5 | 通用对话 |
| `Qwen/Qwen2.5-Coder-7B-Instruct` | 代码专用 | 代码生成 |
| `deepseek-ai/DeepSeek-V3` | DeepSeek-V3 | 推理、数学 |
| `THUDM/glm-4-9b-chat` | 智谱 GLM-4 | 中文对话 |
| `meta-llama/Llama-3.1-8B-Instruct` | Llama 3.1 | 英文对话 |

## 优势

- ✅ 聚合多家模型
- ✅ 价格透明
- ✅ 国内访问快
- ✅ 新品更新快

## 常见问题

### Q: 支持哪些模型？

硅基流动支持 100+ 模型，包括 Qwen、DeepSeek、GLM、Llama、Mistral 等。

### Q: 如何查看价格？

访问 [硅基流动价格页面](https://cloud.siliconflow.cn/price) 查看实时价格。
