# HeriBase Ability Skills

让本地 Agent 帮你整理钱币照片、识别钱币、管理收藏，以及办理真人鉴定和追踪行情。

公开仓库：[Git02580/heribase-ability-skills](https://github.com/Git02580/heribase-ability-skills)。六个 skills 相互配合，**请整套安装**，保留各目录里的脚本、参考资料、页面资源和 CLI。

## 让你的 Agent 帮你安装

把下面这段话发送给你正在使用的 Codex、Claude Code 或其他支持 Agent Skills 的 Agent：

> 请阅读 https://github.com/Git02580/heribase-ability-skills 的 README，将全部 HeriBase skills 安装到你实际使用的用户级 skills 目录。使用复制方式安装，保持六个 skill 目录同级。按照 heribase-cli/references/installation.md 检查运行环境，补齐缺少的依赖，告诉我本地环境是否可用。后续 Python 命令使用检查结果中的解释器；HeriBase 登录由我在浏览器完成。

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

## 检查环境并开始使用

安装说明随 `heribase-cli` 一同分发，因此通过 `npx skills` 安装后也能阅读。先运行 `scripts/setup.py --check`；缺少 Python 依赖时运行 `--install`。该命令将依赖装入 `heribase-cli/.venv`，不修改系统 Python。

macOS / Linux，以 Codex 用户级目录为例：

```sh
SKILLS_DIR="$HOME/.agents/skills"
python3 "$SKILLS_DIR/heribase-cli/scripts/setup.py" --check
# 需要补齐依赖时执行
python3 "$SKILLS_DIR/heribase-cli/scripts/setup.py" --install
```

Windows PowerShell：

```powershell
$skillsDir = Join-Path $HOME '.agents\skills'
py -3 "$skillsDir\heribase-cli\scripts\setup.py" --check
# 需要补齐依赖时执行
py -3 "$skillsDir\heribase-cli\scripts\setup.py" --install
```

其他 Agent 请将目录替换为安装器实际输出的位置。检查通过后，把结果交给 Agent；后续 Python 脚本使用输出里的 `python` 路径。

首次连接需要 HeriBase 提供的 API 地址，并由你完成浏览器登录，具体命令见[配置与登录](skills/heribase-cli/references/installation.md#配置与登录)。随后就可以直接说：

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

本地任务和登录配置保存在用户目录的 `.heribase` 中。安装检查不登录、不上传图片，也不执行线上业务写入。
