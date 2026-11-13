# HeriBase Connector

<a href="https://www.heribase.com/zh-CN/"><img src="heribase-icon.png" alt="HeriBase" width="64" height="64"></a>

**给钱币收藏者的 Agent Skills**

把钱币照片发给 AI 助手，它可以帮你整理和配对正反面、用 HeriBase 识别钱币，再把你核对过的结果存入收藏。

[HeriBase 官网](https://www.heribase.com/zh-CN/) · [安装与排障](../skills/heribase-cli/references/installation.md)

[English](../README.md) · **简体中文** · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## 快速开始

把下面这段话发给 Codex、Claude Code 或其他支持 Skills、能运行本地命令的桌面 Agent：

```text
请从 https://github.com/Git02580/heribase-ability-skills 安装全部六个 HeriBase Skills。
按 README 将技能整套复制到当前 Agent 的 Skills 目录，再运行 setup.py --init 完成初始化。
准备好后告诉我怎么开始；如需登录 HeriBase，请让我在浏览器里完成。
```

<details>
<summary>自己在终端安装</summary>

需要 Node.js 24+、Python 3.9+（推荐 3.12）和 Git。以下以 Codex 为例，整套安装：

```sh
npx skills add Git02580/heribase-ability-skills --skill '*' --agent codex --global --copy
```

用安装器显示的实际 Skills 目录执行初始化。请把命令中的 `<skills-dir>` 换成这个路径。

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

使用 Claude Code、Gemini CLI 或 OpenCode 时，把 `codex` 换成 `claude-code`、`gemini-cli` 或 `opencode`。只装在当前项目就去掉 `--global`。如果 Agent 找不到技能，可以新开一个会话。

</details>

## 试着识别第一枚钱币

1. **发正反面照片。** 有一批照片时，可以让助手先配对，再把不确定的配对列出来。
2. **确认识别。** 核对本次要识别的照片，确认后由助手提交到 HeriBase。
3. **核对并收藏。** 查看识别出的币种和信息，再决定要不要加入 HeriBase 收藏。

## 你可以这样说

- “帮我配对这个文件夹里钱币的正反面，不确定的配对列出来。”
- “识别这枚钱币，等我核对结果后再加入收藏。”
- “查一下我的真人鉴定进度。”
- “看看我正在追踪的钱币有哪些最新行情。”

## 使用前了解

- 整理照片时可以先不登录 HeriBase；你的 AI 助手可能会通过它的服务商处理图片。在线识别和账户操作需要登录 HeriBase。
- 可以在聊天里办理，也可以打开本地工作台核对照片。网页上传后的自动整理需要已登录的 Codex CLI。
- 识别结果和参考价格用于辅助研究，不能作为真伪鉴定或成交价保证。

<details>
<summary>包含哪些技能</summary>

六个技能共用一个本地工作空间，请整套安装。

- [环境配置与登录](../skills/heribase-cli/SKILL.md) · `heribase-cli`
- [本地任务保存与恢复](../skills/heribase-task-package/SKILL.md) · `heribase-task-package`
- [钱币整理、识别与收藏](../skills/heribase-collection/SKILL.md) · `heribase-collection`
- [本地工作台](../skills/heribase-workspace/SKILL.md) · `heribase-workspace`
- [真人鉴定](../skills/heribase-appraisal/SKILL.md) · `heribase-appraisal`
- [行情追踪](../skills/heribase-tracking/SKILL.md) · `heribase-tracking`

</details>

## 获取帮助

[提交问题](https://github.com/Git02580/heribase-ability-skills/issues). 请勿附上账户信息、凭据或私人藏品照片。
