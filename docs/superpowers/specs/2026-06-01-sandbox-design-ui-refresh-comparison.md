# OpenSquilla 沙箱优化前后对比

日期：2026-06-01

本文对比的是：

- **优化前**：当前 OpenSquilla 沙箱和权限模型的现状。
- **优化后**：`2026-05-29-sandbox-run-mode-design.md` v2 设计落地后的目标状态。

本文只关注沙箱优化本身的产品和技术差异：现在的问题是什么，优化后怎么变好。

## 一句话结论

优化前，OpenSquilla 的最大问题不是“没有沙箱”，而是 **审批、bypass、host exec、沙箱边界被揉在一起**。用户点一个看起来像“少问我”的按钮，实际可能让命令绕过沙箱直接跑到宿主机。

优化后，系统会变成三层清晰模型：

1. **Run Mode** 决定整体运行姿态。
2. **Run Context** 保存当前会话的 workspace、mounts、domains、grants。
3. **Operation Profile** 判断每次工具调用到底在做什么。

最终效果是：默认仍在沙箱里工作；需要扩大边界时清楚询问；只有用户明确选择 `Full Host Access` 或沙箱失败后的 `Host Once`，才会跑到宿主机。

## 1. 执行模式语义

**优化前不足**

当前模型里有 `off`、`on`、`bypass`、`full`、`elevated` 这些词。它们同时表达三件事：

- 要不要问用户。
- 要不要绕过沙箱。
- 要不要绕过敏感路径检查。

这导致用户很难判断自己到底开了什么权限。比如 `bypass` 听起来像“跳过审批弹窗”，但当前 shell 执行逻辑里它也会绕过 sandbox backend，变成 host exec。

**优化后设计**

只暴露三个用户能理解的 Run Mode：

- `Standard-Sandbox`
- `Trusted-Sandbox`
- `Full Host Access`

它们分别对应：

| Run Mode | 执行位置 | 审批行为 |
| --- | --- | --- |
| `Standard-Sandbox` | Sandbox | 普通风险会问 |
| `Trusted-Sandbox` | Sandbox | 普通审批少问，但边界扩展仍问 |
| `Full Host Access` | Host | 不逐条询问 |

**优化后优势**

用户不需要理解内部的 `elevated`。看名字就能知道：

- 前两个仍然是沙箱。
- 只有 `Full Host Access` 是宿主机。

这直接消除“我只是想少点确认，结果命令裸跑宿主机”的误解。

## 2. Bypass 行为

**优化前不足**

当前 Chat 里虽然显示的是 `Execution mode`，但点击后仍然是启用 `/elevated bypass`。确认文案也明确说它允许 host execution。Approvals 页面和全局 approval modal 里还有 `Bypass Approvals` 按钮，它会传 `elevatedMode=bypass`。

结果是 bypass 变成一条绕过沙箱的捷径。

**优化后设计**

旧保存状态里的 bypass 只在迁移边界上解释为 `Trusted-Sandbox`：

- 跳过普通审批。
- 继续在沙箱中执行。
- 不跳过新挂载、新域名、敏感路径、Host Once 等边界决策。

CLI 不再把 `bypass` 作为正式命令或别名。因为旧 `sandbox bypass` 的真实含义是关掉 runtime sandbox，新设计里的 `trust` 则是仍然沙箱执行。继续复用这个词会让用户和脚本误判安全含义。

`Bypass Approvals` 不再作为普通 approval 主按钮出现。如果保留“少问我”的入口，也必须叫成 `Switch to Trusted-Sandbox`，并明确说明仍然沙箱执行。

**优化后优势**

用户可以获得更顺滑的体验，但不会因为少点一次确认就丢掉沙箱隔离。

## 3. Host 执行入口

**优化前不足**

host execution 有多个入口：

- `/elevated on`
- `/elevated bypass`
- `/elevated full`
- 普通 approval 通过后设置本次 host 权限
- approval modal 里的 `Bypass Approvals`
- session elevated mode

入口越多，越难判断一个命令为什么跑到了宿主机。

**优化后设计**

host execution 只剩两种合法入口：

1. `Full Host Access`
   - 用户主动选择全局宿主机访问。
   - 不逐条询问。
   - UI 必须明显提示高风险。

2. `Host Once`
   - 先在沙箱里跑过。
   - 失败原因像沙箱限制。
   - 用户只批准这一次。
   - 与原操作指纹绑定，用完即失效。

**优化后优势**

host 执行变得可审计、可解释、可控。用户不会在普通审批里被引导去绕过沙箱。

## 4. 普通审批

**优化前不足**

当前普通 approval 通过后，shell 层会把这次调用提升成 host execution。也就是说，“同意这个危险命令”会被解释成“允许这个命令在宿主机执行”。

这两个含义不应该绑定。

**优化后设计**

普通 approval 只回答：

> 这个操作是否可以在当前 resolved policy 下继续？

如果当前 Run Mode 是 `Standard-Sandbox` 或 `Trusted-Sandbox`，通过审批后仍然应该在沙箱中执行。

普通 approval 选项：

- Approve Once
- Always Allow This Type
- Deny
- Deny This Type

不会出现 `Run on Host`。

**优化后优势**

审批变成“是否允许这个操作”，不是“是否切到宿主机”。权限含义更小，风险更低。

## 5. Host Once

**优化前不足**

当前已经有 backend denial escalation 的路径，但整体语义不够产品化。用户看不到清晰的“先沙箱失败，再单次宿主机补救”的流程。

**优化后设计**

Host Once 是一个明确的失败恢复动作：

1. 先尝试沙箱执行。
2. 后端判断失败是否由沙箱限制导致。
3. 如果适合，弹出 Host Once 请求。
4. 用户选择 `Run on Host Once` 或 `Keep Blocked`。
5. 批准只对原命令、原参数、原操作画像有效。

**优化后优势**

可用性保留了，但系统不会一开始就诱导用户关闭沙箱。

## 6. Chat 输入框功能键

**优化前不足**

当前 composer gear 里有：

- `Execution mode`
- `Squilla Router`
- `Visual effects`

它的问题不是缺少更多入口，而是没有清晰的三档 Run Mode。`Execution mode` 实际还是旧 bypass toggle。这个功能键应该继续保持轻，不应该再塞入 Workspace、Mounts、Domains 或完整 Sandbox 页面跳转。

**优化后设计**

composer gear 保持轻量，但内容变成：

- `Run Mode`
- `Squilla Router`
- `Visual effects`

其中：

- `Run Mode` 是唯一放在聊天输入框功能键里的沙箱控制。
- `Squilla Router` 保留现有产品入口。
- `Visual effects` 是前端偏好，不参与沙箱。

Workspace 修改、挂载目录、Allowed Domains、doctor/explain 和规则管理全部放到 `Control -> Sandbox` 页。聊天功能键不提供 `Workspace` 或 `Open Sandbox...`。

**优化后优势**

用户在发下一条消息前能快速确认：

- 当前是不是沙箱。

同时不会把 workspace、挂载、域名、doctor、规则管理都塞进聊天输入框。

## 7. Topbar 职责

**优化前不足**

现在 Chat 已经把 session chip、run status、context warning 放到全局 topbar center。这个区域如果继续被塞进更多配置项，会很快变乱。

**优化后设计**

topbar center 只做只读会话状态：

- 当前 session
- run status
- context warning
- 可选的 Run Mode 状态 chip

Run Mode 的快捷修改在 composer gear；Workspace、Mounts、Domains 的修改在 Sandbox 页。

**优化后优势**

界面层次清楚：

- topbar 是状态。
- composer gear 是快捷设置。
- Sandbox 页是完整管理。

## 8. Sandbox 侧边栏页面

**优化前不足**

现在没有专门的 Sandbox 页面。用户要理解沙箱状态，需要在 Config、Health、Approvals、Chat 之间来回找：

- Config 里是底层开关。
- Health 里有 doctor。
- Approvals 里有审批。
- Chat 里有 execution mode。

这些信息分散，用户很难知道“沙箱到底是不是生效了”。

**优化后设计**

新增 `Control -> Sandbox` 页面，放在 Health 后面。

页面分区：

- Status
- Workspace
- Mounts
- Allowed Domains
- Rules & Activity

这个页面用标准 view wrapper 渲染，离开 Chat 时会清掉 Chat 专属 topbar 内容。

**优化后优势**

用户有一个稳定入口回答：

- 沙箱后端是否可用。
- 当前 workspace 是什么。
- 挂载了哪些目录。
- 允许了哪些域名。
- 最近为什么被拦。
- 哪些规则可以撤销。

## 9. Workspace

**优化前不足**

当前 workspace 主要来自配置或默认目录。用户在对话中说“看 `/home/usr1/1`”时，系统没有产品化路径去问“要不要把这个目录加入沙箱可见范围”。

如果直接 host exec，风险太大；如果直接失败，体验又差。

**优化后设计**

Workspace 变成 session Run Context 的一部分：

- Sandbox 页可以切换当前 workspace。
- Sandbox 页可以管理 recent workspaces。
- 修改后下一次工具调用生效，不需要重启 gateway。

**优化后优势**

用户能在 Sandbox 设置里切项目目录；agent 也能在沙箱里访问用户指定的项目，而不是靠 host bypass。聊天输入框保持专注，不承担项目管理职责。

## 10. 外部路径访问

**优化前不足**

用户输入外部路径时，系统没有明确的 Path Access Request。模型或工具要么失败，要么倾向于找 host 执行绕路。

**优化后设计**

当用户明确要求查看或修改沙箱外路径，比如 `/home/usr1/1`：

1. 先判断路径是否在当前 workspace 或已挂载目录内。
2. 不在的话，后端校验路径。
3. 安全则询问是否加入挂载。
4. 看/分析默认只读。
5. 明确修改才提供读写。
6. 加挂载后继续沙箱执行。

**优化后优势**

系统优先扩大沙箱可见范围，而不是绕开沙箱。用户想处理外部项目时，体验更自然，风险也更小。

## 11. 挂载目录安全校验

**优化前不足**

OpenSquilla 已经有 extra mounts 概念，但如果挂载校验不够强，用户或配置可能把 `.ssh`、云凭证、Docker socket、系统目录挂进沙箱。

这等于给沙箱开后门。

**优化后设计**

路径校验必须跨平台、后端执行、fail closed：

- 展开 `~`
- 转绝对路径
- resolve symlink
- 检查 ancestor
- 处理大小写不敏感文件系统
- 处理 Windows drive letter
- 处理 UNC/network path
- 处理 Windows junction/reparse point
- 处理 WSL path
- 处理 macOS `/private` alias
- 处理容器内外路径映射

敏感路径默认硬拦：

- `/etc`、`/proc`、`/sys`、`/dev`
- Docker/Podman socket
- SSH/GPG
- AWS/GCP/Azure/Cloudflare credentials
- GitHub/Git credential stores
- browser profiles
- password manager stores
- keychains/private certs
- shell history/token caches

**优化后优势**

用户仍然能灵活挂载普通项目目录，但敏感凭证和系统边界不会因为配置失误暴露给 agent。

## 12. 网络访问

**优化前不足**

当前 shell/code 沙箱遇到网络问题时，主要给提示：没有网络，使用 `http_request`/`web_fetch`，或者用 bypass。这个体验容易把用户推向绕过沙箱。

同时，直接做“开全网”又违背沙箱思想。

**优化后设计**

UI 不提供 `Open Internet` 这种开关，只提供 `Allowed Domains`：

- 允许具体域名。
- 允许受控 wildcard。
- 拒绝过宽 wildcard。
- 默认拒绝 localhost、private network、metadata service。
- 重定向到未允许域名时重新拦截。
- HTTP 需要更强提醒。

第一阶段只约束 sandboxed shell/code/package-manager egress，不改现有 explicit network tool 的测试语义。

**优化后优势**

网络不是全开，而是按任务开放窄通道。用户能完成依赖安装、下载等常见工作，但数据外传风险明显降低。

## 13. Package Install Bundle

**优化前不足**

`pip install`、`npm install`、`cargo fetch`、`go mod download` 这类操作常常需要多个域名。如果每个域名都问一次，用户会被打扰到想直接关掉沙箱。

**优化后设计**

为常见包管理器提供 domain bundle：

- Python package indexes
- Node package registry
- Rust crates
- Go modules
- 必要时的 GitHub release/source download

bundle 绑定到：

- workspace
- operation kind
- package ecosystem
- sandbox execution

**优化后优势**

不会每个域名都问；也不会变成全网放行。它是一条“只为依赖安装开放”的窄通道。

## 14. Operation Profile

**优化前不足**

当前策略主要按工具名或 action tag 判断。比如 shell 可能是：

- `ls`
- `pip install`
- `rm -rf`
- `curl | sh`
- 修改系统服务

它们都是 shell，但风险完全不同。

**优化后设计**

每次工具调用先生成 Operation Profile：

- 工具是什么。
- 操作类型是什么。
- 目标路径在哪里。
- 是否需要网络。
- 是否触及敏感边界。
- 风险等级是什么。
- 识别置信度如何。

**优化后优势**

同一个工具可以按真实动作走不同策略。允许一次 `git status` 不会等于允许所有 shell。

## 15. Hints

**优化前不足**

`LevelHints` 已经存在，但使用很浅。比如 `needs_network` 没有真正变成 allowed domain 或 package bundle 的决策入口。

**优化后设计**

hints 只做分类证据，不做授权凭证：

- `needs_network` 触发域名检查。
- `writes_outside_workspace` 触发挂载或拒绝。
- `crosses_trust_boundary` 即使 Trusted 也要问。
- `high_impact` 提升风险。
- `trusted_source` 只能降低误报，不能绕过敏感边界。

**优化后优势**

hints 终于有用，但不会因为 hint 写得“可信”就自动放权。

## 16. 未识别操作

**优化前不足**

规则覆盖不了所有实际命令。复杂 shell、变量、重定向、脚本下载执行都可能让分类失败。

如果识别失败被当成普通操作，会有安全洞。

**优化后设计**

unknown 分三类：

- `unknown_normal`
- `unknown_suspicious`
- `unknown_sensitive`

识别失败不能直接低风险。遇到 sudo、curl|sh、base64 exec、凭证路径、Docker socket、metadata endpoint 等迹象时，要强询问或拒绝。

**优化后优势**

系统在不确定时保守处理，不会因为规则没写到就默认放行。

## 17. Approvals 页面和弹窗

**优化前不足**

Approvals 页和全局 approval modal 仍然提供 `Bypass Approvals`。用户在处理一个 pending request 时，很容易顺手把整个 session 推到旧 bypass/host 模式。

**优化后设计**

普通 approval 只处理当前操作：

- Approve Once
- Always Allow This Type
- Deny
- Deny This Type

`Effective execution mode` 摘要保留，但读取新的 Run Context。

如果要切 Run Mode，应通过明确的 Run Mode 控件，而不是通过某条 approval 的危险快捷按钮。

**优化后优势**

审批页面不再是绕过沙箱的入口。用户可以清楚地区分“批准这次操作”和“改变整个会话的运行模式”。

## 18. Always Allow This Type

**优化前不足**

如果 “Always Allow” 只按工具名或命令粗匹配，用户允许一次 shell 后，可能无意中放开很多不相关操作。

**优化后设计**

Always Allow 绑定 Operation Profile：

- tool
- operation kind
- target scope
- execution target
- network requirement
- workspace/session
- TTL 或作用域

**优化后优势**

用户允许的是“这类操作”，不是“这个工具从此都能干任何事”。

## 19. Doctor / Explain

**优化前不足**

Health 有 doctor，但沙箱相关状态和具体拦截原因不够集中。用户看见失败时，往往不知道是：

- 后端缺依赖。
- 网络被拦。
- 路径没挂载。
- 敏感路径被拒。
- 命令自己失败。

**优化后设计**

Doctor 负责沙箱健康：

- backend 是否可用
- 是否退化 noop
- network guard 是否可用
- mounts 是否安全
- 配置是否需要重启

Explain 负责单次决策原因：

- 为什么直接执行。
- 为什么询问。
- 为什么拒绝。
- 为什么要求挂载。
- 为什么要求域名授权。
- 为什么 Host Once 可用或不可用。

**优化后优势**

用户不是只看到“失败”，而是看到“为什么失败”和“下一步怎么修”。

## 20. Config 和 slash command 文案

**优化前不足**

Config help、`/permissions`、`/elevated` 仍然在解释旧模型：

- `on` 是 host exec with approval。
- `bypass` 是 host exec with auto approval。
- `full` 是 host exec 且跳过敏感路径。

这会和新 UI 的 Run Mode 冲突。

**优化后设计**

所有用户可见文案统一到三档：

- `Standard-Sandbox`
- `Trusted-Sandbox`
- `Full Host Access`

CLI 主命令收敛为：

- `opensquilla sandbox on`
- `opensquilla sandbox trust`
- `opensquilla sandbox full`
- `opensquilla sandbox status`
- `opensquilla sandbox reset`

旧 `/elevated` 可以保留兼容，但不作为主入口宣传。旧 `on` 不作为新模式暴露。旧 `opensquilla sandbox bypass` 不做静默 alias，而是报错并提示用户选择 `trust` 或 `full`。

**优化后优势**

用户不会在 Chat、Config、Approvals、CLI 看到四套不同说法。

## 21. 测试策略

**优化前不足**

已有 `tests/test_sandbox` 覆盖了一部分 sandbox 行为，但它没有覆盖新 Run Mode 语义，也没有防止 `Trusted-Sandbox` 被接回 host exec。

另外，开发流程如果只跑单个新测试，就可能出现“沙箱功能自己绿了，但旧的沙箱/CLI/前端入口被破坏”的情况。`/home/lrk/opensquilla/tests` 是全项目测试目录，但当前沙箱迁移不要求这个目录下所有测试都作为阻塞门槛通过。

**优化后设计**

开发门禁改成“相关矩阵必须绿，全量测试只做观察”：

1. 测试命令使用项目方式 `uv run pytest`，不是裸 `pytest`。
2. 开发前先跑沙箱相关基线：`tests/test_sandbox`、`tests/test_cli/test_sandbox_cmd.py`、`tests/test_gateway/test_chat_static_assets.py`、`tests/test_application/test_approval_rpc.py`、`tests/test_gateway/test_rpc_approvals.py`。
3. 如果开发前这个相关基线不通过，先停止沙箱开发；如果已经有自己的预备改动，就只撤回自己的改动，然后单独处理相关基线失败。
4. 全量 `uv run pytest tests` 可以作为健康快照，但不是这次沙箱迁移的阻塞门槛。它如果在 Feishu、packaging、系统依赖、live smoke 等无关区域失败，只记录，不因此停掉沙箱开发。
5. 开发中可以用 `.sandbox-tmp-tests/` 的临时测试加快反馈，临时测试不提交。
6. 每个任务结束后，必须跑该任务列出的 focused tests。
7. 实现完成后，先跑沙箱相关矩阵；相关矩阵通过后，再把重要的新沙箱测试补充到 `tests/test_sandbox/`。
8. 新增沙箱测试失败时，修实现代码，不改无关测试。

原有测试不随意改、不删、不放松断言。允许修改的旧测试只有三类：旧 CLI sandbox/bypass 语义测试、旧前端 bypass/elevated 静态测试、旧 Windows auto-noop 预期测试。沙箱新能力的测试风格跟附近测试保持一致：

- Trusted-Sandbox 永远 sandbox execution。
- Full Host Access 是唯一全局 host execution。
- `sandbox bypass` 报错并提示迁移，不修改配置。
- Trusted-Sandbox 跳过日常沙箱内确认，但新挂载、未知域名、敏感路径、可疑 unknown、Host Once 仍然询问或拒绝。
- 普通 approval 不含 Host Once。
- Host Once 只在沙箱失败后出现。
- approval 通过不等于 host execution。
- 外部路径先 Path Access Request。
- 敏感路径不能通过 symlink/junction/大小写/ancestor 绕过。
- package bundle 只能用于对应 ecosystem/workspace。
- explicit network tool 的现有测试语义保持不变。

**优化后优势**

这次改动不会靠文档记忆防回退，而是用新增测试防止以后又把 bypass 接回 host。

## 22. ROI 变化

**优化前 ROI 问题**

如果先做 backend 资源限制、seccomp、worktree 等底层能力，但不先拆清执行语义，用户仍然会通过 bypass/approval 走到 host。

底层沙箱再强，也会被产品语义绕开。

**优化后 ROI 排序**

P0：

1. 三档 Run Mode 替代 elevated/bypass。
2. CLI 收敛到 `on`、`trust`、`full`，旧 `bypass` 报错提示迁移。
3. Session Run Context 实时生效。
4. Chat composer gear 迁移到轻量 Run Mode 控制，保留 Router / Visual effects，不加入 Workspace 或 Open Sandbox。
5. Approvals 和 modal 移除旧 bypass host 入口。
6. 外部路径 Path Access Request。
7. Host Once 只在沙箱失败后出现。

P1：

1. Sandbox 页面。
2. Operation Profile + hints。
3. Allowed Domains + package bundles。
4. Doctor / Explain。

P2：

1. 资源限制、seccomp/no_new_privs 等硬隔离增强。
2. worktree/session 隔离。

P3：

1. Claude 式复杂 auto classifier。

**优化后优势**

先堵住“语义绕过沙箱”这条最大路径，再补强底层隔离。投入顺序更合理。

## 总体对比表

| 主题 | 优化前不足 | 优化后优势 |
| --- | --- | --- |
| 模式命名 | elevated/bypass/full 混杂 | 三档 Run Mode 语义清楚 |
| bypass | 少问审批等于绕过沙箱 | CLI bypass 移除；旧状态迁移为 Trusted-Sandbox |
| host exec | 多入口、难审计 | 只有 Full Host Access 和 Host Once |
| 普通 approval | 批准后可能 host 执行 | 批准后仍按当前 policy 执行 |
| Host Once | 语义不够产品化 | 沙箱失败后的一次性补救 |
| Chat gear | Execution mode 仍是旧 bypass | 只保留轻量 Run Mode 控制 |
| Sandbox 页面 | 没有统一管理入口 | Control -> Sandbox 集中管理 |
| Workspace | 不够灵活 | 在 Sandbox 设置中会话级切换，下一次调用生效 |
| 外部路径 | 易失败或倾向 host | 优先询问挂载 |
| 挂载校验 | 配置可能开后门 | 跨平台解析，敏感路径硬拦 |
| 网络 | 无网络提示容易推向 bypass | Allowed Domains 窄通道 |
| 依赖安装 | 域名逐个问很烦 | package bundle 降低噪音 |
| 工具分类 | 按工具/action 太粗 | Operation Profile 看真实操作 |
| hints | 存在但作用浅 | 用于分类，不直接授权 |
| unknown | 规则外容易模糊 | unknown 保守分类 |
| Approvals | Bypass Approvals 是危险入口 | 只处理当前请求 |
| Always Allow | 可能按工具过宽 | 绑定具体操作画像 |
| Doctor/Explain | 状态和原因分散 | 健康与决策可解释 |
| 文案 | 多套旧概念 | 全部统一到三档模式 |
| 测试 | 未覆盖新语义 | 只新增测试防退化 |

## 最终判断

这次优化最重要的收益不是“多加一个 UI 页面”，而是把 OpenSquilla 的沙箱从“有执行隔离能力，但容易被 bypass 语义绕开”变成：

> 默认沙箱执行，边界扩展明确询问，host 执行只有清楚、少数、可审计的入口。

这也是为什么 P0 应该先做 Run Mode、Run Context、approval 迁移、Path Access Request 和 Host Once，而不是先追更复杂的 classifier 或更大的 backend 改造。
