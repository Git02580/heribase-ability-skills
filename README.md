# HeriBase Connector

**Turn a folder of coin photos into a collection.**

If you have a camera roll full of unnamed coin photos or a spreadsheet with images, give the whole batch to Codex, Claude Code, or another compatible AI agent. HeriBase Connector helps it pair fronts and backs, flag missing photos, identify the coins you choose, and save the results you approve to your HeriBase collection.

**[Quick start](#quick-start)** · [See the workflow](#from-five-photos-to-three-coin-records) · [HeriBase website](https://www.heribase.com/) · [What's new](CHANGELOG.md)

**[See what we verified](docs/verification.md)** · HeriBase mobile app: [App Store](https://apps.apple.com/us/app/heribase-ai-coin-identifier/id6762598274) · [Google Play](https://play.google.com/store/apps/details?id=com.weipaitang.coin)

[![Connector checks on GitHub](https://github.com/HeriBase/heribase-ability-skills/actions/workflows/connector-checks.yml/badge.svg?branch=main)](https://github.com/HeriBase/heribase-ability-skills/actions/workflows/connector-checks.yml)

**English** · [Chinese (Simplified)](docs/README.zh-CN.md) · [Chinese (Traditional)](docs/README.zh-HK.md) · [Japanese](docs/README.ja.md) · [Spanish](docs/README.es.md) · [Portuguese (Brazil)](docs/README.pt-BR.md) · [German](docs/README.de.md) · [French](docs/README.fr.md)

## From five photos to three coin records

This sample contains both sides of two coins and just the front of a third. In two live Codex runs, the organizer saved all five photos separately. After we manually confirmed two pairs, reopening the task showed both pairs and the third coin still missing its back photo. [Download the photos and compare the recorded results](docs/verification.md#five-photo-workbench-check).

![HeriBase workbench showing two complete front-and-back pairs and a third coin missing its back photo](docs/demo-photo-pairs.webp)

*Workbench illustration of the reviewed state, with English labels.* [Demo photo credits](docs/demo-credits.md)

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

[Download the five sample photos](docs/coin-photo-sample.zip) · Unzip the folder and use the photo-pairing prompt below. If the agent leaves photos separate, check them in the workbench. The [recorded run](docs/verification.md#five-photo-workbench-check) includes the reference pairs.

### Sort a folder of photos in one pass

Point your agent at a folder of coin photos from a trip, a show, or an old backup. It groups the fronts and backs it can match and calls out missing photos, possible duplicates, and uncertain pairs. Review those exceptions before choosing what to identify.

```text
Organize the coin photos in this folder. Pair the fronts and backs, list any missing sides or uncertain pairs, and show me the results before identification.
```

## What you can do with your collection

### Start with the catalog you already have

Give the agent an Excel workbook with embedded photos or image links. It can make a draft entry for each row and keep the worksheet and row as its source. Rows with missing or unreadable pictures stay in the batch for you to fix.

```text
Organize this coin spreadsheet. Keep the original worksheet and row for each record, and show me which rows have missing or unreadable photos.
```

### Identify one coin and decide whether to save it

Send clear photos of both sides. Review the photos your agent will submit. When HeriBase returns a suggested match, compare the year, denomination, and any mint mark or reference value supplied for that coin. Save it to your collection when the result looks right.

```text
Identify this coin from these two photos. Show me the result and any fields I should check before I decide whether to add it to my collection.
```

## Keep going with the same collection

### Finish a batch another day

The workspace keeps the original files, the pairs you reviewed, and the work that is still open. Return to the same batch when you find a missing photo, and continue with the coins that still need attention.

```text
Resume the coin batch we worked on last time. Show me the coins that still need a photo and the identifications I have not reviewed.
```

For coins already in HeriBase, you can also check the latest available prices for items you track or look up the status and report of an expert appraisal.

## Before you start

### Frequently asked questions

**Do I need to sign in before I try it?**

You can pair the sample photos first. Sign in to HeriBase when you are ready to identify coins online or use your account. Depending on the agent you choose, its provider may process the images you give it.

**Can I stay in my agent chat?**

Yes. Start in the conversation and ask the agent to open the local workbench when you want a larger view. Automatic sorting after a workbench upload requires a signed-in Codex CLI. HeriBase has a separate sign-in.

**What happens when a coin has only one photo?**

The missing side is flagged. You can continue with the complete pairs and add the missing photo to the same batch later.

**Can I use a suggested match to authenticate a coin?**

Treat the suggested identity and any reference value as research aids. HeriBase offers a separate expert appraisal workflow.

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
