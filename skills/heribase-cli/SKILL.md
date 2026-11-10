---
name: heribase-cli
description: Use the installed HeriBase CLI safely for authentication, image upload, coin identification, collection management, appraisal submission using existing credits, tracking, Daily Coin, App guides, local task control, and machine-readable JSON results.
compatibility: Installed HeriBase CLI; companion heribase-task-package is required for persistent coin workflows.
metadata:
  short-description: HeriBase CLI 命令与 JSON 契约
---

# HeriBase CLI

`heribase` 是 Agent 与 HeriBase API 的唯一命令行边界。它管理本机配置、登录凭据、API 直接图片上传及预签名地址申请、异步本地任务和统一 JSON 输出；不要直接请求 HeriBase 内部 HTTP API。

CLI Skill 本身绝不读取或修改 `~/.heribase` 中的文件。任务包例外是独立的 `heribase-task-package` Skill 可以管理 `~/.heribase/user-tasks/<validated-task_key>/`、`_catalog/` 和 `_runtime/locks/`；该例外不扩展到 `auth.json`、配置或其他 CLI 内部文件。另由 `heribase-workspace` 的受限工具管理 `heribase.sqlite` 中 `workspace_*` 表、私有 runtime 与受控备份，复用任务包事务；这不授予 Agent 手工读取认证文件的权限。CLI 不能把任意路径读写或任意命令执行能力暴露给审核台。

## 安装与环境依赖

首次使用或出现环境错误时，按 [安装与环境检查](references/installation.md) 执行本 Skill 的 `scripts/setup.py --check`；缺少 Python 依赖时执行 `--install`。六个 skills 必须完整同级安装。

检查输出的 `python` 是后续所有 HeriBase Python 脚本应使用的解释器；安装依赖后它指向本 Skill 的 `.venv`。不要重新使用缺少依赖的系统 Python。CLI 可直接通过 `node <本 Skill 绝对目录>/bin/heribase` 调用，下文的 `heribase` 命令均可替换为这个前缀，无须先改全局 PATH。Node.js 需要 24+；Windows 也采用同一 Node 调用方式。

## 使用前检查

1. 先执行 `heribase status --json`。
2. 未配置时，请用户执行 `heribase configure --api-base-url <url>`。
3. 未登录或服务端返回未授权时，请用户执行 `heribase login`。该命令会启动浏览器登录，Agent 不应替代用户完成认证。
4. 所有业务、任务和诊断调用都使用 `--json`，只解析 stdout 中唯一的 JSON 文档；stderr 仅用于诊断，绝不从中提取业务结果。

认证 token 仅由 CLI 保存于 `~/.heribase/auth.json`。不要将 token 传入命令、日志、提示词、临时文件或外部服务。

当调用方使用 HeriBase 任务包时，每次业务 stdout JSON 必须先经过敏感字段扫描，再按原样保存到该任务的 `recognition/raw/` 或 `collection/raw/`，同时把规范化结果与 raw 文件哈希关联。CLI 不负责推断或补齐缺失字段。

## 命令边界

- 使用 `file upload` 将已获用户许可的本地图片上传；其 `fileUrl` 才能传给 `identify`。
- `identify` 只接收正面和反面 URL，服务端同步识别后返回业务 `uri` 与只读资产关联结果。
- `collection add`、`collection update`、`collection cancel` 都会变更服务器数据。任务工作流中只有在 `heribase-task-package` 已校验当前授权计划、payload 摘要、dataset revision、item version、审核决定和识别快照后才能调用；计划不存在、过期或不一致时必须拒绝。
- `currencyNumber`、`uniqUri`、`userUniqUri` 均由服务端产生或回查；只能读取，绝不能作为写请求的关联依据。
- 支持识别资格、收藏容量/编辑表单/收藏夹、真人鉴定、钱币追踪、Daily Coin、App 引导与价格入口。先按命令参考查询已有额度和资料，再在用户授权范围内执行写入。
- `appraisals submit` 消耗已有鉴定次数，`tracking add` 可消耗追踪位；鉴定次数和追踪位可分别通过对应的 `products/checkout/purchases pay/detail` 命令购买或查单。付款由用户在网页完成，查单确认 paid + granted 后核对相应余额，再单独提交鉴定或开启追踪。会员查询、自动续费和交易仍通过各自独立命令处理。
- 非会员价格请求可能只返回 App 引导；保留 API 实际返回的会员价格数据，不伪造缺失序列。不调用支付通知、浏览器返回、App 激活/转化上报。
- 不存在 `heribase batch organize`。批量图片配对、去重和第一次确认由具体业务 Skill 在本地会话中完成。

完整语法、JSON 字段、编辑 flag、任务状态和失败处理见 [命令参考](references/command-reference.md)。在实际执行某条命令前，必须先阅读对应小节。

## 执行与失败处理

- 业务命令可使用 `--mode sync`（默认）或 `--mode async`。`sync` 会等待本地 daemon 完成；`async` 返回任务信息后可用 `heribase task wait <task-id> --json` 等待。
- 对多个独立项目，记录每项的稳定本地 ID、attempt 和终态；发生部分失败时保留成功结果，仅在原确认范围内重试确定失败项。
- `file upload` 使用 `/agent/v1/file/upload` 直接上传，不自动重试或切换到预签名链路。失败后按任务错误决定是否重试；`file pre-upload` 的过期 URL 不可复用。不要把上传成功但尚未识别的图片误记为已识别资产。
- 遇到 `fetch failed`、本地连接被拒绝／重置或疑似 daemon 通信中断时，先保存原命令的错误上下文，并运行 `heribase daemon status --json`。只有 status 表明 daemon 未运行、异常，或 status 本身无法与 daemon 通信时，才依次运行一次 `heribase daemon stop --json` 与 `heribase daemon start --json`，然后再次检查 status；健康的 daemon 不得为了重试而随意重启。
- daemon 恢复后，读取类命令可重试一次；识别、上传等未完成操作仍须受原有用户确认范围约束。识别、收藏写入、鉴定提交、追踪写入及收藏夹写入若在错误前可能已提交或终态不明确，必须先执行只读核验，标记 `reconcile_required`，不得因重启 daemon 而直接重试写入。
- 遇到输入校验失败、未登录或权限错误时，说明问题并停下；不要猜测参数、编造 ID 或绕过确认。超时、崩溃或无法判断是否已写入时，记录为 `reconcile_required` 并先执行只读查询，不能盲目重试。

- 本次写接口没有服务端幂等键，不能添加虚假的 `requestId`。CLI 阻止已执行写任务的 `task retry`；读取 `error.data` 获取原业务码附带的 guide/失败 URI，`reconciliationRequired=true` 时先核验。
