# Install and troubleshoot HeriBase Connector

[Quick start](../README.md) · [简体中文安装说明](../skills/heribase-cli/references/installation.md) · [HeriBase website](https://www.heribase.com/)

## 1. Install all six Skills

Use a desktop AI agent that supports Agent Skills and can run local commands. You need **Node.js 24+**, **Python 3.9+** with `venv` and `pip` (3.12 recommended), and **Git**. Check `node --version`, `python3 --version` (on Windows, `py -3 --version`), and `git --version` first.

- **macOS:** Use the official [Python](https://www.python.org/downloads/) and [Node.js](https://nodejs.org/en/download) installers, or Homebrew. If you use Homebrew, follow its PATH instructions so the required versions are available to your agent.
- **Linux:** Use your distribution's package manager for Python, venv, and Git (for example, `sudo apt install python3 python3-venv git` on Ubuntu or Debian). Use the [Node.js installation instructions](https://nodejs.org/en/download) if your package manager supplies an older version.
- **Windows:** Install [Python](https://www.python.org/downloads/windows/), [Node.js](https://nodejs.org/en/download), and [Git](https://git-scm.com/downloads/win). Enable the Python launcher and pip, then reopen PowerShell and your agent.

For a user-wide Codex installation, run:

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
```

For Claude Code, Gemini CLI, or OpenCode, substitute `claude-code`, `gemini-cli`, or `opencode` for `codex`. Omit `--global` for a project-only install. Use the actual destination shown by the installer.

To install manually, copy all six `heribase-*` folders under [`skills/`](../skills/) into your agent's Skills directory. Keep them side by side, including their scripts, references, and assets. Cloning this repository alone does not install the skills.

## 2. Initialize the installation

The installer copies files. Initialization prepares the Python environment, checks the bundled HeriBase CLI, and configures the default HeriBase service if it is not already configured. Existing settings are preserved.

Replace `<skills-dir>` with the actual directory containing the six installed folders.

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

`ok: true` means initialization succeeded. If `authenticated` is false, you can still start by organizing photos. For online identification and account actions, ask your agent to help you sign in to HeriBase and complete the sign-in yourself in the browser. A saved sign-in can expire; sign in again if the service rejects it.

For later Python commands, use the interpreter path returned by initialization. It is normally inside `heribase-cli/.venv`.

## 3. Start in chat or open the workbench

Try: “Pair the front and back photos in this folder and show me the uncertain pairs.” For a single coin, send both sides and ask your agent to identify it. Review the photos before identification and the result before saving to your collection.

Ask your agent to open the local workbench if you want to review the photos in a browser. Automatic sorting after upload in the workbench requires a signed-in [Codex CLI](https://developers.openai.com/codex/cli/). This is separate from your HeriBase sign-in. You can still start in chat with another compatible agent.

Your local tasks and HeriBase sign-in settings are stored under `.heribase` in your home folder. Initialization does not upload coin photos.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| My agent can't find the skills | Check the installation directory and that all six folders are present, then open a new session. |
| A skill can't find its companion files | Reinstall all six together with `--copy`. |
| Python modules are missing | Check that venv and pip are available, rerun `--init`, and use the `python` path it returns. |
| Node is missing or too old | Install Node.js 24 or later, reopen the terminal and agent, and check `node --version`. |
| The workbench does not automatically sort photos | Check that Codex CLI is installed and signed in. |
| HeriBase says I am not signed in | Ask the agent to start HeriBase sign-in again; complete it in the browser. |

For a read-only environment check, replace `--init` with `--check`. When [reporting an issue](https://github.com/HeriBase/heribase-ability-skills/issues), include your operating system, agent, and the error with private information removed.
