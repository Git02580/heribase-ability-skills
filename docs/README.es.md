# HeriBase Connector

**Convierte una carpeta de fotos de monedas en una colección.**

¿Tienes fotos de monedas sin nombrar o una hoja de cálculo con imágenes? Dale todo el lote a Codex, Claude Code u otro agente de IA compatible. HeriBase Connector le ayuda a emparejar anversos y reversos, señalar las fotos que faltan, identificar las monedas que elijas y guardar en HeriBase los resultados que apruebes.

**[Inicio rápido](#inicio-rápido)** · [Ver cómo funciona](#de-cinco-fotos-a-tres-fichas-de-monedas) · [Sitio oficial de HeriBase](https://www.heribase.com/es/) · [Novedades (en inglés)](../CHANGELOG.md) · [Ver la comprobación (en inglés)](verification.md)

[English](../README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-HK.md) · [日本語](README.ja.md) · **Español** · [Português (Brasil)](README.pt-BR.md) · [Deutsch](README.de.md) · [Français](README.fr.md)

## De cinco fotos a tres fichas de monedas

La muestra incluye las dos caras de dos monedas y solo el anverso de una tercera. En dos pruebas con Codex, las cinco fotos quedaron separadas. Tras revisarlas manualmente, guardamos dos pares y dejamos indicada la falta del reverso de la tercera moneda. [Ver la comprobación (en inglés)](verification.md#five-photo-workbench-check)

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

[Descargar las cinco fotos de muestra](coin-photo-sample.zip) · Descomprime el archivo y prueba el mensaje de emparejamiento con los cinco JPEG. Puedes comparar tus resultados con el ejemplo.

### Ordena una carpeta de fotos de una vez

Dale al agente las fotos de una feria, un viaje o una copia antigua. Agrupa las caras que puede emparejar y te muestra las fotos que faltan, los posibles duplicados y las parejas dudosas.

```text
Organiza estas fotos de monedas. Empareja anversos y reversos y señala las fotos que falten, los duplicados y las parejas dudosas antes de identificar las monedas.
```

## Qué puedes hacer con tu colección

### Aprovecha el catálogo que ya tienes

Si tu archivo de Excel contiene imágenes o enlaces a ellas, el agente puede preparar una ficha por fila y conservar la hoja y el número de fila. Las imágenes ausentes o ilegibles quedan pendientes de revisión.

```text
Organiza esta hoja de monedas. Conserva la hoja y la fila de origen e indica qué filas tienen fotos que faltan o que no se pueden leer.
```

### Identifica una moneda antes de guardarla

Confirma las fotos que se enviarán. Cuando veas la sugerencia, compara el año, el valor facial y las demás características que HeriBase haya devuelto. Tú decides si se guarda en la colección.

```text
Identifica esta moneda con estas dos fotos. Muéstrame el resultado antes de que decida si la añado a mi colección.
```

## Sigue trabajando con tu colección

### Retoma el trabajo otro día

El espacio de trabajo conserva las fotos, las parejas que revisaste y los asuntos pendientes. Cuando encuentres una foto que falte, puedes añadirla al mismo lote.

```text
Retoma el último lote de monedas. Muéstrame cuáles necesitan fotos y qué identificaciones quedan por revisar.
```

También puedes consultar los últimos precios disponibles de las monedas que sigues y revisar el estado o el informe de una tasación por un especialista.

## Antes de empezar

### Preguntas frecuentes

**¿Tengo que iniciar sesión para probarlo?**

Puedes empezar emparejando las fotos de muestra. Para identificar monedas en línea o usar tu cuenta, inicia sesión en HeriBase. El proveedor de tu agente puede procesar las imágenes que le envíes.

**¿Puedo seguir en el chat?**

Sí. Abre el espacio de trabajo local cuando quieras revisar las fotos en detalle. Para ordenar automáticamente las fotos que subas allí, necesitas una sesión activa en Codex CLI.

**¿Y si solo tengo una cara?**

El agente señala la cara que falta. Puedes continuar con los pares completos y añadir la foto al mismo lote después.

**¿La identificación certifica la autenticidad?**

Usa el resultado y el precio de referencia como pistas para investigar. La tasación por un especialista es un servicio separado de HeriBase.

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
