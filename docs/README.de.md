# HeriBase Connector

<a href="https://www.heribase.com/de/"><img src="heribase-icon.png" alt="HeriBase" width="64" height="64"></a>

**Agent Skills für Münzsammler**

Schicke deinem KI-Agenten Fotos deiner Münzen. Er kann die Aufnahmen sortieren, Vorder- und Rückseiten zuordnen, Münzen mit HeriBase bestimmen und dir helfen, geprüfte Ergebnisse in deiner Sammlung zu speichern.

[Offizielle HeriBase-Website](https://www.heribase.com/de/) · [Installation und Fehlerbehebung (auf Englisch)](installation.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · **Deutsch** · [Français](README.fr.md)

## Schnellstart

Sende diese Nachricht an Codex, Claude Code oder einen anderen Desktop-Agenten, der Skills unterstützt und lokale Befehle ausführen kann:

```text
Installiere alle sechs HeriBase Skills von https://github.com/HeriBase/heribase-ability-skills.
Folge der README: Kopiere die Skills in das Skills-Verzeichnis meines Agenten und führe setup.py --init aus.
Sag mir, wenn alles bereit ist, und zeig mir, wie ich anfange. Falls eine Anmeldung bei HeriBase nötig ist, möchte ich sie im Browser selbst abschließen.
```

<details>
<summary>Über das Terminal installieren</summary>

Du brauchst Node.js ab Version 24, Python ab Version 3.9 (empfohlen: 3.12) und Git. Dieses Beispiel installiert das komplette Paket für Codex:

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
```

Verwende für die Einrichtung das vom Installer angezeigte Skills-Verzeichnis. Ersetze in den Befehlen unten `<skills-dir>` durch diesen Pfad.

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

Ersetze für Claude Code, Gemini CLI oder OpenCode `codex` durch `claude-code`, `gemini-cli` oder `opencode`. Lass `--global` weg, wenn du die Skills nur im aktuellen Projekt verwenden möchtest. Starte eine neue Sitzung, falls dein Agent die Skills nicht findet.

</details>

## Mit der ersten Münze loslegen

1. **Sende Fotos der Vorder- und Rückseite.** Bei mehreren Münzen kannst du den Agenten bitten, passende Fotos zuzuordnen und unsichere Paare zu zeigen.
2. **Bestätige die Bestimmung.** Prüfe die ausgewählten Fotos, bevor der Agent sie zur Bestimmung an HeriBase sendet.
3. **Prüfe und speichere das Ergebnis.** Vergleiche den Münzvorschlag und die Details mit deinem Stück. Bitte dann den Agenten, es bei Bedarf zur HeriBase-Sammlung hinzuzufügen.

## Das kannst du deinen Agenten fragen

- “Ordne die Fotos in diesem Ordner nach Vorder- und Rückseite zu. Zeig mir die unsicheren Paare.”
- “Bestimme diese Münze. Ich möchte das Ergebnis prüfen, bevor sie in meine Sammlung kommt.”
- “Prüfe den Stand meiner Expertenbegutachtung.”
- “Zeig mir die neuesten verfügbaren Preise für die Münzen, die ich beobachte.”

## Vor dem Start

- Fotos lassen sich vor der Anmeldung bei HeriBase sortieren. Dein KI-Agent kann Bilder über seinen eigenen Anbieter verarbeiten. Für die Online-Bestimmung und Kontoaktionen musst du dich bei HeriBase anmelden.
- Du kannst im Chat arbeiten oder Fotos im lokalen Arbeitsbereich prüfen. Damit dort hochgeladene Fotos automatisch sortiert werden, musst du bei Codex CLI angemeldet sein.
- Bestimmungen und Referenzpreise dienen als Orientierung. Sie bestätigen weder die Echtheit einer Münze noch einen Verkaufspreis.

<details>
<summary>Enthaltene Skills</summary>

Installiere alle sechs Skills zusammen. Sie nutzen denselben lokalen Arbeitsbereich.

- [Einrichtung und Anmeldung](../skills/heribase-cli/SKILL.md) · `heribase-cli`
- [Lokale Aufgaben](../skills/heribase-task-package/SKILL.md) · `heribase-task-package`
- [Münzsammlung](../skills/heribase-collection/SKILL.md) · `heribase-collection`
- [Lokaler Arbeitsbereich](../skills/heribase-workspace/SKILL.md) · `heribase-workspace`
- [Expertenbegutachtung](../skills/heribase-appraisal/SKILL.md) · `heribase-appraisal`
- [Preisbeobachtung](../skills/heribase-tracking/SKILL.md) · `heribase-tracking`

</details>

## Hilfe

[Ein Problem melden](https://github.com/HeriBase/heribase-ability-skills/issues). Bitte füge keine Kontodaten, Zugangsdaten oder privaten Münzfotos bei.
