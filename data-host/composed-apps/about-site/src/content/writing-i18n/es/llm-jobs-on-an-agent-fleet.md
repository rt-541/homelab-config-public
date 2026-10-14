---
title: "Trabajo con LLM en una flota de agentes"
dek: "El servicio de trabajos de LLM de \"fire-and-forget\" del homelab, primero construido como una cola frente a un gateway LiteLLM, luego reconstruido para que cada trabajo sea una tarea de un solo disparo para un grupo de agentes NanoClaw, con capas de renderizado local, Claude y Blender."
lang: es
source: llm-jobs-on-an-agent-fleet
source_hash: a4f84adc1c843c27
model: qwen3-14b
---

Algunos trabajos con LLM no deben realizarse en la sesión que los considera: cien resúmenes, un lote de clasificaciones, un borrador largo de baja importancia, cualquier cosa privada que deba permanecer en la LAN. El homelab tiene un pequeño servicio para eso. Un solicitante envía un prompt y un nivel, recibe un ID de trabajo de inmediato y recoge el resultado más tarde. Ahora ha sido construido dos veces.

## Versión uno: una cola y un gateway

La versión de junio de 2026 se ejecutó en nemesis como dos stacks. `llm-queue` fue una aplicación FastAPI con un panel web, una API REST y un endpoint MCP, todo sobre una sola base de datos SQLite en modo WAL. Los solicitantes eligieron un alias de capacidad (`fast` en el vLLM de la B70, `background` y `reasoning` en Ollama en CPU), y cada alias tenía su propio trabajador, por lo que un trabajo lento en CPU nunca bloqueaba un trabajo en GPU.

La segunda fase colocó un gateway LiteLLM delante de los modelos. El gateway emitía a cada usuario una clave virtual, y esa clave era el login en todas partes: interfaz web, REST y MCP. La cola limitaba los trabajos a un hash de la clave, y ejecutaba cada trabajo a través del gateway como ese usuario, por lo que las cuotas estaban en un solo lugar. Eso significó que el trabajador necesitaba la clave del solicitante después de que la solicitud hubiera regresado, por lo que cada fila de trabajo llevaba la clave cifrada con Fernet, y el trabajador la descifraba, ejecutaba el trabajo y lo limpiaba una vez que el trabajo terminaba o se cancelaba. LiteLLM no guardaría sus claves en SQLite, por lo que el gateway también necesitaba un sidecar Postgres.

Funcionó, y fue mucha maquinaria.

## La flota a la que se trasladó

En septiembre, el homelab recibió una flota de NanoClaw en devastator. NanoClaw ejecuta agentes de Claude Code en contenedores, organizados como grupos de agentes: cada grupo tiene sus propias instrucciones, habilidades, montajes y entorno, y se despierta para mensajes de un canal o para tareas programadas y de una sola vez. Algunos grupos se comunican directamente con Anthropic. Otros se ejecutan en qwen3-14b, servido por vLLM en el local B70 y alcanzado a través de un pequeño proxy normalizador que hace que la API del modelo local se comporte lo suficiente como la de Anthropic para el soporte de Claude Code (se pliegan los mensajes del sistema, se limitan los tokens de salida y se desactiva el modo de pensamiento de qwen3).

Esa flota ya había realizado la ruta, el control de acceso y la auditoría que la cola había construido para sí misma. Y nada había utilizado la cola en 30 días.

## Versión dos: trabajos como tareas de agentes

El 2026-09-19 la cola y la puerta de enlace se descompusieron y se eliminaron del repositorio. El reemplazo, `llm-jobs`, es un servicio de la biblioteca estándar de Python que se ejecuta como una unidad de usuario systemd en devastator. Tiene propiedad de dos cosas, claves y trabajos, ambas en un solo archivo SQLite. Todo lo demás es NanoClaw.

Un trabajo funciona así:

1. Un llamante envía un prompt y un nivel.
2. El servicio crea una tarea de NanoClaw de una sola vez en el grupo de agentes del nivel.
3. El contenedor del grupo se despierta con un contrato de trabajador corto precedido: haz exactamente el trabajo, entrega una vez, no publiques en canales, no hagas preguntas.
4. El agente llama a la herramienta MCP del servicio `deliver_result` con el identificador del trabajo y su respuesta, o con una oración de error si el trabajo no puede realizarse.
5. El llamante consulta y recibe.

Las sesiones de Claude Code lo alcanzan como un servidor MCP con tres herramientas importantes: `submit_job`, `get_status` y `get_result` (más `list_tiers`, `list_jobs` y `cancel_job`). Una llamada típica se ve así:

```
submit_job(
  tier="local",
  prompt="Summarize the release notes below in five bullets for a homelab operator. <notes...>",
  params={"max_words": 150}
)
```

El prompt debe ser autónomo; el trabajador no ve nada más. Las `params` sugerencias se convierten en líneas en el contrato del trabajador. Las claves son claves de portador, con alcance por propietario: un llamante solo ve sus propios trabajos, y los resultados se mantienen 30 días. Se ejecuta un trabajo por nivel a la vez, y un trabajo sin entrega dentro de su tiempo de espera se considera fallido y su tarea cancelada.

## Tres niveles

- **local** se ejecuta en el grupo `jobs-local`: qwen3-14b a través del proxy, con Anthropic bloqueado del contenedor. Gratis y privado. Un trabajo trivial regresó en 16 segundos.
- **claude** se ejecuta en `jobs-claude`: Sonnet, con medición. Un trabajo trivial tomó 50 segundos. NanoClaw no tiene límite de uso por grupo, por lo tanto el servicio impone uno: límites diarios por clave, más un techo diario para trabajos y tokens de salida que comparten todas las claves. Sin importar cuántas claves estén activas, el nivel medido tiene un solo techo.
- **render**, añadido el 2026-09-26, se ejecuta en `jobs-render`. El prompt es una receta JSON (una URL del modelo, vistas, muestras, tamaño), el grupo tiene una habilidad `blender-render` y una instalación de Blender de solo lectura, y renderiza imágenes estáticas sin interfaz gráfica con Cycles. Un nivel puede solicitar artefactos, y este lo hace: cada trabajo obtiene su propia carpeta montada en el contenedor, `get_result` lista los archivos, y el servicio los entrega al propietario del trabajo. Con `"photo": true` en la receta, el trabajador también llama a `request_photo` para cada vista y consulta a `photo_status`. Eso encola un paso a través del arbitro de GPU en devastator, que presta el B70 de vLLM a un modelo de imagen de FLUX Kontext cuando la tarjeta esté ociosa, y escribe una foto junto a cada renderización.

Las herramientas del trabajador (`deliver_result`, `request_photo`, `photo_status`) son visibles solo para los trabajadores.

## Lo que no funcionó

- **qwen3 no puede realizar llamadas a herramientas a través del proxy.** Los trabajos de texto plano funcionan en el nivel local. Detrás del proxy, qwen3-14b falla en los pasos de llamada a herramientas con el mensaje "Content block is not a text block", y un trabajo de renderizado no es más que llamadas a herramientas. El nivel de renderizado se ejecuta en Sonnet, bajo su propio pequeño límite diario; un trabajo de renderizado solo necesita unas pocas de esas llamadas.
- **No hay GPU en los contenedores del agente.** NanoClaw no tiene passthrough de dispositivos, por lo que Blender renderiza en la CPU, aproximadamente 35 segundos por vista a 128 muestras. El paso de foto solo obtiene la GPU porque el árbitro se ejecuta en el host, fuera de NanoClaw, y el trabajador le pide las fotos a través de MCP.

## ¿Qué se lleva adelante?

La segunda versión es más pequeña porque dejó de ser dueña de cosas que ya eran propiedad de otro sistema. El servicio de trabajos mantiene las claves, los trabajos, los límites y los artefactos; NanoClaw mantiene los modelos, los contenedores, las habilidades y las credenciales. Un nuevo nivel es un nuevo grupo de agentes con sus propias instrucciones y habilidades, más una entrada en la tabla de niveles, lo que es cómo un renderizador de Blender llegó una semana más tarde sin ningún cambio en cómo los llamadores envían las solicitudes. Y el contrato de entrega es el mismo para cada nivel: el trabajador llama a una herramienta, exactamente una vez, y se detiene.
