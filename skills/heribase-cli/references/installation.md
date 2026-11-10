# 安装与初始化

本文同时供用户和安装 Agent 使用。完成顺序是：安装六个 skills → 补齐基础环境 → 执行 `setup.py --init` → 给出使用引导。用户委托安装后，由安装 Agent 连续执行这些步骤；不要只报告文件已复制或环境检查通过。`npx skills` 不会自动运行安装后脚本，接续初始化由当前 Agent 执行。首次加载 skill 时若尚未完成准备，同样执行 `--init`。

## 1. 选择宿主并整套安装

优先根据当前 Agent 已配置的 skills 目录和用户希望的范围安装。用户级适用于多个项目；项目级仅对当前项目生效。不要把仓库源码目录直接当作安装位置。

```sh
npx skills add Git02580/heribase-ability-skills --skill '*' --agent codex --global --copy
```

将 `codex` 替换为 `claude-code`、`gemini-cli` 或 `opencode`。当前项目安装去掉 `--global`。同一条命令可在 macOS/Linux 终端与 Windows PowerShell 使用。没有 Node.js 时先完成下一节；使用 Git 来源时还需要 Git。

无法使用安装器时，将仓库 `skills/` 内的六个 `heribase-*` 文件夹完整复制到宿主实际的 skills 根目录。常见位置：Codex 用户级 `~/.agents/skills`、项目级 `.agents/skills`；Claude Code 用户级 `~/.claude/skills`、项目级 `.claude/skills`。自定义配置优先，不创建同名技能的多份副本。Windows 的 `~` 指当前用户目录。

安装后应存在以下同级目录，且各自的 scripts、references、assets、bin 等内容完整：

```text
<skills-dir>/
├── heribase-cli/
├── heribase-task-package/
├── heribase-collection/
├── heribase-workspace/
├── heribase-appraisal/
└── heribase-tracking/
```

不要仅复制 SKILL.md，也不要把六个文件夹再包进一个 `heribase-ability-skills` 子目录。宿主未发现技能时，核对实际路径并重新打开会话。

## 2. 准备基础环境

| 组件                         | 要求                             | 用途                                |
| ---------------------------- | -------------------------------- | ----------------------------------- |
| Python                       | 3.9+；新装推荐 3.12，含 venv/pip | 工作台与任务脚本                    |
| Node.js                      | 24+                              | 随附的 JavaScript CLI 与 npx 安装器 |
| Git                          | 可在终端运行                     | 使用 npx 从仓库安装                 |
| Pillow、openpyxl、defusedxml | 由 setup.py 安装                 | 图片、表格及 XML 处理               |
| 浏览器                       | 现代桌面浏览器                   | 登录与可选工作台                    |
| Codex CLI                    | 仅网页后台自动整理需要，须已登录 | 自动整理执行器                      |

基础程序检查：

```sh
python3 --version
node --version
git --version
```

Windows 使用 `py -3 --version` 或实际可用的 `python --version`。

**macOS**：已安装 Homebrew 时，可运行 `brew install python@3.12 node@24 git`。随后确认 `python3.12`、`node` 和 `git` 在当前终端可用；Node 若未进入 PATH，按 Homebrew 输出的提示配置。也可使用 [Python 安装包](https://www.python.org/downloads/) 和 [Node.js 安装包](https://nodejs.org/en/download)。

**Linux**：使用发行版包管理器准备 Python、venv 和 Git，例如 Ubuntu/Debian：`sudo apt install python3 python3-venv git`。Node.js 请按 [Node.js 官方安装说明](https://nodejs.org/en/download) 选择 24+；不要假定发行版的默认 `nodejs` 包满足版本要求。

**Windows**：使用 [Python 安装包](https://www.python.org/downloads/windows/)、[Node.js 安装包](https://nodejs.org/en/download) 和 [Git 安装包](https://git-scm.com/downloads/win)。确保 Python launcher/pip 可用，Node 和 Git 已加入 PATH，然后重新打开 PowerShell 和 Agent。

安装 Agent 先检查已有版本，缺什么补什么；需要管理员权限时说明具体安装操作。不要把 HeriBase Token 当作依赖配置。

## 3. 自动完成本地初始化

`<skills-dir>` 是实际安装目录，不能使用源码路径代替。基础 Python/Node 可用后，由 Agent 执行：

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

Windows 可用：

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

这个命令可以重复运行，会依次：

- 检查六个 skills、Python、Node.js 和随附 CLI。
- 缺少 Python 依赖时在 `heribase-cli/.venv` 安装，再次检查；依赖齐全时跳过下载。
- 检查随附 CLI 文件并准备 Windows `heribase.cmd`；通过 Node 执行，不修改 CLI 产物。
- 调用随附 CLI 的 `status --json`；仅当 CLI 明确返回未配置时，执行 `configure --api-base-url https://api.heribase.com` 并重新查询状态。已有配置或其他错误不会触发覆盖。
- 返回 `initialization` 和 `onboarding`，供 Agent 生成友好提示。

`ok: true` 表示环境和本地初始化均成功，`authenticated: false` 只表示需要登录。失败时按 `checks`、`initialization.error` 或顶层 `error` 修复，不把部分完成说成全部成功。脚本不会安装系统 Python、Node 或 Git；这些程序缺失时由安装 Agent 按上一节补齐。

仅排障时执行 `setup.py --check`：它只查询环境和 CLI 版本，不创建配置。需要单独重装 Python 依赖时可用 `--install`，随后执行 `--init` 完成初始化。

**后续所有 HeriBase Python 命令使用检查输出中的 `python` 绝对路径。** 安装后通常是：

- macOS/Linux：`<skills-dir>/heribase-cli/.venv/bin/python`
- Windows：`<skills-dir>\heribase-cli\.venv\Scripts\python.exe`

不要在另一个 Python 环境里反复补包，也不要将本机 `.venv` 复制给其他用户。技能重新安装后再次运行 `--init` 即可。

## 配置与登录

CLI 已包含在 `heribase-cli/bin/heribase` 中，它是 JavaScript 文件。直接用 Node 启动，无需复制另一个 CLI，也无需修改全局 PATH。

`--init` 已通过 CLI 初始化默认 API `https://api.heribase.com`，普通用户无需提供地址或执行 `configure`。登录放在使用引导中：已有登录状态则跳过；未登录时询问是否现在登录，也允许先做本地整理，等在线操作前再引导。用户选择登录后，由 Agent 运行下列命令，浏览器认证由用户完成。

macOS/Linux：

```sh
SKILLS_DIR="$HOME/.agents/skills"  # 改成你的实际目录
node "$SKILLS_DIR/heribase-cli/bin/heribase" login
node "$SKILLS_DIR/heribase-cli/bin/heribase" status --json
```

Windows PowerShell：

```powershell
$skillsDir = Join-Path $HOME '.agents\skills' # 改成你的实际目录
node "$skillsDir\heribase-cli\bin\heribase" login
node "$skillsDir\heribase-cli\bin\heribase" status --json
```

已有配置会保留，不会被默认地址覆盖。确实需要测试环境或其他服务地址时，才运行 `node <CLI路径> configure --api-base-url <自定义地址>`；首次初始化也可通过 `HERIBASE_API_BASE_URL` 指定地址。配置优先级为已有配置 → 环境变量 → 官方默认地址。

`status --json` 确认本机是否保存登录凭据；当前 CLI 可能启动或连接本地 daemon，它不能证明凭据仍有效，业务接口返回未授权时重新引导登录。CLI 管理用户目录下的 `.heribase`；不要读取或复制 `auth.json` 排障。`--help`、`version` 以及环境脚本的 `--check` 不创建配置。

技能文档中的 `heribase ...` 均可替换为上面的 `node .../bin/heribase ...`。需要直接输入 `heribase` 时，可自行把 `heribase-cli/bin` 加入 PATH；这不是首次使用的必要步骤。

## 4. 给用户一个简短引导

初始化通过后，Agent 应根据实际结果回复，使用 `onboarding` 中的提示和示例，不直接粘贴整段检查 JSON、内部目录或脚本参数。例如首次安装且未登录时：

> HeriBase 已安装并初始化完成！
>
> 我可以帮你整理钱币照片、识别钱币并加入收藏，还能查看真人鉴定进度和追踪行情。
>
> 你可以直接说：“帮我整理这些钱币照片”，或发来正反面照片说：“识别这枚钱币”。
>
> 要现在登录吗？也可以先发照片体验本地整理，在线识别和收藏前再登录。

已保存登录状态时，将最后一句改为“已检测到保存的登录状态，发来照片或告诉我想做什么即可。”不要再次要求登录。用户已经给出具体任务时，简短说明准备完成并继续原任务。初始化失败时只说明失败原因和接下来的处理，不输出上述成功文案。

## 5. 开始使用

优先在当前对话给 Agent 照片或本次需要处理的目录。例如：“帮我整理这些钱币照片”“识别这枚钱币”“继续上次任务”“查看真人鉴定进度”。Agent 按相应业务 skill 办理。

需要网页时，用检查结果里的解释器启动：

```sh
"<python 的绝对路径>" "<skills-dir>/heribase-workspace/scripts/workspace.py" start --no-default-browser --page add
```

PowerShell 调用带引号的程序路径须加 `&`：

```powershell
& "<python 的绝对路径>" "<skills-dir>\heribase-workspace\scripts\workspace.py" start --no-default-browser --page add
```

Codex 桌面由 Agent 打开返回的工作台地址；其他宿主需要系统浏览器时可去掉 `--no-default-browser`。网页自动整理目前依赖已登录的 Codex CLI，参考 [Codex CLI 官方说明](https://developers.openai.com/codex/cli/) 安装。它与 HeriBase 登录是两件事；其他 Agent 的用户可先使用聊天办理，不能把“skills 已加载”描述成“后台自动整理已可用”。

## 常见问题

- **Agent 找不到技能**：核对安装范围、实际目录与六个 SKILL.md，必要时重新打开会话。
- **脚本找不到同级技能**：重新整套安装，并加 `--copy`。
- **Python 依赖仍缺失**：使用检查输出的 `python`，不要继续用原来的系统解释器。
- **Linux 缺少 ensurepip/venv**：先安装对应 Python 的 venv 包，再执行 `--init`。
- **Node 版本不足或找不到**：安装 24+ 后重启终端及 Agent，重新检查 `node --version`。
- **网络或包源错误**：修复网络/包源设置后重跑 `--init`；不要把包含凭据的完整日志发到聊天。
- **网页没有自动整理**：检查 Codex CLI 安装和登录；本脚本只检查可执行文件是否存在。
- **只有 `status --json` 失败**：检查 CLI 的本地配置、目录权限和 daemon 错误；不要因此重装 Python 依赖或删除已有配置。若是 CLI 本身的能力或兼容性问题，说明所需改进，交由 CLI 维护方处理，不修改随附产物。

安装器参考：[skills CLI](https://github.com/vercel-labs/skills)；宿主发现规则：[Codex](https://developers.openai.com/codex/skills/)、[Claude Code](https://code.claude.com/docs/en/skills)。
