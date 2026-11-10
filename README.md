# HeriBase Ability Skills

让本地 Agent 帮你整理钱币照片、识别钱币、管理收藏，以及办理真人鉴定和追踪行情。

公开仓库：[Git02580/heribase-ability-skills](https://github.com/Git02580/heribase-ability-skills)。六个 skills 相互配合，**请整套安装**，保留各目录里的脚本、参考资料、页面资源和 CLI。

## 让你的 Agent 帮你安装

把下面这段话发送给你正在使用的 Codex、Claude Code 或其他支持 Agent Skills 的 Agent：

> 请阅读 https://github.com/Git02580/heribase-ability-skills 的 README，将全部 HeriBase skills 安装到你实际使用的用户级 skills 目录。使用复制方式安装，保持六个 skill 目录同级。继续按 heribase-cli/references/installation.md 补齐基础环境，运行安装目录里的 heribase-cli/scripts/setup.py --init，完成依赖安装、默认 API 配置和登录状态检查。最后告诉我是否初始化成功、我能做什么，并给几个直接使用的例子；未登录时询问我是否现在登录，浏览器认证由我完成。

需要限定在某个项目使用时，把“用户级”改成“当前项目”。

## 自己安装

先准备 **Node.js 24+、Python 3.9+ 和 Git**。新装 Python 推荐 3.12。macOS、Linux 和 Windows 的准备步骤见[安装说明](skills/heribase-cli/references/installation.md)。

在终端运行，以下以 Codex 用户级安装为例：

```sh
npx skills add Git02580/heribase-ability-skills --skill '*' --agent codex --global --copy
```

| 你使用的 Agent | `--agent` 参数 |
| -------------- | -------------- |
| Codex          | `codex`        |
| Claude Code    | `claude-code`  |
| Gemini CLI     | `gemini-cli`   |
| OpenCode       | `opencode`     |

安装到当前项目时，先进入该项目目录，再去掉 `--global`。其他 Agent 可不传 `--agent`，跟随安装器选择。安装完成后，以安装器显示的实际目录为准。

`--copy` 用于保留技能之间的同级路径关系。若使用手动安装，将本仓库 `skills/` 下的六个 `heribase-*` 文件夹完整复制到宿主的技能目录；只有源码仓库下载到本机还不算安装完成。

## 初始化并开始使用

安装说明随 `heribase-cli` 一同分发，因此安装后也能阅读。**安装 Agent 应在复制完成后继续运行 `scripts/setup.py --init`，再向用户报告完成。** `npx skills` 本身只安装技能文件，不执行初始化脚本；手动安装者执行下面的命令，也可以直接让 Agent“完成 HeriBase 初始化”。

`--init` 会检查环境、将缺失的 Python 依赖装入 `heribase-cli/.venv`、初始化默认 API `https://api.heribase.com`，并返回登录状态和简短引导。已有自定义配置会保留，可以重复执行。

macOS / Linux，以 Codex 用户级目录为例：

```sh
SKILLS_DIR="$HOME/.agents/skills"
python3 "$SKILLS_DIR/heribase-cli/scripts/setup.py" --init
```

Windows PowerShell：

```powershell
$skillsDir = Join-Path $HOME '.agents\skills'
py -3 "$skillsDir\heribase-cli\scripts\setup.py" --init
```

其他 Agent 请将目录替换为安装器实际输出的位置。后续 Python 脚本使用输出里的 `python` 路径。仅排查环境时可用只读的 `--check`。

初始化后，Agent 会说明能做什么，并在尚未登录时询问是否现在登录。也可以先整理本地照片，等在线识别、收藏或查询时再登录；已保存登录状态则直接开始。具体命令见[配置与登录](skills/heribase-cli/references/installation.md#配置与登录)。你可以直接说：

- “帮我整理这些钱币照片，先让我核对正反面。”
- “识别这枚钱币，结果确认后再加入收藏。”
- “继续上次的钱币任务。”
- “查看我的真人鉴定进度。”
- “查看我正在追踪的钱币行情。”

当前网页上传后的后台自动整理使用已登录的 **Codex CLI**；在其他 Agent 中安装 skills 不会自动提供这个执行器。聊天办理可以使用当前 Agent；需要网页自动整理时，按安装说明准备 Codex。

## 包含的技能

| Skill                   | 用途                               |
| ----------------------- | ---------------------------------- |
| `heribase-cli`          | 环境检查、CLI 配置与登录、命令参考 |
| `heribase-task-package` | 保存与恢复本地任务                 |
| `heribase-collection`   | 照片整理、识别、审核和收藏         |
| `heribase-workspace`    | 本地工作台和对话协作               |
| `heribase-appraisal`    | 真人鉴定材料与进度                 |
| `heribase-tracking`     | 本人收藏追踪与行情                 |

本地任务和登录配置保存在用户目录的 `.heribase` 中。初始化不自动登录、不上传图片，也不执行线上业务写入。

## CLI 维护边界

`skills/heribase-cli/bin/heribase` 由 CLI 项目独立打包和维护。Skills 优化仅调整技能说明、调用脚本和安装引导，不修改、重新打包或替换该文件。需要 CLI 新增或调整能力时，先说明所需功能与原因，由 CLI 维护方实现并提供新版产物。
