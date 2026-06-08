# OpenSquilla 国内镜像安装指南

## 问题

国内用户在安装 OpenSquilla 时可能遇到以下问题：

1. **GitHub 访问慢** - 克隆仓库和下载资源缓慢
2. **PyPI 访问受限** - Python 包下载失败
3. **uv 安装脚本访问慢** - uv 安装脚本加载缓慢

## 解决方案

### 方法一：使用国内镜像（推荐）

#### 1. 设置 uv 镜像

```bash
# 设置 uv 镜像环境变量
export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
export UV_TOOL_DIR="${HOME}/.uv-tools"
```

#### 2. 使用镜像安装

```bash
# 使用阿里云 PyPI 镜像安装
OPENSQUILLA_INSTALL_INDEX="https://mirrors.aliyun.com/pypi/simple/" bash install.sh
```

#### 3. 配置持久化

将以下内容添加到 `~/.bashrc` 或 `~/.zshrc`：

```bash
# OpenSquilla 国内镜像配置
export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
export OPENSQUILLA_INSTALL_INDEX="https://mirrors.aliyun.com/pypi/simple/"
```

---

### 方法二：使用 Gitee 镜像（推荐用于克隆）

#### 1. 从 Gitee 克隆

如果 GitHub 访问缓慢，可以使用 Gitee 镜像：

```bash
# 方法 A：使用 GitHub 代理加速
git clone https://mirror.ghproxy.com/https://github.com/opensquilla/opensquilla.git

# 方法 B：从 Gitee 导入（如果有镜像）
# 访问 https://gitee.com/mirrors/opensquilla
```

#### 2. 配置 Git 代理

```bash
# 设置 GitHub 代理（如果你有代理）
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy https://127.0.0.1:7890

# 或只为 GitHub 设置代理
git config --global http.https://github.com.proxy http://127.0.0.1:7890
```

---

### 方法三：手动下载安装包

#### 1. 下载 Wheel 文件

访问 [OpenSquilla Releases](https://github.com/opensquilla/opensquilla/releases) 下载最新的 `.whl` 文件。

如果 GitHub 下载缓慢，可以使用镜像：

```bash
# 使用 GitHub 代理加速下载
wget https://mirror.ghproxy.com/https://github.com/opensquilla/opensquilla/releases/download/v0.3.0/opensquilla-0.3.0-py3-none-any.whl
```

#### 2. 本地安装

```bash
# 使用 uv 本地安装
uv tool install --python 3.12 --force --reinstall-package opensquilla ./opensquilla-0.3.0-py3-none-any.whl

# 或使用 pip
pip install --upgrade ./opensquilla-0.3.0-py3-none-any.whl
```

---

## 国内可用的 PyPI 镜像

| 镜像 | URL | 说明 |
|------|-----|------|
| **阿里云** | https://mirrors.aliyun.com/pypi/simple/ | 推荐，速度快 |
| **清华大学** | https://pypi.tuna.tsinghua.edu.cn/simple/ | 教育网友好 |
| **豆瓣** | https://pypi.douban.com/simple/ | 备用 |
| **中科大** | https://pypi.mirrors.ustc.edu.cn/simple/ | 备用 |

---

## uv 国内安装

### 方法 A：使用国内镜像安装 uv

```bash
# 使用清华镜像安装 uv
export INSTALL_URL="https://cdn.jsdelivr.net/gh/astral-sh/uv/0.5.1/install-installer.sh"
curl -LsSf "${INSTALL_URL}" | sed 's|https://astral.sh/uv/install.sh|https://mirrors.aliyun.com/pypi/simple/|' | sh
```

### 方法 B：手动下载 uv

```bash
# 使用 GitHub 代理下载 uv
wget https://mirror.ghproxy.com/https://github.com/astral-sh/uv/releases/latest/download/uv-installer-linux-x86_64.tar.gz
tar -xzf uv-installer-linux-x86_64.tar.gz
./uv-installer/install.sh
```

---

## 完整安装示例（国内用户）

```bash
#!/bin/bash
# 国内用户一键安装脚本

# 1. 设置镜像
export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple/"
export OPENSQUILLA_INSTALL_INDEX="https://mirrors.aliyun.com/pypi/simple/"

# 2. 克隆项目（使用 GitHub 代理）
git clone https://mirror.ghproxy.com/https://github.com/opensquilla/opensquilla.git
cd opensquilla

# 3. 拉取 LFS 文件
git lfs install
git lfs pull --include="src/opensquilla/squilla_router/models/**"

# 4. 安装
bash install.sh

# 5. 配置
opensquilla onboard
```

---

## 常见问题

### Q: 下载速度慢怎么办？

1. 使用 GitHub 代理：`https://mirror.ghproxy.com/`
2. 配置 Git 代理
3. 使用 Gitee 镜像（如有）

### Q: pip 安装失败怎么办？

1. 切换到国内 PyPI 镜像
2. 使用 `--index-url` 参数
3. 手动下载 wheel 文件

### Q: uv 安装脚本无法访问？

1. 使用 `pip install uv` 替代脚本安装
2. 手动下载 uv-installer
3. 使用国内 PyPI 镜像

---

## 验证安装

```bash
# 检查版本
opensquilla --version

# 检查健康状态
opensquilla health

# 运行测试
opensquilla agent -m "你好，请用中文回复"
```

---

## 相关资源

- [OpenSquilla GitHub](https://github.com/opensquilla/opensquilla)
- [阿里云 PyPI 镜像](https://developer.aliyun.com/mirror/)
- [清华大学 PyPI 镜像](https://mirrors.tuna.tsinghua.edu.cn/help/pypi/)
- [GitHub 代理加速](https://mirror.ghproxy.com/)
