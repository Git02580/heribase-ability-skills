# HeriBase Connector

**Convierte una carpeta de fotos de monedas en una colección.**

¿Tienes fotos de monedas sin nombrar o una hoja de cálculo con imágenes? Dale todo el lote a Codex, Claude Code u otro agente de IA compatible. HeriBase Connector le ayuda a emparejar anversos y reversos, señalar las fotos que faltan, identificar las monedas que elijas y guardar en HeriBase los resultados que apruebes.

**[Inicio rápido](#inicio-rápido)** · [Sitio oficial de HeriBase](https://www.heribase.com/es/) · [Novedades (en inglés)](../CHANGELOG.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · **Español** · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## De cinco fotos a tres fichas de monedas

Imagina una carpeta con ambas caras de dos monedas y solo el anverso de una tercera. El agente reúne los dos pares completos y marca el reverso que falta. Puedes identificar ya las dos primeras y volver a la tercera cuando tengas la otra foto.

![Espacio de trabajo de HeriBase con dos pares completos y una tercera moneda a la que le falta el reverso](demo-photo-pairs.webp)

*Demostración con fotos de muestra y la interfaz traducida al inglés.* [Créditos de las fotos](demo-credits.md)

<details>
<summary>Así se ve una identificación</summary>

Tras confirmar las fotos que quieres identificar, verás la moneda sugerida y los datos devueltos por HeriBase. Compara el año y el valor facial con tus fotos y decide si quieres guardar la ficha.

![Ficha de ejemplo de un centavo Indian Head de 1860, con ambas caras y el botón para guardar en la colección](demo-identification.webp)

*Los datos de identificación de la ficha son de ejemplo.*

</details>

## Inicio rápido

Copia este mensaje en Codex, Claude Code u otro agente de escritorio compatible con Skills y capaz de ejecutar comandos locales:

```text
Instala las seis HeriBase Skills desde https://github.com/HeriBase/heribase-ability-skills.
Sigue el README: copia todas las Skills al directorio de Skills de mi agente y ejecuta setup.py --init.
Dime cómo empezar cuando todo esté listo. Si necesito iniciar sesión en HeriBase, deja que lo haga en el navegador.
```

<details>
<summary>Instalar desde la terminal</summary>

Necesitas Node.js 24 o posterior, Python 3.9 o posterior (se recomienda 3.12) y Git. Este ejemplo instala el conjunto completo para Codex:

```sh
npx skills add HeriBase/heribase-ability-skills --skill '*' --agent codex --global --copy
```

Usa el directorio de Skills que indica el instalador. Sustituye `<skills-dir>` en los siguientes comandos por esa ruta.

**macOS / Linux**

```sh
python3 "<skills-dir>/heribase-cli/scripts/setup.py" --init
```

**Windows PowerShell**

```powershell
py -3 "<skills-dir>\heribase-cli\scripts\setup.py" --init
```

Si usas Claude Code, Gemini CLI u OpenCode, cambia `codex` por `claude-code`, `gemini-cli` u `opencode`. Quita `--global` si quieres instalar las Skills solo en el proyecto actual. Si el agente no las encuentra, abre una sesión nueva.

</details>

[Instalación y solución de problemas (en inglés)](../docs/installation.md)

## Pruébalo con tus fotos

> Organiza las fotos de monedas de esta carpeta. Empareja anversos y reversos, señala las fotos que faltan y los pares dudosos, y espera a que los revise antes de identificar las monedas.

## Sigue trabajando con tu colección

- **Retoma un lote.** Conserva las fotos originales, los pares que revisaste y el punto en el que te quedaste.
- **Consulta los precios de tus monedas.** Pide al agente los últimos precios disponibles para las monedas que sigues en HeriBase.
- **Consulta una tasación.** Revisa el estado de una tasación por un especialista y abre el informe cuando esté listo.

## Antes de empezar

- Puedes ordenar las fotos sin iniciar sesión en HeriBase. El agente de IA puede procesarlas a través de su propio proveedor. La identificación en línea y las acciones en tu cuenta requieren iniciar sesión en HeriBase.
- Puedes trabajar en el chat o revisar las fotos en el espacio de trabajo local. Para ordenar automáticamente las fotos que subas a ese espacio, necesitas tener una sesión iniciada en Codex CLI.
- La identificación y los precios de referencia sirven para investigar. No certifican la autenticidad de una moneda ni garantizan su precio de venta.

<details>
<summary>Qué incluye</summary>

Instala las seis Skills juntas: comparten el mismo espacio de trabajo local.

- [Configuración e inicio de sesión](../skills/heribase-cli/SKILL.md) · `heribase-cli`
- [Tareas locales](../skills/heribase-task-package/SKILL.md) · `heribase-task-package`
- [Colección de monedas](../skills/heribase-collection/SKILL.md) · `heribase-collection`
- [Espacio de trabajo local](../skills/heribase-workspace/SKILL.md) · `heribase-workspace`
- [Tasación por especialistas](../skills/heribase-appraisal/SKILL.md) · `heribase-appraisal`
- [Seguimiento de precios](../skills/heribase-tracking/SKILL.md) · `heribase-tracking`

</details>

## Ayuda

[Notificar un problema](https://github.com/HeriBase/heribase-ability-skills/issues). No incluyas datos de tu cuenta, credenciales ni fotos privadas.
