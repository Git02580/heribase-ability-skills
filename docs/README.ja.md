# HeriBase Connector

**フォルダーにたまったコイン写真を、整理されたコレクションに。**

名前を付けていないコイン写真や、画像付きの表がたまっていませんか？まとめて Codex、Claude Code などの対応する AI エージェントに渡せます。HeriBase Connector が表裏の組み合わせや不足写真の確認を手伝い、選んだコインを識別し、確認済みの結果を HeriBase のコレクションに保存できます。

**[クイックスタート](#クイックスタート)** · [HeriBase 公式サイト](https://www.heribase.com/ja/) · [更新履歴（英語）](../CHANGELOG.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · **日本語** · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## 5枚の写真から3枚のコインを整理

2枚のコインは表裏がそろっていて、3枚目は表の写真しかないとします。エージェントはそろった2組をまとめ、3枚目の裏面がないことを知らせます。まず2枚を識別し、残りは写真を追加してから続けられます。

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

> このフォルダーのコイン写真を表と裏で組み合わせて。不足している写真や、判断が難しい組み合わせは教えて。私が確認してから識別を始めて。

## コレクションの整理を続ける

- **前回の続きから始める.** 元の写真、表裏の組み合わせ、確認の進み具合が残るので、同じ作業を再開できます。
- **保有コインの価格を確認する.** HeriBase で追跡しているコインの最新の参照価格を確認できます。
- **鑑定の進捗を確認する.** 専門家による鑑定の進捗を確認し、完成したレポートを開けます。

## 利用する前に

- HeriBase にログインする前でも写真を整理できます。AI エージェントが提供元のサービスで画像を処理する場合があります。オンラインでの識別やアカウント操作には HeriBase へのログインが必要です。
- チャットで作業するか、ローカルの作業画面で写真を確認できます。作業画面にアップロードした写真の自動整理には、ログイン済みの Codex CLI が必要です。
- 識別結果や参考価格は調査の目安です。真贋や売却価格を保証するものではありません。

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
