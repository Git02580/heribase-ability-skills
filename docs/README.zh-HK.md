# HeriBase Connector

**將一個資料夾的錢幣相片，整理成可繼續管理的收藏。**

相簿裏有一堆未命名的錢幣相片，或已有一份附圖的試算表？把整批資料交給 Codex、Claude Code 或其他相容的 AI 助手。HeriBase Connector 可協助配對正反面、標示欠缺的相片、辨識你選定的錢幣，並把你核對過的結果加入 HeriBase 收藏。

**[快速上手](#快速上手)** · [查看工作流程](#5-張相片整理成-3-枚錢幣的記錄) · [HeriBase 官方網站](https://www.heribase.com/zh-HK/) · [更新記錄（英文）](../CHANGELOG.md) · [查看實測記錄（英文）](verification.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · **繁體中文** · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## 5 張相片，整理成 3 枚錢幣的記錄

範例包含兩枚錢幣的正反面，以及第三枚的正面。用 Codex 實測兩次，5 張相片均已保留，自動整理沒有合併。手動確認並儲存兩組正反面後，第三枚仍標示為欠缺反面。 [查看實測記錄（英文）](verification.md#five-photo-workbench-check)

![HeriBase 工作台顯示兩組齊全的正反面相片，以及一枚欠缺反面的錢幣](demo-photo-pairs.webp)

*工作台示範使用公開範例相片，畫面以英文呈現。* [示範相片來源](demo-credits.md)

<details>
<summary>看看辨識結果</summary>

確認要辨識的相片後，工作台會顯示建議的幣種和 HeriBase 回傳的資料。對照相片核對年份和面額，再決定是否加入收藏。

![1860 年印第安頭像一美仙的範例辨識卡，包含兩面相片及收藏按鈕](demo-identification.webp)

*卡片上的辨識資料為示範用途。*

</details>

## 快速上手

把以下指示傳給 Codex、Claude Code，或其他支援 Skills 且能執行本機指令的桌面 Agent：

```text
請從 https://github.com/HeriBase/heribase-ability-skills 安裝全部六個 HeriBase Skills。
依照 README，將整套技能複製到目前 Agent 的 Skills 目錄，再執行 setup.py --init 完成初始化。
準備好後請告訴我如何開始。如需登入 HeriBase，請讓我在瀏覽器完成。
```

<details>
<summary>自行在終端機安裝</summary>

需要 Node.js 24+、Python 3.9+（建議 3.12）和 Git。以下是為 Codex 安裝整套技能的例子：

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
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

[安裝及疑難排解（英文）](../docs/installation.md)

## 用自己的相片試試

[下載 5 張範例相片](coin-photo-sample.zip) · 解壓後，把 5 張 JPEG 交給助手，試用下方的配對指令，再與示範結果比較。

### 一次整理整個資料夾

把展覽、旅行或舊備份的錢幣相片整批交給助手。助手會配對有足夠依據的正反面，列出欠缺的相片、可能重複的項目及不確定的配對。核對後再選擇要辨識的錢幣。

```text
整理這個資料夾的錢幣相片，配對正反面並列出欠缺或不確定的相片。等我核對後才開始辨識。
```

## 如何整理你的收藏

### 從現有的 Excel 收藏表開始

助手可把附有圖片或圖片連結的試算表逐列整理成草稿，保留原工作表和列號，並標出欠圖或無法讀取的項目。

```text
整理這份收藏表，保留每筆記錄的工作表和列號，先列出缺圖或無法讀取圖片的項目。
```

### 辨識一枚，再決定是否收藏

先確認要提交的正反面相片。收到建議幣種後，對照相片核對年份、面額和可用的造幣標記或參考價格，再決定是否儲存。

```text
用這兩張相片辨識這枚錢幣。先給我看結果，我核對後再決定是否收藏。
```

## 繼續管理你的收藏

### 下次接續同一批

原始檔案、已核對的配對及進度都留在工作空間。找到欠缺的相片後，可回到同一批補上。

```text
接續上次整理的錢幣，列出尚待補圖和仍未核對的記錄。
```

你亦可查閱正在追蹤的錢幣行情，或查看專家鑑定的進度及報告。

## 使用前須知

### 常見問題

**試用前要登入嗎？**

配對範例相片可以先做。線上辨識和帳戶操作需要登入 HeriBase；助手可能透過自己的服務供應商處理你交給它的相片。

**可以在對話內完成嗎？**

可以。需要仔細核對時，可開啟本機工作台。工作台上載後的自動整理需要已登入的 Codex CLI，與 HeriBase 登入分開。

**如果只有一面的相片？**

欠缺的一面會被標示。你可先處理完整配對，稍後再回到同一批補圖。

**辨識結果能證明真偽嗎？**

建議幣種和參考價格可作研究參考。如需專家判斷，可使用 HeriBase 的專家鑑定服務。

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

[回報問題](https://github.com/HeriBase/heribase-ability-skills/issues). 請勿附上帳戶資料、憑證或私人收藏相片。
