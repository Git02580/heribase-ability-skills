# 安装与环境检查

本文同时供用户和安装 Agent 使用。目标是：把六个 skills 放到宿主能发现的位置，检查运行环境，完成依赖安装，再引导用户开始使用。

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

## 3. 检查与安装 Python 依赖

`<skills-dir>` 是实际安装目录。先执行：

```sh
python3 <skills-dir>/heribase-cli/scripts/setup.py --check
```

Windows 可用：

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --check
```

检查仅执行 CLI 的版本查询，不访问账户或线上业务。返回 `ok: true` 表示基本环境可用；返回 `ok: false` 时按 `checks` 中失败项处理。

Python 依赖缺失时执行：

```sh
python3 <skills-dir>/heribase-cli/scripts/setup.py --install
```

Windows 将前缀改为 `py -3`。可以重复执行。脚本会创建 `heribase-cli/.venv` 并安装 requirements.txt 中的依赖，准备 CLI 执行权限及 Windows `heribase.cmd`，最后再检查一次。它不会安装系统 Python、Node 或 Git；这些程序缺失时按上一节处理。

**后续所有 HeriBase Python 命令使用检查输出中的 `python` 绝对路径。** 安装后通常是：

- macOS/Linux：`<skills-dir>/heribase-cli/.venv/bin/python`
- Windows：`<skills-dir>\heribase-cli\.venv\Scripts\python.exe`

不要在另一个 Python 环境里反复补包，也不要将本机 `.venv` 复制给其他用户。技能重新安装后若缺少依赖，再运行 `--install` 即可。

## 配置与登录

CLI 已包含在 `heribase-cli/bin/heribase` 中，它是 JavaScript 文件。直接用 Node 启动，无需复制另一个 CLI，也无需修改全局 PATH。

默认 API 地址为 `https://api.heribase.com`。首次执行登录或业务命令时，CLI 自动初始化本机配置；普通用户直接登录即可。

macOS/Linux：

```sh
SKILLS_DIR="$HOME/.agents/skills"  # 改成你的实际目录
node "$SKILLS_DIR/heribase-cli/bin/heribase" configure --api-base-url https://api.heribase.com
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

登录由用户在浏览器完成。未登录不代表本地依赖安装失败。CLI 管理用户目录下的 `.heribase`；不要读取或复制 `auth.json` 排障。`--help`、`version` 以及环境脚本的 `--check` 不创建配置。

技能文档中的 `heribase ...` 均可替换为上面的 `node .../bin/heribase ...`。需要直接输入 `heribase` 时，可自行把 `heribase-cli/bin` 加入 PATH；这不是首次使用的必要步骤。

## 4. 开始使用

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
- **Linux 缺少 ensurepip/venv**：先安装对应 Python 的 venv 包，再执行 `--install`。
- **Node 版本不足或找不到**：安装 24+ 后重启终端及 Agent，重新检查 `node --version`。
- **网络或包源错误**：修复网络/包源设置后重跑 `--install`；不要把包含凭据的完整日志发到聊天。
- **网页没有自动整理**：检查 Codex CLI 安装和登录；本脚本只检查可执行文件是否存在。
- **只有 `status --json` 失败**：核对 HeriBase 配置、网络和登录，与依赖检查分别处理。

安装器参考：[skills CLI](https://github.com/vercel-labs/skills)；宿主发现规则：[Codex](https://developers.openai.com/codex/skills/)、[Claude Code](https://code.claude.com/docs/en/skills)。
