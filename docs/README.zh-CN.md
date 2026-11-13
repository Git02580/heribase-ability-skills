# HeriBase Connector

**把一文件夹的钱币照片，整理成可继续维护的收藏。**

相册里堆着没命名的钱币照片，或已经用表格记录了一批藏品？把整批资料交给 Codex、Claude Code 或其他兼容的 AI 助手。HeriBase Connector 会帮助手配对正反面、标出缺图，识别你选中的钱币，再把核对过的结果存进 HeriBase 收藏。

**[快速开始](#快速开始)** · [HeriBase 官网](https://www.heribase.com/zh-CN/) · [更新记录（英文）](../CHANGELOG.md)

[English](../README.md) · **简体中文** · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## 5 张照片，整理出 3 枚钱币

假设文件夹里有两枚钱币的正反面，第三枚只有正面。助手会整理出两组完整照片，并提示第三枚缺反面。你可以先识别照片齐全的两枚，补图后再继续第三枚。

![HeriBase 工作台展示两组完整的正反面照片，以及一枚缺反面的钱币](demo-photo-pairs.webp)

*工作台演示使用公开示例照片，画面为英文翻译。* [演示照片来源](demo-credits.md)

<details>
<summary>看看识别结果长什么样</summary>

确认要识别的照片后，工作台会展示建议的币种和 HeriBase 返回的信息。对照照片核对年份和面额，再决定是否加入收藏。

![1860 年印第安头像一美分硬币的示例识别卡，包含两面照片和收藏入口](demo-identification.webp)

*卡片中的识别信息为演示数据。*

</details>

## 快速开始

把下面这段话发给 Codex、Claude Code 或其他支持 Skills、能运行本地命令的桌面 Agent：

```text
请从 https://github.com/HeriBase/heribase-ability-skills 安装全部六个 HeriBase Skills。
按 README 将技能整套复制到当前 Agent 的 Skills 目录，再运行 setup.py --init 完成初始化。
准备好后告诉我怎么开始；如需登录 HeriBase，请让我在浏览器里完成。
```

<details>
<summary>自己在终端安装</summary>

需要 Node.js 24+、Python 3.9+（推荐 3.12）和 Git。以下以 Codex 为例，整套安装：

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
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

[安装与排障](../skills/heribase-cli/references/installation.md)

## 用自己的照片试一试

> 帮我整理这个文件夹的钱币照片，配对正反面，列出缺图和不确定的配对。等我核对后再开始识别。

## 收藏后还可以做什么

- **接着整理上次那批.** 原始照片、配对决定和核对进度会保存在任务里，下次可以接着做。
- **查收藏里的行情.** 让助手查看你在 HeriBase 追踪的钱币最新可用的行情。
- **跟进真人鉴定.** 查询鉴定进度，报告出具后可以打开查看。

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

[提交问题](https://github.com/HeriBase/heribase-ability-skills/issues). 请勿附上账户信息、凭据或私人藏品照片。
