# OpenSquilla — Token 高效 AI Agent

[![Website](https://img.shields.io/badge/Website-opensquilla.ai-blue)](https://opensquilla.ai)
[![Release](https://github.com/OpenSquilla/opensquilla/workflows/Wheelhouse%20Zip%20Release/badge.svg)](https://github.com/OpenSquilla/opensquilla/releases)
[![License](https://img.shields.io/github/license/OpenSquilla/opensquilla)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-green)](https://www.python.org/)

> **相同预算，更强智能** — OpenSquilla 是一个 Token 高效的微内核 AI Agent

---

## 🎯 简介

OpenSquilla 通过智能路由、持久记忆、安全沙箱、内置网络搜索和本地向量检索，在**相同预算下提供更强能力**。

| 特性 | 说明 |
|------|------|
| **SquillaRouter 智能路由** | 本地 LightGBM + ONNX BGE 分类器，四层智能分发 |
| **四层认知记忆** | working → episodic → semantic → raw |
| **MCP + 16 技能** | 按需加载，避免 steady-state token 浪费 |
| **20+ LLM 支持** | OpenRouter/OpenAI/Anthropic/DeepSeek/智谱/硅基流动等 |
| **安全沙箱** | 三层策略 + Bubblewrap 隔离 |
| **统一网关** | Web UI + CLI + 多渠道适配器 |

---

## 🚀 快速开始

### 前置要求

- Git 和 Git LFS
- Python 3.12+ 或 uv（推荐）

### 安装

```bash
# 克隆项目（含 LFS 资产）
git lfs install
git clone https://github.com/opensquilla/opensquilla.git
cd opensquilla
git lfs pull --include="src/opensquilla/squilla_router/models/**"

# 安装（推荐使用 uv）
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\install.ps1

# macOS/Linux
bash install.sh
```

### 配置

```bash
# 交互式配置向导
opensquilla onboard

# 或非交互式（推荐用于自动化）
export OPENROUTER_API_KEY="sk-..."
opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

### 运行

```bash
# 启动网关（Web UI：http://127.0.0.1:18790/control/）
opensquilla gateway run

# 交互式聊天
opensquilla chat

# 单次执行
opensquilla agent -m "你的提示词"
```

---

## 🌐 国内 LLM 配置

### DeepSeek

```bash
export DEEPSEEK_API_KEY="sk-..."
opensquilla onboard --provider deepseek --api-key-env DEEPSEEK_API_KEY
```

### 硅基流动 (SiliconFlow)

```bash
export SILICONFLOW_API_KEY="sk-..."
opensquilla onboard --provider siliconflow --api-key-env SILICONFLOW_API_KEY
```

### 智谱 AI (Zhipu)

```bash
export ZHIPUAI_API_KEY="..."
opensquilla onboard --provider zhipu --api-key-env ZHIPUAI_API_KEY
```

### 月之暗面 (Moonshot)

```bash
export MOONSHOT_API_KEY="sk-..."
opensquilla onboard --provider moonshot --api-key-env MOONSHOT_API_KEY
```

---

## 📚 文档

- [完整文档](docs/README.md)
- [CLI 命令](docs/cli.md)
- [配置指南](docs/configuration.md)
- [功能说明](docs/features.md)
- [贡献指南](docs/contributing-docs.md)

---

## 🔧 国内镜像加速

如遇网络问题，可使用国内镜像：

```bash
# 使用阿里云 uv 镜像
export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"

# 安装
OPENSQUILLA_INSTALL_INDEX="https://mirrors.aliyun.com/pypi/simple/" bash install.sh
```

---

## 🤝 贡献

欢迎各种形式的贡献 — Bug 报告、功能建议、文档改进、新的提供商/渠道适配器、技能和核心运行时工作。

打开 [Issue](https://github.com/opensquilla/opensquilla/issues) 或提交 [Pull Request](https://github.com/opensquilla/opensquilla/pulls)。

---

## 📄 许可证

Apache License 2.0 - 详见 [LICENSE](LICENSE) 文件

---

## 🌟 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=OpenSquilla/opensquilla&type=Date)](https://star-history.com/#OpenSquilla/opensquilla&Date)

---

**English** | [简体中文](README.zh-CN.md)
