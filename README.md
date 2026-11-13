# HeriBase Connector

**Turn a folder of coin photos into a collection.**

If you have a camera roll full of unnamed coin photos or a spreadsheet with images, give the whole batch to Codex, Claude Code, or another compatible AI agent. HeriBase Connector helps it pair fronts and backs, flag missing photos, identify the coins you choose, and save the results you approve to your HeriBase collection.

**[Quick start](#quick-start)** · [HeriBase website](https://www.heribase.com/) · [What's new](CHANGELOG.md)

**English** · [Chinese (Simplified)](docs/README.zh-CN.md) · [Chinese (Traditional)](docs/README.zh-HK.md) · [Japanese](docs/README.ja.md) · [Spanish](docs/README.es.md) · [Portuguese (Brazil)](docs/README.pt-BR.md) · [German](docs/README.de.md) · [French](docs/README.fr.md)

## From five photos to three coin records

Imagine a folder with both sides of two coins and only the front of a third. Your agent groups the two complete pairs and flags the missing back photo. You can identify the two ready coins now and finish the third when you have its other side.

![HeriBase workbench showing two complete front-and-back pairs and a third coin missing its back photo](docs/demo-photo-pairs.webp)

*Workbench demo with sample photos and an English translation of the interface.* [Demo photo credits](docs/demo-credits.md)

<details>
<summary>See what an identification looks like</summary>

After you approve the photos for identification, the workbench shows the suggested coin and the details HeriBase returns. Compare the year and denomination with your photos, then choose whether to save the record.

![Sample identification card for an 1860 Indian Head cent, with both photos and the Save to collection action](docs/demo-identification.webp)

*Sample identification data shown for illustration.*

</details>

## Quick start

Copy this into Codex, Claude Code, or another desktop agent that supports Skills and can run local commands:

```text
Install all six HeriBase Skills from https://github.com/HeriBase/heribase-ability-skills.
Follow the README: copy the skills into my agent's Skills directory and run setup.py --init.
Tell me when I can start. If I need to sign in to HeriBase, let me finish in the browser.
```

<details>
<summary>Install from the terminal</summary>

You need Node.js 24+, Python 3.9+ (3.12 recommended), and Git. This example installs the full set for Codex:

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
```

Use the Skills directory printed by the installer for initialization. In the commands below, replace `<skills-dir>` with that path.

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

For Claude Code, Gemini CLI, or OpenCode, replace `codex` with `claude-code`, `gemini-cli`, or `opencode`. Omit `--global` to install for the current project. If the agent doesn't see the skills, start a new session.

</details>

[Installation and troubleshooting](docs/installation.md)

## Try it with your photos

```text
Organize the coin photos in this folder. Pair the fronts and backs, show me any missing or uncertain photos, and let me review the pairs before identification.
```

## Keep going with the same collection

- **Pick up where you left off.** Return to a saved batch with its original photos, pairing decisions, and review progress.
- **Follow coins you already own.** Ask for the latest available prices for the coins you track in HeriBase.
- **Check an expert appraisal.** Find out where an appraisal stands and open its report when it is ready.

## Before you start

- You can organize photos before signing in to HeriBase. Your AI agent may process images through its own provider. Online identification and account actions require a HeriBase sign-in.
- You can work in chat or open the local workbench to review photos. Automatic photo sorting after uploading in the workbench requires a signed-in Codex CLI.
- Identifications and reference prices can help with research. They do not authenticate a coin or guarantee its selling price.

<details>
<summary>What's included</summary>

Install the six skills together; they share the same local workspace.

- [Setup and sign-in](skills/heribase-cli/SKILL.md) · `heribase-cli`
- [Local tasks](skills/heribase-task-package/SKILL.md) · `heribase-task-package`
- [Coin collection](skills/heribase-collection/SKILL.md) · `heribase-collection`
- [Local workbench](skills/heribase-workspace/SKILL.md) · `heribase-workspace`
- [Expert appraisal](skills/heribase-appraisal/SKILL.md) · `heribase-appraisal`
- [Price tracking](skills/heribase-tracking/SKILL.md) · `heribase-tracking`

</details>

## Help

[Report an issue](https://github.com/HeriBase/heribase-ability-skills/issues). Please leave out account details, credentials, and private coin photos.
