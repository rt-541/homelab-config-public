---
title: "Una GPU de Intel, tres tareas"
dek: "Una tarjeta gráfica Intel Arc Pro B70 en un VM de RHEL sirve un modelo de lenguaje local, transcodifica para Plex y, cuando ambos están inactivos, se utiliza para un modelo de imágenes, con un pequeño árbitro que decide quién posee la tarjeta."
lang: es
source: one-intel-gpu-three-jobs
source_hash: 90b822f2afb6ceb3
model: qwen3-14b
---

La tarjeta es una Intel Arc Pro B70: Battlemage, 32 GB, pasada a una VM de RHEL llamada devastator. Fue comprada para un trabajo: servir un modelo de lenguaje local a los agentes en la flota NanoClaw. Al final terminó con tres: el modelo de lenguaje, transcodificación de hardware de Plex (más una campaña en lote que re-encodifica remuxes de 4K sobre VAAPI para recuperar espacio en disco), y, desde hoy, convertir renders 3D en fotografías.

## Haciendo que la tarjeta aparezca

El controlador que conoce esta tarjeta es `xe`, y el ID del dispositivo tiene que estar en él. El kernel de RHEL 10.0 no lo tenía. La actualización en lugar de la actualización desde 9.6 había fijado la versión de lanzamiento de la suscripción a 10.0, por lo que `dnf update` nunca avanzó el kernel. Establecer la versión de lanzamiento a 10.2 y actualizar trajo un kernel firmado por Red Hat con el ID retrotraído, y después de un reinicio la tarjeta apareció:

```
Kernel driver in use: xe
```

junto con un nodo de renderizado y el firmware GuC y HuC cargado desde `linux-firmware`. El contenedor de Plex, que ya montó `/dev/dri`, vio el nuevo nodo de renderizado sin cambios.

## Servir un modelo con vLLM

vLLM se ejecuta desde la imagen llm-scaler de Intel (`intel/llm-scaler-vllm:0.14.0-b8.3.1`), que se comunica con la tarjeta a través de su propia pila oneAPI y Level Zero, independiente del controlador de medios que usa Plex. El modelo servido avanzó en pasos: Qwen2.5-7B, luego Qwen3-14B como AWQ, y luego una prueba de Qwen3-30B-A3B.

El 30B es un modelo de mezcla de expertos con aproximadamente 3.3B parámetros activos por token, por lo que se decodifica como un modelo pequeño. Las recetas de Intel solo muestran que se divide entre dos o más tarjetas, ya que se ejecuta en FP16 (aproximadamente 61 GB) o se cuantiza en tiempo real, lo cual carga primero el modelo completo en la memoria RAM del host. Un checkpoint ya cuantizado a INT4 es aproximadamente de 17 GB y cabe en un B70. Tiene que ser GPTQ: en esta imagen, solo los checkpoints GPTQ obtienen un método de cuantización para las capas de MoE.

Dos configuraciones importaron para los agentes. La primera fue el contexto. El propio harness del agente envía aproximadamente 16k tokens de prompt y esquemas de herramientas, por lo que la ventana se llevó a 32k, y luego a 64k con YaRN estático en el 7B (un factor de 2 sobre su base de 32k, el método que documenta Qwen). La segunda fue las llamadas a herramientas. Sin un analizador, el modelo devolvió sus invocaciones de herramientas como texto plano; con el analizador Hermes habilitado, regresan como llamadas reales:

```
- --enable-auto-tool-choice
- --tool-call-parser
- hermes
```

## Dejando espacio para Plex

vLLM reclama una porción fija de la tarjeta al iniciar. Esa porción pasó de 0.75 a 0.80 a 0.92 y finalmente se estabilizó en 0.85, lo que deja aproximadamente 4.8 GB para Plex: dos transcodificaciones de 4K HDR a unos 2 GB cada una más un margen para el controlador. Un tercer flujo recurre al CPU. El modelo apenas lo notó; aún había espacio en la caché KV para muchas solicitudes concurrentes.

## Prestar la tarjeta

La generación de imágenes requiere la mayor parte de la tarjeta, y vLLM no puede redimensionar su memoria mientras se ejecuta. Reserva al iniciar y no se reduce. Por lo tanto, el diseño intercambia dueños en lugar de dividir el pool.

**Un grabador.** Cada minuto, un temporizador raíz lee el DRM fdinfo de cada proceso, donde el `xe` controlador reporta VRAM por cliente y tiempo de uso de la CPU. Los clientes se nombran según su contenedor, o según el nombre del comando, por lo tanto, cada proceso de transcodificación de Plex cuenta como `plex`. Escribe una captura actual y un archivo de historia mensual. La historia también responde a una pregunta abierta: Plex tiene aceleración hardware en esta tarjeta y muchas reproducciones, pero no había registro de cuántas veces realmente transcodifica.

**Un árbitro.** Un pequeño servicio mantiene una cola de solicitudes de fotos y un modo: `llm`, `swapping` o `image`. Se cambia a `image` solo cuando la cola no esté vacía, vLLM no haya tenido ninguna solicitud en ejecución, esperando o finalizada durante 60 segundos, y el grabador muestre que no hay otro cliente en la tarjeta. Luego detiene vLLM, inicia ComfyUI con FLUX.1 Kontext, procesa la cola y devuelve la tarjeta tan pronto como la cola esté vacía o hayan pasado 15 minutos. Declara `llm` solo después de que vLLM responda a su prueba de salud.

**Un proxy de paciente.** Los agentes NanoClaw alcanzan a vLLM a través de un pequeño proxy. Éste lee el modo del árbitro y mantiene las solicitudes mientras el modo no es `llm`, y vuelve a intentar las conexiones rechazadas. Un agente que habla durante un intercambio espera en lugar de fallar.

Medido el primer día: el intercambio a `image` más la primera foto tomó 85 segundos, cada foto después de eso 52 a 62 segundos a 1328x800 y 24 pasos, y vLLM estuvo nuevamente saludable 56 segundos después de la devolución.

## Lo que no funcionó

- **Un núcleo principal.** El kernel-ml de ELRepo reconoce la tarjeta, pero está sin firmar, y la VM inicia con Secure Boot activado. El firmware lo rechazó antes de que se cargara el espacio de usuario. Incluso firmarlo con una clave de propietario de la máquina autoregistrada no permitió el arranque. Fue eliminado; esta VM solo ejecuta núcleos firmados por Red Hat.
- **Qwen3-32B.** Se reinició 252 veces con lo que parecía un problema de VRAM. El registro del núcleo decía lo contrario: un asesinato de grupo de memoria de cgroups a 8,3 GB de RSS, que era el límite de `memory: 8G` del archivo de configuración. El límite se aumentó a 16 GB para el siguiente intento.
- **Redimensionamiento en lugar.** No hay forma de pedirle a un vLLM en ejecución que devuelva memoria, lo cual es la razón principal de la existencia del árbitro.

## Lo que se lleva adelante

El plan es un segundo B70. Las dos tarjetas formarían una piscina de paralelismo de tensores (TP=2, 64 GB) en una segunda máquina, ya que la host actual es una placa Mini-ITX con un solo slot PCIe. Plex y la campaña de transcodificación se moverían a las tarjetas Arc A380. Hasta entonces, el patrón se mantiene para cualquier acelerador compartido: mide quién está en él antes de decidir algo, y cuando una carga de trabajo no pueda reducirse, intercambia toda la tarjeta en lugar de dividirla.
