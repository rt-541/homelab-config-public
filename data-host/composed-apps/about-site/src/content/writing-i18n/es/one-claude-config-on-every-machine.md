---
title: "Una configuración de Claude Code en cada máquina"
dek: "Un mercado de plugins personalizado para las habilidades, un plugin que extrae la configuración global al inicio de la sesión y empuja los cambios locales de vuelta, y un bot de revisión que realiza solicitudes de extracción limpias."
lang: es
source: one-claude-config-on-every-machine
source_hash: 29dccfd0b07ab734
model: qwen3-14b
---

Claude Code se ejecuta aquí en clientes de Windows, clientes de Linux y servidores RHEL. Cada uno tiene un global `CLAUDE.md`, un `settings.json`, algunas habilidades y comandos, y cada uno se ha desviado ligeramente hacia un conjunto diferente. La antigua solución era copiar a mano, o un rol de Ansible que enviaba archivos cuando alguien recordaba ejecutarlo. Ninguna de estas soluciones notaba un cambio hecho en una máquina que nunca regresaba.

## Un mercado para las habilidades

Claude Code puede instalar plugins desde un mercado, y un mercado es simplemente un repositorio git con un manifiesto que enumera sus plugins. El 2026-09-18 un repositorio privado se convirtió en uno. Ahora enumera cinco plugins:

- **workshop**: las habilidades build-plan y shopcad-model detrás de los planes físicos en este sitio;
- **homelab-ops**: la habilidad que envía trabajos de LLM a la flota de homelab;
- **gpu-llm**: una habilidad más un servidor MCP para un modelo local a demanda en una GPU de juego;
- **docs-tools**: diagramas Mermaid y Markdown de Obsidian;
- **config-sync**: el plugin que mantiene todo lo demás actualizado.

La mayoría comenzaron como habilidades sueltas en un repositorio de dotfiles. El plugin gpu-llm existía solo en una máquina, en un commit que nunca se había empujado. Fue extraído del mercado desde ese checkout y cambiado para alcanzar su host por nombre de DNS en lugar de una dirección IP que ya se había desviado.

## Dos fuentes de verdad

El repositorio de dotfiles es la fuente de verdad para los archivos: el global `CLAUDE.md`, `settings.json`, las habilidades que no son plugins y los comandos. El mercado es la fuente de verdad para los plugins, y un cambio en un plugin se envía incrementando su versión. La memoria por proyecto, `settings.local.json`, credenciales y cachés nunca se tocan.

## config-sync

El plugin config-sync, construido el 2026-09-19, es un script de bash y un `SessionStart` hook. Cada inicio de sesión, genera un hash de cada elemento rastreado y aplica lo que sea seguro. El trabajo de red (adelantar el checkout de dotfiles, actualizar el mercado, instalar o actualizar cada plugin que enumere) ocurre como máximo una vez cada 24 horas. Cuando todo está al día, no imprime nada. Cuando algo requiere una decisión, imprime líneas que comienzan con `config-sync:`, y una habilidad en el mismo plugin le dice a Claude cómo leerlas y resolverlas.

La parte que lo hace seguro es un pequeño archivo de estado que contiene el hash aplicado por última vez para cada elemento. Eso convierte cada comparación en una de tres maneras:

- el repositorio se movió y la copia local no lo hizo: aplícalo, en silencio;
- la copia local se movió y el repositorio no lo hizo: reporta esto y nunca sobrescríbalo; `push` lleva el cambio de vuelta al repositorio para que las otras máquinas lo recojan;
- ambos se movieron: reporta un conflicto; `--force` en `apply` o `push` elige al ganador.

`settings.json` se compara como JSON ignorando el orden de las claves, por lo tanto, un archivo reordenado no se considera un cambio.

La superficie del script es pequeña:

```
config-sync.sh status              # what differs, changes nothing
config-sync.sh apply [--force]     # pull, apply safe updates, update plugins
config-sync.sh push [-m msg]       # fold local edits back, commit, push
config-sync.sh diff <key>          # installed vs repo for one item
```

En una nueva máquina, el arranque es de dos líneas: registrar el mercado y instalar config-sync, luego un reinicio. El primer hook de la sesión clona el repositorio de dotfiles e instala la configuración global y los otros cuatro plugins. Windows lo ejecuta bajo Git Bash.

Las pruebas realizan quince verificaciones contra un home y un repositorio de dotfiles de uso temporal con un binario de `claude` estubado y sin conexión a red. En la primera máquina real, `status` adoptó los nueve elementos seguidos como ya en paso, y la primera `push` llevó una nueva sección de la configuración global `CLAUDE.md` de vuelta al repositorio.

## Un bot de revisión, más tarde

El 2026-09-24 se añadió una acción de GitHub para revisar cada solicitud de extracción que no sea un borrador, publicar un veredicto de aprobación o solicitar cambios anclado al commit principal y fusionar las limpias. Solo fusiona cuando el head no haya cambiado, no haya etiqueta `no-automerge` y nada bajo los directorios de workflow o plugin haya cambiado. La primera versión revisó con Claude; una actualización la misma noche movió las revisiones al modelo local gratuito en la flota de NanoClaw para que permanezcan en la LAN. Debido a que el bot no fusionará cambios en su propio directorio de workflow, la solicitud de extracción que lo añade necesitó una persona para fusionarla.

## Lo que no funcionó

- **El rol de Ansible de solo envío.** Se mantiene como un respaldo, pero enviar la configuración no puede ver los cambios realizados en el extremo remoto. Al hacerlo al inicio de la sesión, sí se pueden ver.
- **Escribir el plugin en su lugar.** El modo automático de Claude Code se negó a escribir el script y el archivo de enlace en el directorio del plugin, marcándolo como modificación propia. Colocarlos en otro lugar y copiarlos dentro fue permitido. El bot de revisión se encontró con el mismo problema en su script de fusión ("fusionar sin revisión") y solo fue escrito después de que el propietario lo aprobó fuera del modo automático.
- **Estilos de prueba en `/tmp`.** `/tmp` se monta `noexec` en el servidor principal, por lo tanto, los binarios de prueba colocados allí se omiten silenciosamente y se ejecuta el real. Para config-sync, los estilos ahora se ejecutan a través de `sh`. Para el bot de revisión, las pruebas llegaron al cliente real de GitHub, obtuvieron un 422 y publicaron nada; `gh` ahora se finge como una función de shell.

## ¿Qué se lleva hacia adelante

Un cambio global ahora tiene un solo camino: hacerlo en cualquier máquina, `push`, y el resto convergerá en su próximo inicio de sesión. Un nuevo archivo rastreado es un caso en el script y un incremento de versión. Las copias del repositorio de dotfiles de las habilidades que se movieron a plugins aún están allí, y se mostrarán una vez que cada máquina ejecute config-sync.
