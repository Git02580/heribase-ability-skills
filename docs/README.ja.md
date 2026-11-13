# HeriBase Connector

**フォルダーにたまったコイン写真を、整理されたコレクションに。**

名前を付けていないコイン写真や、画像付きの表がたまっていませんか？まとめて Codex、Claude Code などの対応する AI エージェントに渡せます。HeriBase Connector が表裏の組み合わせや不足写真の確認を手伝い、選んだコインを識別し、確認済みの結果を HeriBase のコレクションに保存できます。

**[クイックスタート](#クイックスタート)** · [作業の流れを見る](#5枚の写真から3枚のコインを整理) · [HeriBase 公式サイト](https://www.heribase.com/ja/) · [更新履歴（英語）](../CHANGELOG.md) · [検証結果を見る（英語）](verification.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · **日本語** · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## 5枚の写真から3枚のコインを整理

サンプルには、2枚のコインの表裏と、3枚目の表の写真が入っています。Codex で2回試したところ、どちらも5枚の写真は個別に保存されました。目視で2組の表裏を確認して保存し、3枚目は裏面が不足した状態で残しました。 [検証結果を見る（英語）](verification.md#five-photo-workbench-check)

![表裏がそろった2枚のコインと、裏面の写真がない1枚を表示した HeriBase の作業画面](demo-photo-pairs.webp)

*公開されているサンプル写真を使った作業画面のデモです。画面内の表示は英訳しています。* [デモ写真の出典](demo-credits.md)

<details>
<summary>識別結果を見てみる</summary>

識別する写真を確認すると、候補のコインと HeriBase から返された情報が表示されます。写真と見比べて年号や額面を確かめ、保存するかを選びます。

![1860年のインディアンヘッド・セントの識別例。表裏の写真とコレクションへの保存ボタンがある](demo-identification.webp)

*カード内の識別情報は表示例です。*

</details>

## クイックスタート

Codex、Claude Code など、Skills に対応し、ローカルでコマンドを実行できるデスクトップの AI エージェントに、次の指示を送ってください。

```text
https://github.com/HeriBase/heribase-ability-skills にある HeriBase Skills を6つすべてインストールしてください。
README に従って、使っているエージェントの Skills ディレクトリにコピーし、setup.py --init を実行してください。
準備ができたら使い方を教えてください。HeriBase へのログインが必要なら、ブラウザーで自分で行います。
```

<details>
<summary>ターミナルからインストールする</summary>

Node.js 24 以上、Python 3.9 以上（3.12 推奨）、Git が必要です。次は Codex に一式をインストールする例です。

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
```

インストーラーに表示された Skills ディレクトリを使って初期化します。以下の `<skills-dir>` を実際のパスに置き換えてください。

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

Claude Code、Gemini CLI、OpenCode の場合は、`codex` をそれぞれ `claude-code`、`gemini-cli`、`opencode` に置き換えます。現在のプロジェクトだけで使う場合は `--global` を省略します。スキルが見つからない場合は、新しいセッションを開いてください。

</details>

[インストールとトラブル対処（英語）](../docs/installation.md)

## 手元のコイン写真で試す

[サンプル写真5枚をダウンロード](coin-photo-sample.zip) · ZIPを展開し、下の指示と一緒にJPEGを渡してください。組み合わせを作業画面の例と見比べられます。

### フォルダーの写真をまとめて整理する

イベントや旅行で撮ったコイン写真をまとめて渡します。エージェントは表裏を組み合わせ、不足や重複の可能性、判断しにくい組み合わせを示します。

```text
このフォルダーのコイン写真を表裏で組み合わせて。不足や判断の難しい組み合わせを教えて。確認してから識別したい。
```

## コレクションでできること

### 今あるExcel台帳を使う

写真や画像リンクのある表から、シート名と行番号を残して下書きを作れます。画像がない行や読み込めない行は確認用に残ります。

```text
このコイン台帳を整理して。シート名と行番号を残し、画像がない行や読み込めない行を教えて。
```

### 1枚識別してから保存する

表裏の写真を確認してから識別を始めます。候補が出たら、写真と照らして年号、額面、取得できたミントマークなどを確認して保存します。

```text
この2枚の写真からコインを識別して。コレクションへの追加を決める前に結果を見せて。
```

## コレクションの整理を続ける

### 別の日に作業を再開する

元の写真や確認済みの組み合わせ、未確認の項目が作業環境に残ります。足りない写真を見つけたら同じ作業を開いて追加できます。

```text
前回のコイン整理を再開して。不足している写真と、まだ確認していない識別結果を教えて。
```

追跡中のコインの最新価格を確認したり、専門家に依頼した鑑定の進捗や報告書を見たりできます。

## 利用する前に

### よくある質問

**最初からログインは必要ですか？**

写真整理はログイン前に試せます。オンライン識別やアカウント操作にはHeriBaseへのログインが必要です。エージェント提供元が画像を処理する場合があります。

**チャットだけで作業できますか？**

はい。細かく確認したいときはローカルの作業画面を開けます。画面へのアップロード後に自動整理するには、別途Codex CLIへのログインが必要です。

**片面しか撮っていない場合は？**

不足している面が表示されます。そろっているコインを先に進め、後から同じ作業に写真を追加できます。

**識別結果で真贋は分かりますか？**

候補と参考価格は調査の手掛かりです。専門家による鑑定は別のサービスで確認できます。

<details>
<summary>同梱スキル</summary>

6つのスキルはローカルの作業環境を共有するため、一式をインストールしてください。

- [環境設定とログイン](../skills/heribase-cli/SKILL.md) · `heribase-cli`
- [ローカル作業の保存と再開](../skills/heribase-task-package/SKILL.md) · `heribase-task-package`
- [コインの整理・識別・収集](../skills/heribase-collection/SKILL.md) · `heribase-collection`
- [ローカルの作業画面](../skills/heribase-workspace/SKILL.md) · `heribase-workspace`
- [専門家による鑑定](../skills/heribase-appraisal/SKILL.md) · `heribase-appraisal`
- [価格の追跡](../skills/heribase-tracking/SKILL.md) · `heribase-tracking`

</details>

## サポート

[問題を報告する](https://github.com/HeriBase/heribase-ability-skills/issues). アカウント情報、認証情報、非公開のコイン写真は添付しないでください。
