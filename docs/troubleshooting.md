# 故障排查指南

本文档帮助你诊断和解决 OpenSquilla 使用中的常见问题。

## 🔍 快速诊断

### 运行健康检查

```bash
opensquilla doctor
opensquilla doctor --json
opensquilla gateway status
```

健康检查会验证：
- ✅ 配置文件完整性
- ✅ API Key 有效性
- ✅ LLM 提供商连接
- ✅ 模型可用性
- ✅ 记忆系统状态
- ✅ MCP 服务器连接

Web UI 健康视图：http://127.0.0.1:18791/control/

---

## 📦 安装问题

### 问题：opensquilla 命令未找到

**症状：**
```bash
opensquilla --version
# command not found: opensquilla
```

**解决方案：**

```bash
# 更新 shell 配置
uv tool update-shell

# 或打开新终端窗口

# 检查可执行文件位置
command -v opensquilla  # Linux/macOS
where.exe opensquilla  # Windows PowerShell
```

### 问题：安装脚本失败

**症状：**
```bash
bash install.sh
# Error: uv not found
```

**解决方案：**

```bash
# 方法 1：手动安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 方法 2：使用 pip
pip install uv

# 方法 3：国内镜像
export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
curl -LsSf https://mirrors.aliyun.com/pypi/simple/ | sh
```

### 问题：Git LFS 文件下载失败

**症状：**
```bash
git lfs pull
# Error: failed to fetch some objects
```

**解决方案：**

```bash
# 1. 确认 LFS 已安装
git lfs install

# 2. 检查 LFS 文件列表
git lfs ls-files

# 3. 手动指定下载
git lfs pull --include="src/opensquilla/squilla_router/models/**"

# 4. 使用 GitHub 代理加速
git config --global http.proxy http://127.0.0.1:7890
```

---

## 🔑 配置问题

### 问题：提供商未配置

**症状：**
```
Error: Provider not configured
```

**解决方案：**

```bash
# 1. 运行配置向导
opensquilla onboard

# 2. 检查已配置提供商
opensquilla providers list

# 3. 配置提供商
opensquilla providers configure openrouter

# 4. 使用环境变量
export OPENAI_API_KEY="sk-..."
opensquilla configure provider --provider openai --api-key-env OPENAI_API_KEY
```

### 问题：API Key 无效

**症状：**
```
Error: Invalid API key for provider: openai
```

**解决方案：**

```bash
# 1. 验证 API Key
echo $OPENAI_API_KEY  # 确认环境变量已设置

# 2. 重新配置
opensquilla onboard --provider openai --api-key-env OPENAI_API_KEY

# 3. 检查 API Key 格式
# OpenAI: sk-...
# Anthropic: sk-ant-...
# DeepSeek: sk-...
# Groq: gsk_...

# 4. 测试 API Key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

---

## 🤖 运行时问题

### 问题：网关未运行

**症状：**
```
Error: Gateway is not running
```

**解决方案：**

```bash
# 1. 启动网关
opensquilla gateway run

# 2. 或使用托管后台进程
opensquilla gateway start --json
opensquilla gateway status

# 3. 访问 Web UI
# http://127.0.0.1:18791/control/
```

### 问题：端口已被占用

**症状：**
```
Error: Port 18791 already in use
```

**解决方案：**

```bash
# 1. 使用其他端口
opensquilla gateway run --port 18792

# 2. 或停止托管网关
opensquilla gateway stop

# 3. 检查端口占用
# Linux/macOS
lsof -i :18791
# Windows
netstat -ano | findstr 18791
```

### 问题：Agent 响应缓慢

**可能原因和解决方案：**

```bash
# 1. 网络延迟 - 检查连接
ping api.openai.com

# 2. 模型速度 - 切换到更快的模型
opensquilla configure provider --provider groq --model llama-3.1-8b-instant

# 3. 路由问题 - 使用推荐路由
opensquilla configure router --router recommended

# 4. 开启诊断
opensquilla diagnostics on
```

### 问题：工具被拒绝

**症状：**
```
Error: Tool execution denied: file_write
```

**解决方案：**

```bash
# 1. 检查沙箱状态
opensquilla sandbox status

# 2. 运行诊断
opensquilla doctor

# 3. 选择权限模式
opensquilla agent --permissions restricted -m "只读操作"
opensquilla agent --permissions full -m "受信任的本地自动化"
```

---

## 🔌 MCP 问题

### 问题：MCP 服务器未连接

**症状：**
```
Error: MCP server 'github' not found
```

**解决方案：**

```bash
# 1. 检查 MCP 列表
opensquilla mcp list

# 2. 添加 MCP 服务器
claude mcp add github --scope user npx -y @modelcontextprotocol/server-github

# 3. 验证 MCP 配置
cat ~/.claude.json

# 4. 测试 MCP 连接
opensquilla mcp test github
```

---

## 🔧 高级问题

### 问题：路由依赖问题

**症状：**
```
Error: SquillaRouter failed to load
```

**解决方案：**

```bash
# 1. 禁用路由器（使用直接模型路由）
opensquilla configure router --router disabled
opensquilla gateway restart

# 2. Windows：安装 Visual C++ Redistributable
# 下载：https://aka.ms/vs/17/release/vc_redist.x64.exe
```

### 问题：搜索不工作

**症状：**
```
Error: Search failed
```

**解决方案：**

```bash
# 1. 检查搜索提供商
opensquilla search list
opensquilla search status

# 2. 使用 DuckDuckGo（无需密钥）
opensquilla configure search --search-provider duckduckgo

# 3. 使用 Brave（需要密钥）
export BRAVE_SEARCH_API_KEY="..."
opensquilla configure search --search-provider brave --api-key-env BRAVE_SEARCH_API_KEY
```

### 问题：Agent 似乎忘记旧上下文

**说明：**
长会话可能会压缩旧历史记录，这是上下文压力下的预期行为。

**解决方案：**

```bash
# 1. 检查会话
opensquilla sessions show <session-key>
opensquilla sessions export <session-key>

# 2. 如果旧文本很重要，保存在文件/记忆/导出会话中
```

### 问题：一次交互太昂贵或太慢

**解决方案：**

```bash
# 1. 使用推荐路由
opensquilla configure router --router recommended

# 2. 开启诊断
opensquilla diagnostics on
opensquilla cost

# 3. 自动化：设置限制
opensquilla agent --max-iterations 20 --timeout 600 -m "有界任务"
```

---

## 🌐 国内用户问题

### 问题：GitHub 访问缓慢

**解决方案：**

```bash
# 1. 使用 GitHub 代理
git clone https://mirror.ghproxy.com/https://github.com/opensquilla/opensquilla.git

# 2. 配置 Git 代理
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
```

### 问题：PyPI 下载缓慢

**解决方案：**

```bash
# 1. 使用国内镜像
export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"

# 2. 持久化配置
echo 'export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"' >> ~/.bashrc

# 3. 安装时指定镜像
OPENSQUILLA_INSTALL_INDEX="https://mirrors.aliyun.com/pypi/simple/" bash install.sh
```

### 问题：LLM API 访问受限

**解决方案：**

```bash
# 1. 使用国内 LLM 提供商
# DeepSeek、SiliconFlow、Moonshot、Zhipu

# 2. 配置代理
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

---

## 📞 获取帮助

### 诊断信息收集

```bash
# 生成诊断报告
opensquilla doctor > diagnostics.txt

# 查看详细日志
opensquilla logs --level DEBUG

# 导出配置
opensquilla config --export > config.json
```

### 社区资源

- 📖 [完整文档](https://docs.opensquilla.ai)
- 💬 [Discord 社区](https://discord.gg/opensquilla)
- 🐛 [Issue 追踪](https://github.com/opensquilla/opensquilla/issues)
- ✉️ [邮件支持](mailto:support@opensquilla.ai)

### 报告问题时请提供

1. OpenSquilla 版本：`opensquilla --version`
2. 操作系统：`uname -a`
3. Python 版本：`python --version`
4. 错误信息：完整错误堆栈
5. 复现步骤：最小复现示例
6. 诊断报告：`opensquilla doctor` 输出

---

**无法解决问题？** 请访问 [GitHub Issues](https://github.com/opensquilla/opensquilla/issues) 搜索或提交问题。

---

[文档首页](README.md) · [产品指南](../README.product.md) · [改进此页](contributing-docs.md) · [报告文档问题](https://github.com/opensquilla/opensquilla/issues/new?template=docs_report.yml)
