# HeriBase Connector

**Transformez un dossier de photos de pièces en collection.**

Vous avez des photos de pièces sans nom ou un tableur avec des images ? Confiez le lot à Codex, Claude Code ou à un autre agent IA compatible. HeriBase Connector l’aide à associer avers et revers, signaler les photos manquantes, identifier les pièces de votre choix et enregistrer dans HeriBase les résultats que vous avez vérifiés.

**[Démarrage rapide](#démarrage-rapide)** · [Site officiel de HeriBase](https://www.heribase.com/fr/) · [Nouveautés (en anglais)](../CHANGELOG.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · **Français**

## De cinq photos à trois fiches

Imaginez un dossier avec les deux faces de deux pièces et seulement l’avers d’une troisième. L’agent rassemble les deux paires complètes et vous signale le revers manquant. Vous pouvez faire identifier les deux premières pièces, puis reprendre la troisième après avoir ajouté sa photo.

![Espace HeriBase avec deux paires complètes et une troisième pièce dont la photo du revers manque](demo-photo-pairs.webp)

*Démonstration avec des photos d’exemple et une interface traduite en anglais.* [Crédits photo](demo-credits.md)

<details>
<summary>Voir un exemple d’identification</summary>

Après validation des photos, l’espace de travail affiche la pièce proposée et les données fournies par HeriBase. Comparez l’année et la valeur faciale avec vos photos, puis décidez si vous souhaitez enregistrer la fiche.

![Fiche d’exemple d’un cent Indian Head de 1860, avec les deux faces et le bouton d’ajout à la collection](demo-identification.webp)

*Les données d’identification de cette fiche sont fournies à titre d’exemple.*

</details>

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

[Installation et dépannage (en anglais)](../docs/installation.md)

## Essayez avec vos photos

> Trie les photos de pièces de ce dossier. Associe les avers et les revers, signale les photos manquantes et les paires incertaines, et attends ma vérification avant de lancer l’identification.

## Continuez à gérer votre collection

- **Reprenez un lot en cours.** Retrouvez les photos d’origine, les paires validées et l’avancement de la vérification.
- **Suivez le prix de vos pièces.** Demandez les derniers prix disponibles pour les pièces que vous suivez dans HeriBase.
- **Suivez une expertise.** Consultez l’état de l’expertise et ouvrez le rapport dès qu’il est prêt.

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
