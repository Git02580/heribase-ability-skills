# HeriBase Connector

**Mach aus einem Ordner mit Münzfotos eine Sammlung.**

Hast du viele unbenannte Münzfotos oder eine Tabelle mit Bildern? Gib den ganzen Stapel an Codex, Claude Code oder einen anderen kompatiblen KI-Agenten. Mit HeriBase Connector kann er Vorder- und Rückseiten zuordnen, fehlende Fotos markieren, ausgewählte Münzen bestimmen und geprüfte Ergebnisse in deiner HeriBase-Sammlung speichern.

**[Schnellstart](#schnellstart)** · [Offizielle HeriBase-Website](https://www.heribase.com/de/) · [Änderungen (auf Englisch)](../CHANGELOG.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · **Deutsch** · [Français](README.fr.md)

## Aus fünf Fotos werden drei Münzeinträge

In einem Ordner liegen Vorder- und Rückseiten von zwei Münzen und nur die Vorderseite einer dritten. Der Agent gruppiert die beiden vollständigen Paare und zeigt dir, welche Rückseite fehlt. Bestimme die ersten beiden Münzen gleich und ergänze die dritte später.

![HeriBase-Arbeitsbereich mit zwei vollständigen Fotopaaren und einer dritten Münze ohne Rückseitenfoto](demo-photo-pairs.webp)

*Demo mit Beispielfotos und englisch übersetzter Benutzeroberfläche.* [Bildnachweise](demo-credits.md)

<details>
<summary>So sieht ein Bestimmungsergebnis aus</summary>

Sobald du die Fotos zur Bestimmung freigibst, siehst du den Münzvorschlag und die von HeriBase gelieferten Angaben. Prüfe Jahr und Nennwert anhand deiner Fotos und entscheide dann, ob du den Eintrag speicherst.

![Beispiel für einen Indian-Head-Cent von 1860 mit Fotos beider Seiten und Schaltfläche zum Speichern](demo-identification.webp)

*Die Angaben zur Bestimmung sind Beispieldaten.*

</details>

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

[Installation und Fehlerbehebung (auf Englisch)](../docs/installation.md)

## Mit eigenen Fotos ausprobieren

> Ordne die Münzfotos in diesem Ordner nach Vorder- und Rückseiten zu. Zeig mir fehlende Fotos und unsichere Paare. Warte mit der Bestimmung, bis ich die Paare geprüft habe.

## Arbeite mit deiner Sammlung weiter

- **Setze einen Stapel fort.** Greif auf die Originalfotos, bestätigten Paare und den bisherigen Prüfstand zu.
- **Verfolge die Preise deiner Münzen.** Frag nach den neuesten verfügbaren Preisen für die Münzen, die du in HeriBase beobachtest.
- **Prüfe den Stand einer Begutachtung.** Sieh nach, wie weit die Prüfung ist, und öffne den Bericht, sobald er vorliegt.

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
