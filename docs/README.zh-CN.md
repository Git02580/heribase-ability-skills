# HeriBase Connector

**用正反两张照片识别一枚钱币，逐步建立自己的收藏。**

把钱币正反面的照片发给 Codex、Claude Code 或其他兼容的桌面助手。登录 HeriBase、确认要提交的照片后，在聊天里核对识别结果，再决定是否收藏。也可以整理整批照片或表格，下次接着做。

**[识别第一枚钱币](#识别一枚再决定是否收藏)** · **[快速开始](#快速开始)** · [查看工作流程](#5-张照片整理出-3-枚钱币) · [HeriBase 官网](https://www.heribase.com/zh-CN/) · [更新记录（英文）](../CHANGELOG.md) · [查看实测记录（英文）](verification.md)

[English](../README.md) · **简体中文** · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## 5 张照片，整理出 3 枚钱币

样例包含两枚钱币的正反面，以及第三枚的正面。用 Codex 实跑两次，5 张照片都保存了，自动整理没有合并。人工确认并保存了两组正反面，第三枚仍标记为缺反面。 [查看实测记录（英文）](verification.md#five-photo-workbench-check)

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

### 识别一枚，再决定是否收藏

发清晰的正反面照片，先核对要提交的图片。拿到建议币种后，对照年份、面额，以及服务实际返回的造币标记或参考价。核对好了再存进收藏。

```text
用这两张照片识别这枚钱币。先给我看结果和要核对的字段，我看完再决定是否收藏。
```

## 用自己的照片试一试

[下载 5 张示例照片](coin-photo-sample.zip) · 解压后，把 5 张 JPEG 交给助手，用下方的配对指令试一次，再对照页面里的演示结果。

### 把一文件夹照片一次理清

把逛展、出游或旧备份里的钱币照片整批交给助手。助手会配对有足够依据的正反面，列出缺图、疑似重复和不确定的配对。核对这些例外后，再选择要识别的币。

```text
整理这个文件夹的钱币照片，配对正反面，列出缺图、疑似重复和不确定的配对。先给我核对，再识别。
```

## 你的收藏可以怎么整理

### 用已有的 Excel 收藏表接着做

把带嵌入图片或图片链接的 Excel 表交给助手。它可以按行建立草稿，保留原工作表和行号。缺图或读不到图片的记录会留在这批里，等你补充。

```text
整理这张收藏表。每条记录保留原工作表和行号，先列出缺图或读不到图片的行。
```

## 收藏后还可以做什么

### 没做完的那一批下次接着来

工作空间会保留原件、你核对过的配对和未完成的记录。找到缺的那张照片后，回到同一批接着处理。

```text
继续上次那批钱币。给我看看还有哪些要补图，哪些识别结果还没核对。
```

对已存进 HeriBase 的钱币，你也可以查看正在追踪的行情，或查询真人鉴定的进度和报告。

## 使用前了解

### 常见问题

**试配对之前要登录吗？**

可以先整理示例照片。在线识别或使用账户功能时需要登录 HeriBase。你使用的助手可能会通过自己的服务商处理你交给它的图片。

**我能一直在聊天里做吗？**

可以。需要放大核对时，再让助手打开本地工作台。通过工作台上传后自动整理需要已登录的 Codex CLI；HeriBase 要单独登录。

**一枚钱币只有一面照片怎么办？**

助手会标出缺哪一面。你可以先处理其他完整的配对，等拿到照片再补回同一批。

**识别结果可以用来鉴真吗？**

建议币种和参考价可用于辅助研究。需要专家判断时，可使用 HeriBase 的真人鉴定流程。

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
