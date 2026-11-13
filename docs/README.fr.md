# HeriBase Connector

**Identifiez une pièce à partir de deux photos et constituez votre collection au fil du temps.**

Envoyez une photo de chaque face à Codex, Claude Code ou à un autre agent compatible sur ordinateur. Connectez-vous à HeriBase, validez les photos et vérifiez l’identification proposée dans la conversation avant de choisir de l’enregistrer. Vous pouvez aussi organiser un dossier de photos ou un tableur et reprendre votre travail plus tard.

**[Identifiez votre première pièce](#identifiez-une-pièce-avant-de-lenregistrer)** · **[Démarrage rapide](#démarrage-rapide)** · [Voir le déroulement](#de-cinq-photos-à-trois-fiches) · [Site officiel de HeriBase](https://www.heribase.com/fr/) · [Nouveautés (en anglais)](../CHANGELOG.md) · [Voir les résultats du test (en anglais)](verification.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · **Français**

## De cinq photos à trois fiches

L’exemple contient les deux faces de deux pièces et seulement l’avers d’une troisième. Lors de deux essais avec Codex, les cinq photos sont restées séparées. Après vérification manuelle, nous avons enregistré deux paires ; il manque toujours le revers de la troisième pièce. [Voir les résultats du test (en anglais)](verification.md#five-photo-workbench-check)

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

### Identifiez une pièce avant de l’enregistrer

Vérifiez les photos sélectionnées. Comparez la pièce proposée avec l’année, la valeur faciale et les autres données fournies par HeriBase. Vous choisissez ensuite d’ajouter la fiche à votre collection.

```text
Identifie la pièce sur ces deux photos. Montre-moi le résultat avant que je décide de l’ajouter à ma collection.
```

## Essayez avec vos photos

[Télécharger les cinq photos d’exemple](coin-photo-sample.zip) · Décompressez les cinq JPEG et utilisez la demande d’association ci-dessous. Vous pourrez comparer le résultat avec la démonstration.

### Triez tout un dossier de photos

Confiez à l’agent vos photos de bourse, de voyage ou d’archives. Il associe les faces, puis signale les photos manquantes, les doublons possibles et les paires incertaines.

```text
Trie ces photos de pièces. Associe les avers et les revers et montre-moi les photos manquantes, les doublons possibles et les paires incertaines avant l’identification.
```

## Que faire avec votre collection ?

### Repartez de votre catalogue Excel

Avec un tableur qui contient des images ou des liens, l’agent prépare une fiche par ligne et conserve le nom de la feuille et le numéro de ligne. Les images manquantes ou illisibles restent à vérifier.

```text
Organise ce tableur. Conserve la feuille et le numéro de ligne, et indique quelles photos sont manquantes ou illisibles.
```

## Continuez à gérer votre collection

### Reprenez le même lot plus tard

L’espace de travail garde les photos d’origine, les paires vérifiées et les tâches en attente. Si vous retrouvez une photo manquante, vous pouvez l’ajouter au même lot.

```text
Reprends le dernier lot de pièces. Montre-moi les photos qui manquent et les résultats d’identification que je dois encore vérifier.
```

Vous pouvez également consulter les derniers prix disponibles des pièces suivies et vérifier l’avancement ou le rapport d’une expertise.

## Avant de commencer

### Questions fréquentes

**Dois-je me connecter pour essayer ?**

Vous pouvez associer les photos d’exemple avant de vous connecter. L’identification en ligne et les actions sur votre compte nécessitent une connexion à HeriBase. Le fournisseur de votre agent peut traiter les images que vous lui transmettez.

**Puis-je rester dans la conversation ?**

Oui. Ouvrez l’espace de travail local pour examiner les photos de plus près. Le tri automatique après un envoi depuis cet espace requiert une session active dans Codex CLI.

**Et s’il manque la photo d’une face ?**

La face manquante est signalée. Vous pouvez traiter les paires complètes, puis ajouter la photo au même lot ultérieurement.

**L’identification certifie-t-elle l’authenticité ?**

Le résultat et le prix de référence aident à faire des recherches. HeriBase propose séparément une expertise.

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
