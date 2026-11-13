# HeriBase Connector

<a href="https://www.heribase.com/es/"><img src="heribase-icon.png" alt="HeriBase" width="64" height="64"></a>

**Agent Skills para coleccionistas de monedas**

Envía fotos de tus monedas a tu agente de IA. Puede ordenar y emparejar las imágenes, identificar las monedas con HeriBase y ayudarte a guardar en tu colección los resultados que hayas revisado.

[Sitio oficial de HeriBase](https://www.heribase.com/es/) · [Instalación y solución de problemas (en inglés)](installation.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · **Español** · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

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

## Prueba con tu primera moneda

1. **Envía fotos del anverso y el reverso.** Si tienes muchas fotos, pide al agente que empareje las caras y te muestre las coincidencias dudosas.
2. **Confirma la identificación.** Revisa las fotos seleccionadas antes de que el agente las envíe a HeriBase para identificarlas.
3. **Revisa y guarda.** Comprueba la moneda sugerida y sus datos. Si todo coincide, pide que la añada a tu colección de HeriBase.

## Qué puedes pedir

- “Empareja las fotos del anverso y el reverso de esta carpeta. Muéstrame los pares dudosos.”
- “Identifica esta moneda. Quiero revisar el resultado antes de añadirla a mi colección.”
- “Consulta el estado de mi tasación por un especialista.”
- “Muéstrame los últimos precios disponibles de las monedas que sigo.”

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
