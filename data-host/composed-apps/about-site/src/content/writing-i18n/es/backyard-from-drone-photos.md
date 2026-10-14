---
title: "Un jardín trasero, dibujado a partir de fotos tomadas con drones, renderizado por el homelab"
dek: "Cinco revisiones de una terraza, un patio de piedra y un anillo de fuego en un día, con cada dibujo, verificación y cantidad proveniente de un solo módulo Python, y vistas en estilo de foto desde un trabajador de Blender en la flota NanoClaw más FLUX Kontext en una GPU compartida."
lang: es
source: backyard-from-drone-photos
source_hash: 59600bce7c2bd0bb
model: qwen3-14b
---

El encargo llegó como una frase y una carpeta con ocho fotos tomadas por dron: una terraza compuesta con una escalera en una esquina y otra que lleva a un patio de piedra, una fila de coníferas a lo largo de la valla trasera, un drenaje francés donde el jardín se inunda, y un lugar para cultivar vegetales. No había mediciones con cinta. El resultado final tenía la misma forma que los otros planos en este sitio: un conjunto de dibujos que alguien podría entregar a los contratistas, un PDF, un modelo 3D, y una lista de precios donde cada línea es un ítem que realmente fue leído.

## Leyendo el sitio desde el aire

Las fotos del dron llevan más que imágenes. La dirección del vuelo en los metadatos de cada imagen determinó hacia dónde se orienta la casa (el giro del giroscopio de la cámara en este dron no es confiable; el giro del vuelo sí lo es), y una anchura conocida en la imagen proporcionó una escala: la casa salió a unos 52 pies de ancho, el jardín unos 50 pies de profundidad. Todo en la revisión A está marcado como una estimación, y la primera hoja enumera las seis mediciones que lo convierten en revisión B.

Las fotos también llevan coordenadas GPS. Estas nunca dejan la copia de trabajo; nada publicado aquí dice dónde está la casa.

## Un módulo, muchas salidas

El plan vive en un solo archivo de Python. Sus `DEFAULTS` contienen cada número que una persona podría cambiar: lote, casa, bay, chimenea, terraza, escalera, patio, anillo de fuego, árboles, drenaje. Todo lo demás se deriva de ellos, incluyendo el nivel del terreno, que es un plano que se inclina hacia la valla trasera y hacia el drenaje de la esquina.

Desde ese solo módulo surgen:

- el modelo 3D, exportado a GLB, STEP y un script de Fusion 360;
- las quince dibujos SVG en las hojas (plan del sitio, sección, estructura, elevaciones, escaleras, patio, anillo, pared de asientos, lecho de hierbas, pantalla del aire acondicionado, árboles, drenaje);
- las cantidades que las cotizaciones deben coincidir (tablas, guardia, pilares, toneladas de pizarra, yardas cúbicas de base, piedra para muros);
- sobre cuarenta verificaciones que fallan en la exportación cuando un número deja de funcionar: escalones de escalera superiores a 7,75 pulgadas, un voladizo de viga superior a un cuarto de su longitud, un anillo de fuego demasiado cerca del arborvitae, sillas que ya no caben en la piedra.

Eso importa más cuando el diseño cambia, y cambió mucho.

## Cinco revisiones en un día

La revisión A colocó una terraza de jardín al norte de un amplio deck, un círculo de fuego al oeste y nueve árboles Green Giants desplazados a lo largo de la valla. Luego el propietario lo vio.

- **A2.** El deck se redujo al umbral de la puerta corrediza, el patio se convirtió en un cuadrado de 16 pies de pizarra marrón seca, los árboles se convirtieron en cinco arborvitae American Pillar en una fila, y el jardín desapareció.
- **A3.** El anillo de fuego se movió a la esquina noroeste del patio, el lecho de hierbas se convirtió en un lecho elevado de piedra que se separa del ladrillo, y el aire acondicionado obtuvo una pantalla. La "puerta" para la cual había dibujado una plataforma resultó ser una ventana del salón.
- **A4.** Una escalera en lugar de dos, el corredor dibujado como el bayo inclinado que realmente es, las esquinas externas del deck cortadas a 45 grados, y una plancha de Blackstone y un ahumador a lo largo de la valla este.
- **A5.** Una pared de asientos de piedra alrededor del fuego, el conjunto de sofá se trasladó al patio, una falda ventilada debajo del deck, y la pantalla del aire acondicionado se abrió en su lado oeste. El propietario preguntó si una pantalla sólida de tres lados afectaría al condensador. Sí lo haría: la unidad toma aire por sus lados y lo expulsa por la parte superior, y una caja alrededor de ella le proporciona su propia salida de aire.

Cada revisión regeneró el modelo, las hojas, las cantidades, el presupuesto y un PDF, y republicó la página. Un cambio como "cortar las esquinas" afectó el contorno de la terraza, los viguetas, los guardas, el fregadero, el vestíbulo y el sendero de piedra alrededor de la terraza, y nada de eso fue redibujado a mano.

Algunas de las cosas que los controles detectaron en el camino: un pozo de fuego que encajaba en el jardín solo como una unidad portátil lista (la distancia de código publicada para un fuego de leña abierto es de 25 pies; el propietario estableció sus propias distancias, y el plan registra ambas), una terraza que no podía colgar sobre el ladrillo (un ledger no puede ir sobre una capa, por lo que se apoya en sus propios dos viguetas), y un patio que se encontraba más alto que el césped en su lado bajo, lo cual ahora es sostenido por la pared de asientos.

## Haciendo que el modelo se parezca a un jardín

Las primeras renderizaciones eran honestas y feas: baldosas de césped escalonadas, árboles apilados como pasteles, muebles como cajas. El marco CAD solo conocía cajas y cilindros, así que aprendió cuatro formas más: polígonos extruidos (piedras irregulares, paredes de asientos curvas, escaleras), una placa con una parte superior inclinada (una tierra lisa), conos (árboles, sombrillas) y un techo de dos aguas. Las piedras provienen de una cuadrícula con vibración recortada al cuadrado del patio y al vestíbulo redondo, por lo que ninguna de las piedras se superpone.

Luego, la fotorealidad. El primer intento fue una instalación única de Blender en la máquina que ejecutaba la sesión, lo cual es el lugar equivocado para ello. El mejor lugar es la flota de NanoClaw, que ya ejecuta trabajadores de tareas detrás de un pequeño servicio de tareas. Así que ahora hay una capa de renderizado:

- un llamante envía una receta en formato JSON (la URL del modelo y las vistas) al servicio de trabajo;
- un grupo de agentes NanoClaw, `jobs-render`, se despierta con una habilidad `blender-render`, ejecuta Blender en modo sin interfaz gráfica y escribe las imágenes en una carpeta de artefactos por trabajo;
- el servicio de trabajo lista esos archivos en el resultado y los entrega a quien realizó la solicitud del trabajo.

El módulo de planificación lleva su propia receta de renderizado: qué partes son ladrillo, teja, compuesto, pizarra, piedra de pared, hierba o vegetación, tres vistas de cámara, el sol (bajo desde el noroeste-oeste, para que las caras norte estén iluminadas) y un plano de suelo infinito que sigue el relieve. Los materiales son procedurales, teñidos con el color de cada parte, por lo que no hay archivos de textura que viajen con el modelo.

![El patio trasero desde el norte, renderizado en Blender por el nivel de renderizado](/plans/backyard/model/cycles-north.png)

Correcto, iluminado y aún obviamente un modelo. Materiales mejores solo habrían hecho que el modelo fuera aún mejor, por lo que el último paso le pasa el render a una herramienta que hace fotografías: FLUX.1 Kontext, un modelo de edición de imágenes que toma una imagen más una instrucción ("convierte este render 3D en una fotografía real; mantén cada objeto donde está") y redibuja las superficies manteniendo el diseño y la cámara.

Se ejecuta en el Intel B70 del host de renderizado, que normalmente aloja el modelo de lenguaje de la flota (vLLM) y respalda Plex. Los dos no pueden compartir la memoria de la tarjeta, así que un pequeño árbitro se la cede. Las solicitudes de fotos se filan con él; cuando vLLM ha estado inactivo durante un minuto y nada más está en la tarjeta, detiene a vLLM, inicia ComfyUI con Kontext, ejecuta toda la cola y le devuelve la tarjeta. Las solicitudes al modelo de lenguaje durante un intercambio esperan en su proxy en lugar de fallar. Una foto toma alrededor de 55 segundos, el intercambio de vuelta alrededor de un minuto, y el trabajador de renderizado simplemente pide una foto de cada vista y espera.

![La misma vista como fotografía](/plans/backyard/model/photo-north.png)

![Desde el sureste](/plans/backyard/model/photo-ne.png)

![Desde el oeste](/plans/backyard/model/photo-west.png)

La cubierta, las esquinas cortadas, el anillo de fuego y la pared de asientos, el aire acondicionado protegido y las cinco columnas están donde el plan las coloca. Los bosques y campos más allá de la valla son la invención del modelo.

## Lo que no funcionó

- **El modelo local no puede manejarlo.** El qwen3-14b de la versión gratuita, detrás de su proxy, falló en el primer giro de llamada a herramientas ("Content block is not a text block"). Los trabajos de texto plano funcionan; un trabajo que debe escribir un archivo y ejecutar un comando aún no lo hace. El trabajador de renderizado se ejecuta en Sonnet, limitado a 30 trabajos al día, ya que cada trabajo solo tiene tres llamadas a herramientas.
- **Blender no puede acceder a la GPU.** NanoClaw no tiene paso directo de dispositivos, por lo que el paso de Blender se ejecuta en el CPU (alrededor de 35 segundos por vista a 128 muestras). El paso de foto obtiene la GPU solo porque el árbitro se ejecuta fuera de NanoClaw, en el host.
- **La descarga oficial de Blender está detrás de una verificación de bot.** Un espejo universitario sirve el mismo archivo.

## Lo que se lleva adelante

El siguiente plan físico obtiene vistas de estilo fotográfico al costo de un bloque `RENDER` en su módulo y un trabajo con `"photo": true`. La capa de renderizado no conoce nada sobre patios traseros; toma cualquier GLB y una receta. Y la lección de las revisiones es la misma que en el garaje y en el armario de bobinas: cuando los dibujos, el modelo, las verificaciones y la lista de compras provienen todos de los mismos números, el propietario puede cambiar de idea cinco veces al día y el plan sigue adelante.

El conjunto de dibujos está en [/plans/backyard/](/plans/backyard/), y la página del proyecto en [/projects/backyard](/projects/backyard).
