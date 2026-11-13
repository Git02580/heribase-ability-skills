# HeriBase Connector

<a href="https://www.heribase.com/"><img src="docs/heribase-icon.png" alt="HeriBase" width="64" height="64"></a>

**Agent Skills for coin collectors**

Send coin photos to your AI agent. It can sort and pair the photos, identify the coins with HeriBase, and help you add reviewed results to your collection.

[HeriBase website](https://www.heribase.com/) · [Installation and troubleshooting](docs/installation.md)

**English** · [简体中文](docs/README.zh-CN.md) · [繁體中文](docs/README.zh-HK.md) · [日本語](docs/README.ja.md) · [Español](docs/README.es.md) · [Português (Brasil)](docs/README.pt-BR.md) · [Deutsch](docs/README.de.md) · [Français](docs/README.fr.md)

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

## Try it with your coins

1. **Send the front and back photos.** For a batch, ask your agent to pair the two sides and show any uncertain matches.
2. **Confirm identification.** Review the selected photos before your agent sends them to HeriBase for identification.
3. **Review and save.** Check the suggested coin and details, then ask your agent to add it to your HeriBase collection.

## What you can ask

- “Pair the front and back photos in this folder. Show me the pairs you're unsure about.”
- “Identify this coin. Let me check the result before adding it to my collection.”
- “Check the status of my expert appraisal.”
- “Show the latest prices available for coins I'm tracking.”

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
