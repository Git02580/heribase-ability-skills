# HeriBase Connector

<a href="https://www.heribase.com/fr/"><img src="heribase-icon.png" alt="HeriBase" width="64" height="64"></a>

**Agent Skills pour les collectionneurs de monnaies**

Envoyez des photos de vos pièces à votre agent IA. Il peut trier et associer les images, identifier les pièces avec HeriBase et vous aider à ajouter à votre collection les résultats que vous avez vérifiés.

[Site officiel de HeriBase](https://www.heribase.com/fr/) · [Installation et dépannage (en anglais)](installation.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · **Français**

## Démarrage rapide

Copiez ce message dans Codex, Claude Code ou un autre agent de bureau capable de charger des Skills et d’exécuter des commandes locales :

```text
Installe les six HeriBase Skills depuis https://github.com/HeriBase/heribase-ability-skills.
Suis le README : copie les Skills dans le dossier de mon agent, puis exécute setup.py --init.
Indique-moi quand tout est prêt et comment commencer. Si je dois me connecter à HeriBase, laisse-moi le faire dans le navigateur.
```

<details>
<summary>Installer depuis le terminal</summary>

Il vous faut Node.js 24 ou plus, Python 3.9 ou plus (3.12 recommandé) et Git. Cet exemple installe les six Skills pour Codex :

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
```

Utilisez le dossier de Skills indiqué par l’installateur. Dans les commandes ci-dessous, remplacez `<skills-dir>` par le chemin de ce dossier.

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

Pour Claude Code, Gemini CLI ou OpenCode, remplacez `codex` par `claude-code`, `gemini-cli` ou `opencode`. Retirez `--global` pour une installation limitée au projet en cours. Si l’agent ne trouve pas les Skills, ouvrez une nouvelle session.

</details>

## Essayez avec votre première pièce

1. **Envoyez des photos de l’avers et du revers.** Si vous avez plusieurs pièces, demandez à l’agent d’associer les photos et de vous signaler les paires incertaines.
2. **Confirmez l’identification.** Vérifiez les photos sélectionnées avant que l’agent ne les transmette à HeriBase pour identification.
3. **Vérifiez et enregistrez.** Vérifiez la pièce proposée et ses caractéristiques, puis demandez à l’agent de l’ajouter à votre collection HeriBase si le résultat vous convient.

## Ce que vous pouvez demander

- “Associe les photos de l’avers et du revers dans ce dossier. Montre-moi les paires dont tu n’es pas sûr.”
- “Identifie cette pièce. Je veux vérifier le résultat avant de l’ajouter à ma collection.”
- “Vérifie l’avancement de mon expertise.”
- “Montre-moi les derniers prix disponibles pour les pièces que je suis.”

## Avant de commencer

- Vous pouvez trier des photos avant de vous connecter à HeriBase. Votre agent IA peut faire traiter les images par son propre fournisseur. L’identification en ligne et les actions sur votre compte nécessitent une connexion à HeriBase.
- Vous pouvez travailler dans la conversation ou ouvrir l’espace de travail local pour vérifier les photos. Le tri automatique des photos ajoutées à cet espace nécessite une session active dans Codex CLI.
- Les identifications et les prix de référence aident à faire des recherches. Ils ne certifient pas l’authenticité d’une pièce et ne garantissent pas son prix de vente.

<details>
<summary>Skills incluses</summary>

Installez les six Skills ensemble : elles partagent le même espace de travail local.

- [Configuration et connexion](../skills/heribase-cli/SKILL.md) · `heribase-cli`
- [Tâches locales](../skills/heribase-task-package/SKILL.md) · `heribase-task-package`
- [Collection de monnaies](../skills/heribase-collection/SKILL.md) · `heribase-collection`
- [Espace de travail local](../skills/heribase-workspace/SKILL.md) · `heribase-workspace`
- [Expertise numismatique](../skills/heribase-appraisal/SKILL.md) · `heribase-appraisal`
- [Suivi des prix](../skills/heribase-tracking/SKILL.md) · `heribase-tracking`

</details>

## Aide

[Signaler un problème](https://github.com/HeriBase/heribase-ability-skills/issues). N’ajoutez pas de données de compte, d’identifiants ni de photos privées.
