# HeriBase Connector

**Mach aus einem Ordner mit Münzfotos eine Sammlung.**

Hast du viele unbenannte Münzfotos oder eine Tabelle mit Bildern? Gib den ganzen Stapel an Codex, Claude Code oder einen anderen kompatiblen KI-Agenten. Mit HeriBase Connector kann er Vorder- und Rückseiten zuordnen, fehlende Fotos markieren, ausgewählte Münzen bestimmen und geprüfte Ergebnisse in deiner HeriBase-Sammlung speichern.

**[Schnellstart](#schnellstart)** · [Ablauf ansehen](#aus-fünf-fotos-werden-drei-münzeinträge) · [Offizielle HeriBase-Website](https://www.heribase.com/de/) · [Änderungen (auf Englisch)](../CHANGELOG.md)

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

[Fünf Beispielfotos herunterladen](coin-photo-sample.zip) · Entpacke die fünf JPEGs und verwende die folgende Anweisung zum Zuordnen der Fotos. Vergleiche das Ergebnis mit der Vorschau.

### Einen ganzen Fotoordner sortieren

Gib dem Agenten Münzfotos von einer Messe, einer Reise oder aus einem alten Backup. Er ordnet passende Seiten zu und zeigt fehlende Fotos, mögliche Duplikate und unsichere Paare.

```text
Sortiere diese Münzfotos. Ordne Vorder- und Rückseiten zu und zeige mir fehlende Fotos, mögliche Duplikate und unsichere Paare vor der Bestimmung.
```

## Was du mit deiner Sammlung machen kannst

### Einen vorhandenen Katalog übernehmen

Aus einer Excel-Tabelle mit Bildern oder Bildlinks kann der Agent einen Entwurf pro Zeile anlegen. Tabellenblatt und Zeilennummer bleiben erhalten. Fehlende oder unlesbare Bilder werden zur Prüfung markiert.

```text
Ordne diese Münztabelle. Behalte Blatt und Zeilennummer bei und markiere Zeilen mit fehlenden oder unlesbaren Bildern.
```

### Eine Münze bestimmen und dann speichern

Prüfe die Fotos, die du zur Bestimmung freigibst. Vergleiche den Vorschlag mit Jahr, Nennwert und weiteren von HeriBase gelieferten Angaben. Danach entscheidest du, ob du die Münze speicherst.

```text
Bestimme die Münze auf diesen beiden Fotos. Zeig mir das Ergebnis, bevor ich entscheide, ob ich sie in meiner Sammlung speichere.
```

## Arbeite mit deiner Sammlung weiter

### An einem anderen Tag weitermachen

Die Originalfotos, geprüften Paare und offenen Schritte bleiben im Arbeitsbereich. Sobald du das fehlende Foto findest, kannst du es im selben Stapel ergänzen.

```text
Setze den letzten Münzstapel fort. Zeig mir fehlende Fotos und die Bestimmungsergebnisse, die ich noch prüfen muss.
```

Außerdem kannst du die neuesten verfügbaren Preise beobachteter Münzen oder den Stand und Bericht einer Expertenbegutachtung abrufen.

## Vor dem Start

### Häufig gestellte Fragen

**Brauche ich zum Ausprobieren ein Konto?**

Du kannst die Beispielfotos vor der Anmeldung zuordnen. Für Online-Bestimmung und Kontoaktionen meldest du dich bei HeriBase an. Dein Agentenanbieter kann die übergebenen Bilder verarbeiten.

**Kann ich im Chat bleiben?**

Ja. Zum genauen Prüfen kannst du den lokalen Arbeitsbereich öffnen. Die automatische Zuordnung nach einem Upload dort setzt eine aktive Codex-CLI-Anmeldung voraus.

**Was passiert, wenn ein Foto fehlt?**

Die fehlende Seite wird markiert. Die vollständigen Paare kannst du zuerst bearbeiten und das fehlende Foto später im selben Stapel ergänzen.

**Bestätigt die Bestimmung die Echtheit?**

Münzvorschläge und Referenzpreise helfen bei der Recherche. HeriBase bietet eine separate Expertenbegutachtung.

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
