# HeriBase Connector

<a href="https://www.heribase.com/pt-BR/"><img src="heribase-icon.png" alt="HeriBase" width="64" height="64"></a>

**Agent Skills para colecionadores de moedas**

Envie fotos de moedas ao seu agente de IA. Ele pode organizar e parear as imagens, identificar as moedas com o HeriBase e ajudar a salvar na sua coleção os resultados que você revisar.

[Site oficial do HeriBase](https://www.heribase.com/pt-BR/) · [Instalação e solução de problemas (em inglês)](installation.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · **Português (Brasil)** · [Deutsch](README.de.md) · [Français](README.fr.md)

## Início rápido

Copie esta mensagem para o Codex, o Claude Code ou outro agente de desktop que aceite Skills e consiga executar comandos locais:

```text
Instale as seis HeriBase Skills de https://github.com/Git02580/heribase-ability-skills.
Siga o README: copie as Skills para a pasta de Skills do meu agente e execute setup.py --init.
Avise quando estiver pronto e mostre como começar. Se for preciso entrar no HeriBase, deixe que eu faça isso no navegador.
```

<details>
<summary>Instalar pelo terminal</summary>

Você precisa do Node.js 24 ou superior, do Python 3.9 ou superior (recomendamos o 3.12) e do Git. Este exemplo instala o conjunto completo para o Codex:

```sh
npx skills add Git02580/heribase-ability-skills --skill '*' --agent codex --global --copy
```

Use a pasta de Skills informada pelo instalador. Substitua `<skills-dir>` pelo caminho dessa pasta nos comandos abaixo.

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

Para o Claude Code, o Gemini CLI ou o OpenCode, troque `codex` por `claude-code`, `gemini-cli` ou `opencode`. Para instalar apenas no projeto atual, remova `--global`. Se o agente não encontrar as Skills, abra uma nova sessão.

</details>

## Experimente com sua primeira moeda

1. **Envie fotos do anverso e do reverso.** Se tiver várias fotos, peça ao agente para formar os pares e mostrar aqueles sobre os quais houver dúvida.
2. **Confirme a identificação.** Confira as fotos selecionadas antes que o agente as envie ao HeriBase para identificar as moedas.
3. **Revise e salve.** Confira a moeda sugerida e seus dados. Se estiver tudo certo, peça ao agente para adicioná-la à sua coleção no HeriBase.

## O que você pode pedir

- “Combine as fotos do anverso e do reverso nesta pasta. Mostre os pares sobre os quais você tiver dúvida.”
- “Identifique esta moeda. Quero conferir o resultado antes de adicioná-la à coleção.”
- “Consulte o andamento da minha avaliação por um especialista.”
- “Mostre os preços mais recentes disponíveis para as moedas que acompanho.”

## Antes de começar

- Você pode organizar as fotos antes de entrar no HeriBase. O agente de IA pode processar imagens usando seu próprio provedor. A identificação on-line e as ações na conta exigem login no HeriBase.
- Trabalhe no chat ou abra o espaço de trabalho local para revisar as fotos. Para organizar automaticamente as fotos enviadas por esse espaço, é preciso estar com uma sessão iniciada no Codex CLI.
- A identificação e os preços de referência ajudam na pesquisa. Eles não autenticam a moeda nem garantem o preço de venda.

<details>
<summary>O que está incluído</summary>

Instale as seis Skills juntas, pois elas compartilham o mesmo espaço de trabalho local.

- [Configuração e login](../skills/heribase-cli/SKILL.md) · `heribase-cli`
- [Tarefas locais](../skills/heribase-task-package/SKILL.md) · `heribase-task-package`
- [Coleção de moedas](../skills/heribase-collection/SKILL.md) · `heribase-collection`
- [Espaço de trabalho local](../skills/heribase-workspace/SKILL.md) · `heribase-workspace`
- [Avaliação por especialistas](../skills/heribase-appraisal/SKILL.md) · `heribase-appraisal`
- [Acompanhamento de preços](../skills/heribase-tracking/SKILL.md) · `heribase-tracking`

</details>

## Ajuda

[Relatar um problema](https://github.com/Git02580/heribase-ability-skills/issues). Não inclua dados da conta, credenciais ou fotos particulares.
