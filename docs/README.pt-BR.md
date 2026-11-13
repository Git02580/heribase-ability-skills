# HeriBase Connector

**Transforme uma pasta de fotos de moedas em uma coleção.**

Tem fotos de moedas sem nome ou uma planilha com imagens? Envie o lote inteiro ao Codex, ao Claude Code ou a outro agente de IA compatível. O HeriBase Connector ajuda a combinar anversos e reversos, sinalizar fotos ausentes, identificar as moedas que você escolher e salvar no HeriBase os resultados aprovados.

**[Início rápido](#início-rápido)** · [Site oficial do HeriBase](https://www.heribase.com/pt-BR/) · [Novidades (em inglês)](../CHANGELOG.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · [Español](README.es.md) · **Português (Brasil)** · [Deutsch](README.de.md) · [Français](README.fr.md)

## De cinco fotos a três registros de moedas

Imagine uma pasta com os dois lados de duas moedas e só o anverso de uma terceira. O agente reúne os dois pares completos e indica qual reverso está faltando. Você já pode identificar as duas primeiras e continuar com a terceira quando tiver a outra foto.

![Espaço de trabalho do HeriBase com dois pares completos e uma terceira moeda sem foto do reverso](demo-photo-pairs.webp)

*Demonstração com fotos de exemplo e interface traduzida para o inglês.* [Créditos das fotos](demo-credits.md)

<details>
<summary>Veja como aparece uma identificação</summary>

Depois de confirmar quais fotos serão usadas, você vê a moeda sugerida e os dados retornados pelo HeriBase. Confira o ano e o valor facial nas suas fotos e decida se quer salvar o registro.

![Registro de exemplo de um centavo Indian Head de 1860, com fotos dos dois lados e a opção de salvar na coleção](demo-identification.webp)

*Os dados de identificação do cartão são ilustrativos.*

</details>

## Início rápido

Copie esta mensagem para o Codex, o Claude Code ou outro agente de desktop que aceite Skills e consiga executar comandos locais:

```text
Instale as seis HeriBase Skills de https://github.com/HeriBase/heribase-ability-skills.
Siga o README: copie as Skills para a pasta de Skills do meu agente e execute setup.py --init.
Avise quando estiver pronto e mostre como começar. Se for preciso entrar no HeriBase, deixe que eu faça isso no navegador.
```

<details>
<summary>Instalar pelo terminal</summary>

Você precisa do Node.js 24 ou superior, do Python 3.9 ou superior (recomendamos o 3.12) e do Git. Este exemplo instala o conjunto completo para o Codex:

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
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

[Instalação e solução de problemas (em inglês)](../docs/installation.md)

## Experimente com suas fotos

> Organize as fotos de moedas desta pasta. Combine anversos e reversos, mostre as fotos que faltam e os pares duvidosos, e espere minha revisão antes de identificar as moedas.

## Continue cuidando da sua coleção

- **Retome um lote.** Volte às fotos originais, às decisões sobre os pares e ao ponto em que parou a revisão.
- **Acompanhe os preços das suas moedas.** Peça os preços mais recentes disponíveis para as moedas que acompanha no HeriBase.
- **Consulte uma avaliação.** Veja o andamento de uma avaliação por especialista e abra o laudo quando estiver pronto.

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

[Relatar um problema](https://github.com/HeriBase/heribase-ability-skills/issues). Não inclua dados da conta, credenciais ou fotos particulares.
