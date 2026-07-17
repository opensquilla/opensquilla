# 新沙箱与审批技术报告

这份报告解释 PR #412 在 `8115d438 fix: align sandbox approvals with run modes`
之后的新沙箱和审批模型，并把它和更早期的混合式沙箱方案对比。

目标读者：PR 审阅者，以及第一次接触这套功能、但不想直接读源码的人。

## 一句话版本

新的沙箱模型改成更清晰的三模式理解方式：先选运行模式，再由运行模式决定是否需要沙箱审批。
它围绕三种运行模式展开：

| 运行模式 | 含义 | 谁能选择 | 审批行为 |
| --- | --- | --- | --- |
| Standard-Sandbox | 严格沙箱。Agent 在有边界的环境里工作。 | owner 和非 owner 用户 | 沙箱需要额外访问时才询问。 |
| Trusted-Sandbox | 仍然启用沙箱，但可信常规工作会更顺畅。 | owner 和非 owner 用户。频道默认使用它。 | 只在仍需人类决定的沙箱访问上询问。 |
| Full Host Access | 不启用沙箱，也不走沙箱审批。Agent 直接在宿主机执行。 | 仅 owner 或配置好的频道管理员 | 不走沙箱审批路径。 |

审批 UI 对沙箱请求只保留一个简单决策模型：

| 选择 | 直白含义 |
| --- | --- |
| 允许一次（Allow once） | 只允许这一次请求。 |
| 允许同类型所有（Allow same type） | 记住当前上下文里的同类型请求。 |
| 不允许（Deny） | 不允许。 |

最重要的设计规则是：

> Full Host Access 就是不启用沙箱，也不走沙箱审批。沙箱模式才使用沙箱审批。
> 频道用户不在聊天里处理沙箱审批；需要时由频道管理员把会话切到 Full Host Access。

本报告里的“之前”不是指最后几次 cleanup commit 之前，而是指更早期的混合式设计：
沙箱、工具审批、权限模式、intent cache 和频道审批还没有收敛到同一套心智模型。

## 为什么需要改

早期模型最大的问题不是“没有安全控制”，而是没有把边界划清：
Full Host Access、沙箱执行、工具审批、频道审批和 intent cache 像几套开关叠在一起。
这会让用户很难判断“我现在是在批准沙箱扩权，还是在批准工具本身执行”。

典型表现包括：

- Full Host Access 语义不够纯，容易变成“宿主机执行 + 仍可能审批”；
- shell warnlist/destructive gate 和沙箱审批像两条审批路线；
- 沙箱关闭时，某些工具仍可能走旧审批逻辑，和“无沙箱就是 full host”的预期冲突；
- 沙箱开启时，用户可能不确定自己会不会同时遇到工具审批和沙箱审批；
- 频道里的沙箱升级可能创建审批请求，但频道用户未必能收到或正确处理；
- 旧的 “always allow” intent cache 容易被误解为新沙箱模型里的“永久允许”；
- WebUI 上的审批选择和后端需要的 `choice` payload 没有足够直接地对齐。

新模型的目标是去掉这些歧义。用户先选信任级别，审批行为再跟着这个选择自然发生。

## 新的理解方式

可以把新模型理解成一条主线：

1. 运行模式决定工具在哪里跑。
2. 审批决定沙箱请求能不能临时扩大访问范围。

当运行模式是 Full Host Access 时，沙箱开关是关闭的，所以沙箱审批也关闭。
当运行模式是 Standard-Sandbox 或 Trusted-Sandbox 时，沙箱是开启的。如果沙箱拦住了某个需要额外访问的操作，就可能出现沙箱审批。

换句话说，新模型不是“多层审批叠加”，而是：

- Full Host Access：不沙箱，不审批；
- Sandbox：沙箱内执行，必要时走沙箱审批；
- Channel：默认 Trusted-Sandbox，不让普通频道用户处理沙箱审批，管理员可显式切 full。

## 不同入口的行为

### WebUI 和 CLI

WebUI 和 CLI 可以直接展示沙箱审批请求。用户只需要选择：

- 允许一次
- 允许同类型所有
- 不允许

这些选择会映射到后端的 `choice` payload，所以 UI 和后端现在共享同一套契约。

### 频道

频道任务现在默认使用 Trusted-Sandbox。频道路径故意不让普通频道用户在聊天里处理沙箱审批。

如果频道任务需要沙箱拦住的访问，Agent 会提示用户找频道管理员切换会话：

```text
/sandbox full
```

只有当某个频道发送者的 sender id 被写入该频道来源的 `channel_admin_senders` 时，
这个发送者才算频道管理员：

```toml
[channel_admin_senders]
feishu = ["sender-id-1"]
slack = ["sender-id-2"]
discord = ["sender-id-3"]
telegram = ["sender-id-4"]
```

这是一个显式白名单。当前实现不会自动信任聊天平台自己的群管理员状态。

## 和早期混合模型对比

| 领域 | 早期混合模型 | 现在的三模式统一模型 |
| --- | --- | --- |
| 运行模式 | 沙箱姿态、权限模式和审批行为不容易一起解释清楚。 | 三种清晰模式：Standard-Sandbox、Trusted-Sandbox、Full Host Access。 |
| Full Host Access | 容易被理解成“更高权限 + 仍可能审批”。 | 仅 owner/admin 可用的宿主机执行；不启用沙箱，不走沙箱审批。 |
| 沙箱关闭 | 关闭沙箱后仍可能被旧工具审批门打断。 | 沙箱关闭等同 Full Host Access：不沙箱、不沙箱审批。 |
| 沙箱开启 | 可能让用户感觉工具审批和沙箱审批同时存在。 | 沙箱内只有沙箱扩权需要审批，用户只面对同一套三选一。 |
| 沙箱审批选择 | UI 选择和后端期望不够直接，选择含义容易发散。 | 三种选择：允许一次、允许同类型所有、不允许。 |
| 频道 | 即使频道用户不能可靠处理审批，也可能创建沙箱升级审批。 | 频道默认 Trusted-Sandbox，不让用户处理沙箱审批。管理员可运行 `/sandbox full`。 |
| 旧 shell 审批 | shell warnlist/destructive approval 和 sandbox escalation 像两条路线。 | 沙箱相关决策收敛到沙箱审批模型；full host 不再额外走这条 gate。 |
| Intent cache | 旧 always-allow intent cache 容易被误解为新模型的一部分。 | 旧 intent cache 不会静默绕过沙箱 gate。 |

## 关键技术部件的作用

这些部件很重要，但它们的作用可以简单理解：

| 部件 | 作用 |
| --- | --- |
| `RunMode` | 给当前信任级别命名：`standard`、`trusted` 或 `full`。 |
| Run-mode policy | 判断某个身份能不能使用某个模式。非 owner 不能使用 `full`。 |
| `ToolContext` | 把当前入口、owner 标记、sender id、channel id 和运行模式带进工具执行。 |
| Sandbox escalation | 当沙箱模式需要额外路径或网络访问时，生成沙箱审批请求。 |
| Approval queue | 保存等待处理的审批请求和最终选择。 |
| Channel command registry | 让频道管理员可以运行 `/sandbox standard`、`/sandbox trusted` 或 `/sandbox full`。 |

## 实际效果

- 用户看到的审批选择更少，也更容易理解。
- Full Host Access 像真正的宿主机模式一样工作。
- “无沙箱”不再意味着“还可能被另一条审批路线拦住”。
- “有沙箱”不再意味着“同时走两套审批路线”。
- 频道默认从 Trusted-Sandbox 开始，更安全。
- 频道管理员仍然有可信场景下的逃生通道。
- WebUI 审批 payload 和后端期望一致。
- 沙箱 gate 不再依赖旧 intent-cache 状态跳过决策。

## 运维注意点

Full Host Access 故意设计得很强。只有在工作区和频道发送者都可信时才应该使用。
对于频道，要谨慎配置 `channel_admin_senders`，因为这些 sender id 可以把会话切出沙箱。

## 可视化页面

打开这个页面可以看图理解前后区别：

[`sandbox-approval-before-after.html`](sandbox-approval-before-after.html)
