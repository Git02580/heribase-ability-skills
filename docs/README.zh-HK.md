# HeriBase Connector

<a href="https://www.heribase.com/zh-HK/"><img src="heribase-icon.png" alt="HeriBase" width="64" height="64"></a>

**為錢幣收藏者而設的 Agent Skills**

把錢幣相片傳給 AI 助手，它可以幫你整理和配對正反面、用 HeriBase 辨識錢幣，再將你核對過的結果加入收藏。

[HeriBase 官方網站](https://www.heribase.com/zh-HK/) · [安裝及疑難排解（英文）](installation.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · **繁體中文** · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## 快速上手

把以下指示傳給 Codex、Claude Code，或其他支援 Skills 且能執行本機指令的桌面 Agent：

```text
請從 https://github.com/Git02580/heribase-ability-skills 安裝全部六個 HeriBase Skills。
依照 README，將整套技能複製到目前 Agent 的 Skills 目錄，再執行 setup.py --init 完成初始化。
準備好後請告訴我如何開始。如需登入 HeriBase，請讓我在瀏覽器完成。
```

<details>
<summary>自行在終端機安裝</summary>

需要 Node.js 24+、Python 3.9+（建議 3.12）和 Git。以下是為 Codex 安裝整套技能的例子：

```sh
npx skills add Git02580/heribase-ability-skills --skill '*' --agent codex --global --copy
```

使用安裝程式顯示的 Skills 目錄進行初始化。把指令中的 `<skills-dir>` 換成該路徑。

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

若使用 Claude Code、Gemini CLI 或 OpenCode，請將 `codex` 換成 `claude-code`、`gemini-cli` 或 `opencode`。只想在目前專案安裝，請移除 `--global`。如果 Agent 找不到技能，可以開啟新對話。

</details>

## 試試辨識第一枚錢幣

1. **傳送正反面相片。** 如有一批相片，可請助手配對，並列出不確定的配對。
2. **確認辨識。** 先核對要辨識的相片；你確認後，助手才會將相片提交至 HeriBase。
3. **核對後收藏。** 查看建議的幣種及資料，再決定是否加入 HeriBase 收藏。

## 你可以這樣說

- “幫我配對這個資料夾內的錢幣正反面相片，並列出不確定的配對。”
- “辨識這枚錢幣，等我核對結果後才加入收藏。”
- “查看我的專家鑑定進度。”
- “看看我追蹤的錢幣有甚麼最新行情。”

## 使用前須知

- 你可先整理相片，稍後才登入 HeriBase。AI 助手可能透過其服務供應商處理圖片；網上辨識及帳戶操作需要登入 HeriBase。
- 你可以在對話內操作，也可開啟本機工作台核對相片。在工作台上載後自動整理相片，需要已登入的 Codex CLI。
- 辨識結果和參考價格只供研究參考，不能證明真偽或保證成交價。

<details>
<summary>包含的技能</summary>

六個技能共用同一個本機工作空間，請整套安裝。

- [環境設定及登入](../skills/heribase-cli/SKILL.md) · `heribase-cli`
- [儲存及恢復本機工作](../skills/heribase-task-package/SKILL.md) · `heribase-task-package`
- [錢幣整理、辨識及收藏](../skills/heribase-collection/SKILL.md) · `heribase-collection`
- [本機工作台](../skills/heribase-workspace/SKILL.md) · `heribase-workspace`
- [專家鑑定](../skills/heribase-appraisal/SKILL.md) · `heribase-appraisal`
- [行情追蹤](../skills/heribase-tracking/SKILL.md) · `heribase-tracking`

</details>

## 取得協助

[回報問題](https://github.com/Git02580/heribase-ability-skills/issues). 請勿附上帳戶資料、憑證或私人收藏相片。
