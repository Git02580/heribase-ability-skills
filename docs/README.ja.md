# HeriBase Connector

<a href="https://www.heribase.com/ja/"><img src="heribase-icon.png" alt="HeriBase" width="64" height="64"></a>

**コイン収集のための Agent Skills**

コインの写真を AI エージェントに送ると、表裏の整理、HeriBase での識別、確認済みの結果のコレクションへの追加を手伝ってくれます。

[HeriBase 公式サイト](https://www.heribase.com/ja/) · [インストールとトラブル対処（英語）](installation.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · **日本語** · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## クイックスタート

Codex、Claude Code など、Skills に対応し、ローカルでコマンドを実行できるデスクトップの AI エージェントに、次の指示を送ってください。

```text
https://github.com/Git02580/heribase-ability-skills にある HeriBase Skills を6つすべてインストールしてください。
README に従って、使っているエージェントの Skills ディレクトリにコピーし、setup.py --init を実行してください。
準備ができたら使い方を教えてください。HeriBase へのログインが必要なら、ブラウザーで自分で行います。
```

<details>
<summary>ターミナルからインストールする</summary>

Node.js 24 以上、Python 3.9 以上（3.12 推奨）、Git が必要です。次は Codex に一式をインストールする例です。

```sh
npx skills add Git02580/heribase-ability-skills --skill '*' --agent codex --global --copy
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

## まずはコイン1枚を識別

1. **表と裏の写真を送る。** 写真が複数ある場合は、表裏を組み合わせ、判断が難しい組み合わせだけ示すよう頼めます。
2. **識別する写真を確認する。** 選んだ写真を確認すると、エージェントが HeriBase に送信して識別します。
3. **結果を確認して保存する。** 候補のコインや詳細を確かめ、必要なら HeriBase のコレクションに追加します。

## こんなふうに頼めます

- “このフォルダーのコイン写真を表と裏で組み合わせて。判断が難しいものは教えて。”
- “このコインを識別して。結果を確認してからコレクションに追加したい。”
- “専門家に依頼した鑑定の進捗を確認して。”
- “追跡しているコインの最新の参考価格を見せて。”

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

[問題を報告する](https://github.com/Git02580/heribase-ability-skills/issues). アカウント情報、認証情報、非公開のコイン写真は添付しないでください。
