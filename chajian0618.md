# OpenSquilla · Coding 模式 + code-task 插件 — 部署与使用说明（chajian0618）

> 给同事的交接文档：我们在 OpenSquilla 上做了什么、怎么**直接在服务器上用**、将来怎么**迁到 Mac 出 `.dmg`**、怎么用 **Web UI**、以及**现在实现了哪些功能**。
>
> 对应代码：分支 `feature/codetask`，最新提交 **`09d094ca`**。

---

## 1. 一句话说明

OpenSquilla 是一个微内核 AI agent 运行时（Web UI / CLI / 聊天渠道共用同一套 turn loop，自带模型路由、记忆、沙箱、联网搜索，版本 0.3.1）。

我们在它上面加了一套 **“coding 模式 + code-task 插件”**：

- 打开 **coding 开关**后，主 agent 自己的写代码工具被禁用，所有“改代码 / 建 App”的活**强制走 code-task** 这个带验证闭环的流程；
- code-task 既能在**真实仓库里改 bug / 加功能**（红→绿→回归），也能**从 0 建一个 Electron 桌面 App** 并验证它真能构建、打包；
- build 模式**按宿主平台出安装包**：macOS 出 `.dmg`、Windows 出 `.exe`、Linux 出 `.AppImage`。要 `.dmg` 就得在 **Mac** 上跑（macOS 的 `.dmg` 只能在 Mac 上构建）。

---

## 2. 我们具体做了什么（功能背景）

1. **coding 模式硬闸门**
   打开 coding 开关后，主 agent 的写工具（`write_file` / `edit_file` / `apply_patch` / `execute_code` / `git_commit` / `create_csv|pdf|pptx|xlsx`）在该会话里被**禁用**。于是它“想改代码就只能”去调用 code-task 插件，而不是在聊天里随手写文件。**保证每次代码改动都经过 code-task 的验证闭环。** 关掉开关就是普通 agent，可在会话里直接写。

2. **code-task 插件**（`src/opensquilla/contrib/codetask`）
   把目标仓库克隆到一个独立运行目录，派一个子 agent 在里面干活，收集补丁，再跑验证。两种验证模式：
   - **red-green（默认）**：先写一个会失败的验收测试（red）→ 改到它通过（green）→ 跑回归确认没引入新失败。适合“真实仓库里改 bug / 加功能”，支持本地路径仓库或 GitHub issue。
   - **build（给“从 0 建 / 改 App”）**：跑一张固定检查单 `npm ci → npm run build → electron-builder 打包`，`state=verified` 表示这个 App 真能装依赖、构建、打包。配套一份从零脚手架（Electron + Vite + React）的提示词。

3. **edit 模式（build 的延伸：迭代改 App）**
   对**已经建好的 App** 做追加/修改（如“加一个 couple 板块”“主色换成蓝色”），规则是**只改该改的文件**、不重新脚手架、改完仍要能 build，并把改动**写回 App 仓库**，下次迭代接着改。

4. **多平台安装包（最新，`09d094ca`）**
   build 模式的打包步骤按**宿主平台**各自出自己平台的安装包，每个平台只能在该平台上构建：
   - **macOS** → `electron-builder --mac dmg`（无签名、确定性，`CSC_IDENTITY_AUTO_DISCOVERY=false`）→ **`.dmg`**
   - **Windows** → `electron-builder --win nsis` → **`.exe`** 安装器
   - **Linux** → `electron-builder --linux AppImage` → **`.AppImage`**（自包含，免装 dpkg/rpm 工具链）

   要点：
   - 钉死单个目标（`dmg`/`nsis`/`AppImage`），避免触发 App 自配的 deb/snap/rpm 等需要额外工具链、在干净机器上会失败的目标；
   - 产物**全树查找**（输出目录可能是 `dist/` 也可能是 `release/`），并排除 `*-unpacked` 目录；多架构会产多个包，**全部记录**；
   - 打包退出 0 但**没产出安装包 → 判 FAILED**（不会"假成功"）；
   - ⚠️ **行为变化**：以前非 mac 宿主是 `--linux --dir`（只验证不出包），现在 **Linux 会真出 `.AppImage`**，首次构建要**联网下载 appimagetool**——离线/受限的 Linux 机器可能在这一步失败。**macOS 行为不变（仍 `.dmg`）。**

5. **运行可观测 + 鲁棒性（`ca6d8e16`）**
   - **空仓库可一步建**：对一个空/未初始化的源仓库也能 build-from-scratch；
   - **run 心跳/可见性**：code-task 在运行目录写 `status.json` 心跳、CLI 启动时报出运行目录，让观察者看运行目录、**别把"故意空着的源仓库"误读为卡死，也别去 kill/重启正在跑的 run**；
   - **模糊才反问**：请求只是个大类时才问 1–2 个澄清问题，否则用合理默认直接开干；
   - app_build 提示词改成**大批量写文件**、尽早落一个可构建脚手架+lockfile，减少多轮往返。

6. **coding 模式下 `process(wait)` 默认 1 小时**（`f9534aa3`）：让一次等待覆盖完整的 code-task 运行，避免中途超时误杀正在建 App 的子任务。

> **SWE-bench 不受 coding 闸门影响** —— coding 闸门只 gate `code-task` 这一个 skill。SWE-bench 是另一个独立的 bundled skill（见 §10），跑 benchmark 实例用，需要 Docker；`a31906d3` 给它加了 **Docker 守护进程预检**（装了 docker 但没启 → 提示"启动 Docker"，不再深处报错）。

---

## 3. 一个任务怎么流转（建 App 出安装包为例）

```
用户在 Web UI Chat（已打开 coding 开关）说：“做一个 XX 桌面 App，本地数据、无后端”
        │
        ▼
主 agent 发现自己没有写工具 → 调用
   opensquilla code-task solve --repo <App仓库> --task "..." --verification-mode build
        │
        ▼
code-task 克隆仓库 → 子 agent 用 Electron+Vite+React 建/改 App → 收集补丁
   （运行期写 status.json 心跳；观察者看运行目录）
        │
        ▼
跑 build 检查单：npm ci → npm run build → electron-builder（按宿主平台）
   · macOS  → 产出 dist/xxx.dmg
   · Windows→ 产出 xxx.exe
   · Linux  → 产出 xxx.AppImage
        │
        ▼
回写结果：state=verified、installer=<安装包路径>（迭代时还会把改动 commit 回 App 仓库）
```

---

## 4. 同事在服务器上直接上手（当前最常用）

服务器上网关已在跑：`127.0.0.1:18791`，**coding 模式已开**。环境在 `/opt/opensquilla-dev-env`，仓库在 `/home/ZhengMY/opensquilla`。

**方式 A — 用 Web UI（推荐）**：在自己电脑上 SSH 进服务器时带**端口转发**，再用本机浏览器打开：

```sh
ssh -L 18791:127.0.0.1:18791 root@47.88.93.207
# 然后浏览器打开：
http://127.0.0.1:18791/control/
```

进 **Chat** 就能用，coding 开关已开（右上角 toggle，要纯聊天就关掉），直接发任务即可。

**方式 B — 命令行（在服务器的 SSH 会话里直接跑）**：

```sh
cd /home/ZhengMY/opensquilla
/opt/opensquilla-dev-env/bin/python3 -m opensquilla.cli.main \
    code-task solve --repo <仓库路径或URL> --task "做一个记事本 App" --verification-mode build
```

> 服务器是 **Linux**，build 模式产出的是 **`.AppImage`**（不是 `.dmg`）；要 `.dmg` 必须到 Mac 上跑（见 §5）。

**如果网关没在跑了**（比如重启过），重新拉起：

```sh
cd /home/ZhengMY/opensquilla
export OPENROUTER_API_KEY="sk-or-..."        # provider key 要在环境里
nohup setsid /opt/opensquilla-dev-env/bin/python3 -m opensquilla.cli.main \
    gateway run --listen 127.0.0.1 --port 18791 > /tmp/gw_18791.log 2>&1 < /dev/null &
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18791/control/   # 期望 200
```

> 默认绑 `127.0.0.1`（只本机可达，安全）。**不要**随手绑 `0.0.0.0` 暴露公网——这个网关是 bypass 权限的 agent，拿到入口的人能在服务器上以 root 跑任意命令；要对外必须配 `[auth] mode="token"` 并在云安全组限制来源 IP。

---

## 5. 将来部署到 Mac（专门为了出 `.dmg`）

只有 macOS 能构建 `.dmg`。要在 Mac 上跑这套：

### 5.1 前置依赖

| 依赖 | 用途 | 安装 |
|---|---|---|
| Python 3.12+ | 跑 OpenSquilla | uv 可自带；或 `brew install python@3.12` |
| uv | 建虚拟环境 / 装依赖 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git + Git LFS | 拉源码 + 模型路由权重 | `brew install git git-lfs` |
| Node.js 18+（建议 20/22） | code-task 建/打包 Electron App | `brew install node` |
| Xcode Command Line Tools | 出 `.dmg`（electron-builder 需要） | `xcode-select --install` |
| OpenRouter API Key（或其它 provider） | LLM 调用 | 环境变量 `OPENROUTER_API_KEY` |

> **务必原生运行，不要用 Docker。** Docker 镜像是 Linux，打不出 macOS 的 `.dmg`；只有原生跑才能让 `electron-builder --mac` 工作。

### 5.2 拿源码（关键：功能在分支里，不在官方发行版里）

官方 `uv tool install opensquilla` 装的是 0.3.1 发行版，**不含**我们的改动；而且 `feature/codetask` **没有推到任何远端**（服务器的 `origin` 指向公开上游 GitHub），所以必须**从服务器直接搬**。最省事的方式（连 git 历史 + LFS 模型一起搬）：

```sh
# 在目标机上执行（把 <key> 换成你的 pem）
rsync -avz --exclude node_modules --exclude __pycache__ \
  -e "ssh -i <key>" \
  root@47.88.93.207:/home/ZhengMY/opensquilla/ ./opensquilla/
cd opensquilla && git status        # 应在 feature/codetask @ 09d094ca
```

如果走 git bundle：`git bundle create full.bundle --all` → scp → `git clone full.bundle` → `git checkout feature/codetask` → 再 `git lfs pull`（bundle 不含 LFS 大文件，要单独拉或拷 `.git/lfs/objects`）。**因为有模型权重是 LFS，rsync 整目录最省心。**

搬过去后建环境 —— **关键避坑（同事就栽在这）**：

> ⚠️ **千万别用系统 `pip install -e .`**。OpenSquilla 要求 Python ≥ 3.12；很多机器的系统 Python 是 3.10/3.11，`pip install` 会失败、或装出一个**坏的 `opensquilla`**，于是 coding 模式下 agent 会**偷偷退化成手工改文件**（失去 code-task 的隔离/验证/提交）。
>
> **正确做法：用 uv 装** —— uv 会自带一个独立的 3.12，跟系统 Python 是几无关。

```sh
git lfs install
git lfs pull --include="src/opensquilla/squilla_router/models/**"

# 推荐：用仓库自带的安装脚本（已固化：uv 钉 --python 3.12；系统 python<3.12 会明确报错而非静默装坏；装后自检）
bash scripts/install_source.sh

# 或开发模式（在仓库里直接跑）：
uv python install 3.12
uv sync --extra recommended            # 按 .python-version(=3.12) 建 .venv + 装依赖
# SWE-bench 才需要： uv sync --extra swebench

# 自检：能打印帮助 = code-task 可用（运行在 3.12 上）
opensquilla code-task --help
```

> 注意：agent / 网关调 code-task 时要用**这个 venv 里的** `opensquilla`（`uv run opensquilla …` 或 `.venv/bin/opensquilla`），不是裸 `opensquilla`——否则又撞回系统 Python 那个坏入口。

### 5.3 配置 provider key

```sh
export OPENROUTER_API_KEY="sk-or-..."
uv run opensquilla onboard --provider openrouter --api-key-env OPENROUTER_API_KEY
```

（或手动 `cp opensquilla.toml.example opensquilla.toml`，在 `[llm]` 填 provider/model/key。我们服务器上用 OpenRouter，SquillaRouter 在 `deepseek-v4` / `glm-5.1` / `claude-opus` 之间按难度自动路由。）

### 5.4 启动 + 出 dmg

```sh
uv run opensquilla gateway run            # Web UI: http://127.0.0.1:18791/control/
```

进 Chat → 开 coding → 发“做一个 XX 桌面 App” → 走 build 模式 → 在 Mac 上结果里给出 `installer <.../dist/xxx.dmg>`。无签名 dmg 第一次打开：**右键 → 打开**，或先 `xattr -dr com.apple.quarantine <dmg 或 .app>`。

---

## 6. 用 Web UI

Chat 页是主战场：聊天、看工具调用、产物、审批。其它区有 Overview/Health（就绪状态、provider 状态、沙箱姿态）、Skills、Sessions、Usage（token / 花费）、Cron。

**coding 开关**：Chat 界面那个 toggle，悬浮提示是
> *“Lock this session into coding mode: code changes go through code-task. Off makes code-task unavailable.”*

打开 → 该会话 agent 的写工具被禁、代码任务一律走 code-task；关掉 → 普通 agent。

**迭代改 App**：建好后接着说“主色换成蓝色 / 加一个 XX 板块”，走 edit 模式，只改相关文件、重新出安装包。

---

## 7. 命令行用法（进阶）

```sh
# 真实仓库里改代码（red-green 验证）
opensquilla code-task solve --repo /path/to/repo --task "修复 X"

# 从 0 建 / 迭代改一个 Electron App（build 验证；按宿主出 dmg/exe/AppImage）
opensquilla code-task solve --repo /path/to/app-repo \
     --task "做一个记事本 App" --verification-mode build
```

主要参数：`--repo`（git URL 或本地路径，必填）、`--task` / `--task-file` / `--issue`（任务来源三选一）、`--verification-mode red-green|build`（默认 red-green）、`--base`（起始 ref）、`--timeout`（默认 1800s）、`--json`（结果输出 JSON）。

SWE-bench（独立 skill）：

```sh
opensquilla swebench solve <instance_id> --dataset verified --json   # 需 Docker + [swebench] extra
```

---

## 8. 验证 / 跑测试

```sh
# code-task 插件自己的测试：119 个全过
PYTHONPATH=src uv run python -m pytest tests/test_contrib/test_codetask/ -q

# 整套回归
PYTHONPATH=src uv run python -m pytest -q
```

整套回归里有**少量预存失败**（与本工作无关、环境相关：meta-skill webpage 那组、shell 进程隔离那组，共 18 个），它们在迁移前的基线里就存在。判断“有没有引入新问题”看的是：**这些之外是否仍全绿**。我们每次改完都跑过整套回归，确认对齐基线（**0 新增失败**：18 failed / 6640 passed）。

---

## 9. 当前服务器现状（参照）

- 机器 `47.88.93.207`，仓库 `/home/ZhengMY/opensquilla`，分支 `feature/codetask`（HEAD **`09d094ca`**）。
- Python 环境：`/opt/opensquilla-dev-env`（uv 管的 cpython 3.12 venv）。
- 实际跑法：
  ```sh
  /opt/opensquilla-dev-env/bin/python3 -m opensquilla.cli.main gateway run --listen 127.0.0.1 --port 18791
  ```
  Web UI：`http://127.0.0.1:18791/control/`（默认 `auth=none`，只绑本机；对外访问参见 §4 的安全提醒）。
- Node `v22.22.2` / npm `10.9.7` 已装。Linux 上 build 模式现在产 **`.AppImage`**；要 `.dmg` 到 Mac 上跑。

---

## 10. SWE-bench skill 说明（与 coding 模式的关系）

- `src/opensquilla/skills/bundled/swe-bench/SKILL.md` —— 一个 bundled skill，能被“跑一道 SWE-bench 题 / run django__django-16429”这类话**意图触发**，也有 CLI（`opensquilla swebench solve …`），实现于 `src/opensquilla/contrib/swebench/`。
- 作用：对一道 SWE-bench 实例端到端测评——拉官方 Docker 镜像 → 起容器 → 跑 agent 解 issue → 收补丁 →（可选 `--evaluate`）判是否 `resolved`。
- 前置：Docker CLI + 守护进程在跑 + `OPENROUTER_API_KEY` + `opensquilla[swebench]` extra（`uv sync --extra swebench`）。
- **和 coding 模式无关**：`CODING_MODE_SKILLS` 里只有 `code-task`，swe-bench 不在其中，开不开 coding 都不变。
- 来源说明：swe-bench harness + skill 是**本团队在这个分支上加的**（早于 coding 模式、独立功能），**不在官方上游 / 0.3.1 发行版里**（SKILL.md 里标的 `origin: opensquilla-original` 是写上去的标，不代表上游真有）。

---

## 11. 提交历史（feature/codetask，新→旧）

| 提交 | 内容 |
|---|---|
| `09d094ca` | build 模式按宿主出 **mac/win/linux 三平台安装包**（钉单目标、全树找产物、无包即 FAILED）；**Linux 改为产 `.AppImage`** |
| `a31906d3` | swebench CLI 预检 Docker **守护进程**是否在跑 + 安装提示改 `uv sync --extra swebench` |
| `ca6d8e16` | 空仓库一步构建、dmg 全树发现、run 心跳/可见性（status.json，别误杀）、模糊才反问、大批量写文件 |
| `af6f4813` | （Mac 部署加固前身）build 模式产 `.dmg`、记录所有包、无包即 FAILED |
| `7d5c0f9b` | build 模式支持对已建 App 的迭代编辑，改动写回仓库 |
| `f9534aa3` | coding 模式下 `process(wait)` 默认 1 小时 |
| `a598683e` | coding 模式工具闸门 + build 验证模式 |
| `fe3e861c` | code-task 工具 deny-list + 给 SWE-bench 开启 SquillaRouter |
