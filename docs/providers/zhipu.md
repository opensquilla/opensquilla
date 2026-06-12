# 智谱 AI (Zhipu) 提供商配置

智谱 AI 提供 GLM 系列大模型，包括 GLM-4 和 GLM-3-Turbo。

## 配置步骤

### 1. 获取 API Key

访问 [智谱AI开放平台](https://open.bigmodel.cn/) 注册并获取 API Key。

### 2. 环境变量配置

```bash
# Linux/macOS
export ZHIPUAI_API_KEY="..."

# Windows PowerShell
$env:ZHIPUAI_API_KEY="..."

# Windows 持久化
setx ZHIPUAI_API_KEY "..."
```

### 3. OpenSquilla 配置

```bash
opensquilla onboard --provider zhipu --api-key-env ZHIPUAI_API_KEY
```

### 4. 模型选择

```bash
# GLM-4-Plus
opensquilla configure provider --provider zhipu --model glm-4-plus

# GLM-4-Air
opensquilla configure provider --provider zhipu --model glm-4-air

# GLM-4-Flash
opensquilla configure provider --provider zhipu --model glm-4-flash

# GLM-3-Turbo
opensquilla configure provider --provider zhipu --model glm-3-turbo
```

## 可用模型

| 模型 | 说明 | 适用场景 |
|------|------|----------|
| `glm-4-plus` | GLM-4 旗舰版 | 复杂推理、创作 |
| `glm-4-air` | GLM-4 轻量版 | 日常对话、轻量任务 |
| `glm-4-flash` | GLM-4 极速版 | 高并发、实时响应 |
| `glm-3-turbo` | GLM-3 加速版 | 成本敏感场景 |

## 价格参考

| 模型 | 输入 (元/百万 Token) | 输出 (元/百万 Token) |
|------|---------------------|---------------------|
| GLM-4-Plus | 50.0 | 50.0 |
| GLM-4-Air | 1.0 | 1.0 |
| GLM-4-Flash | 0.1 | 0.1 |
| GLM-3-Turbo | 0.5 | 0.5 |

*价格仅供参考，以官方为准*

## 优势

- ✅ 国内访问稳定
- ✅ 多价格档位选择
- ✅ 支持函数调用
- ✅ 128K 上下文 (GLM-4-Plus)

## 常见问题

### Q: 如何查看余额？

访问 [智谱AI控制台](https://open.bigmodel.cn/usercenter/apikeys) 查看余额。

### Q: 速率限制是多少？

不同套餐有不同限制，详见官方文档 [速率限制说明](https://docs.bigmodel.cn/cn/api/rate-limit)。

### Q: 支持 Stream 模式吗？

✅ 支持，OpenSquilla 默认启用 Stream 模式。
