---
title: "De un gabinete a una tubería CAD"
dek: "Cómo un solo plan de un armario para filamento de impresión 3D se convirtió en una forma de hacer planes de construcción: un módulo Python por construcción, dibujos y verificaciones a partir de los mismos números, precios de listas reales, y una habilidad que recuerda las lecciones aprendidas."
lang: es
source: from-one-cabinet-to-a-cad-pipeline
source_hash: b5b5727fe04eb573
model: qwen3-14b
---

El primer plan físico en este sitio fue un [estante para filamento de impresora 3D](/projects/spool-cabinet). Comenzó como un artefacto de claude.ai y se movió aquí el mismo día, porque un plan en un chat es difícil de encontrar, revisar o vincular.

## El estante para bobinas, cuatro revisiones en dos días

La revisión A (2026-09-12) era un estante con puertas de acrílico y una caja de calentamiento que funcionaba a 75 C. Esa misma noche obtuvo un script de Fusion 360, un archivo STEP y un GLB, por lo que el plan tenía un modelo editable y no solo dibujos.

- **B** redujo el secador a 65 C. El estante contiene PLA, PETG y TPU, y el PLA no debe almacenarse mucho por encima de 55 C.
- **C** fijó los estantes con tornillos de bolsillo y 1x3 de cenefas. Los estantes sujetos con clips en un claro de 46 in tenderían a deformarse.
- **D** (2026-09-13) reconstruyó la caja alrededor de las puertas de vidrio templado de IKEA OXBERG, eliminó la caja de calentamiento y añadió una lista de compras donde cada precio se verificó contra una lista. El secado se convirtió en un trabajo para un deshidratador comprado.

Una versión de dos bahías que contenía 112 bobinas duró aproximadamente una hora antes de que se redujera a una bahía de ancho BILLY: dos puertas OXBERG, 56 bobinas colocadas de forma vertical con un pitch de 4 in. Las elevaciones anteriores dibujaron las bobinas como círculos vistos desde el frente, lo cual era incorrecto para las bobinas colocadas a lo largo de las vías; el propietario lo detectó, y el pitch y los dibujos se corrigieron juntos.

Las primeras estimaciones de precios estaban equivocadas en ambas direcciones: demasiado alto para el contrachapado y los marcos, demasiado bajo para el acrílico y el poplar. Desde entonces, un precio era una lista leída ese día con el nombre del almacén, o se mantenía fuera del total.

## La tienda del garaje, toda una habitación

La [tienda de garaje](/projects/garage-shop) (2026-09-18) fue un problema más grande: una habitación con un camión estacionado, un armario de pared, herramientas móviles, un carrito de polvo y un subpanel. La revisión A se dibujó en un garaje asumido. La revisión B (2026-09-19) se dibujó en el medido, con un descanso a través de la pared trasera, una puerta de la casa que se ubicaba en algún lugar distinto al que sugerían las fotos, y sin sierra de mesa a mano.

Una habitación con tantas piezas móviles no podía ser verificada a simple vista en un dibujo plano.

## shopcad: un módulo, cada salida

Así que el 2026-09-18 el CAD se convirtió en un marco de trabajo. Cada construcción es un módulo de Python. Su `DEFAULTS` contiene cada número que una persona cambiaría, en pulgadas. Una `build` función coloca cajas y cilindros según esos números, y una `checks` función devuelve pasar o fallar con las figuras en el mensaje.

Desde ese único módulo se generan:

- un visor de three.js con estados (puertas abiertas, banco volteado);
- un archivo STEP para la escena y uno por construcción;
- renders en PNG para las hojas, capturados por Chrome sin cabeza con WebGL de software;
- un script de Fusion 360 cuyos parámetros de usuario son los mismos números;
- las verificaciones, que detienen la exportación cuando un número deje de funcionar.

El armario de bobinas se reconstruyó en el mismo día con diez verificaciones. El garaje alcanzó 24 verificaciones en la revisión B y 40 más tarde. La regla que surgió de ello: cuando el modelo no coincide con una hoja, el modelo suele tener razón, porque tuvo que cerrar la geometría. Un armario en una clavija francesa se encuentra a 1.5 in de la pared, independientemente de lo que diga la hoja.

## Escribirlo como habilidades

El flujo de trabajo se integró en un plugin de Claude Code llamado `workshop`, en un mercado personal de habilidades mantenido en el repositorio homelab. Tiene dos habilidades. `build-plan` posee el diálogo de diseño, las verificaciones de ingeniería, el conjunto de dibujos, los precios y la entrega. `shopcad-model` posee el módulo de planificación y sus salidas. La versión 1.1.0 incorporó lo que el garaje y la pantalla de roca habían enseñado, por lo que el próximo plan no lo vuelve a aprender.

## La pantalla de roca, un pequeño dispositivo

La [pantalla de roca](/projects/rock-screen) (2026-09-19) limpia rocas de río de debajo de una piscina en sacos de burlap de 50 lb. Es una bandeja de 24 x 48 pulgadas en un soporte de 2x4, pivotada 9 pulgadas detrás del extremo de descarga, de modo que se inclina 35 grados con alrededor de 23 lb en el mango cuando está cargada, y vierte a través de un embudo de contrachapado en un saco que está sobre una carretilla de mano.

Sus dibujos se generan mediante un script a partir de constantes geométricas en lugar de dibujarse a mano. El tamaño del saco determina el caño, y el saco de 50 lb obligó a reducir el caño de 11 x 11 pulgadas a 9 x 9. Al cambiar una constante, el embudo, la lista de cortes y la copia siguieron. La regla de llenado también se convirtió en una línea de hoja: la roca pesa aproximadamente 100 lb por pie cúbico, por lo que un saco equivale a tres paladas, 45 lb, y alrededor de 60 sacos hacen un yarda cúbica.

## Luego el jardín trasero

El siguiente plan fue una terraza y un patio dibujados a partir de fotos de drones, y empujó el marco hacia afuera y hacia el renderizado en estilo foto. Esa historia está en [un jardín trasero, dibujado a partir de fotos de drones](/writing/backyard-from-drone-photos); el plan está en [/projects/backyard](/projects/backyard).

## Lo que se lleva adelante

- **Cada límite se convierte en una línea de hoja o en una verificación del modelo.** Un radio de oscilación, un espacio de trabajo, un peso de saco o un ancho de estante se imprime en una hoja o se impone mediante el modelo, preferiblemente ambos.
- **Los precios provienen solo de listados que realmente se han leído.** Se registra el nombre de la tienda, se anota la fecha y un precio que no se puede leer se marca como "no leído" y se excluye del total.
- **Las páginas se renderizan y verifican en anchos de escritorio y estrechos.** Cada hoja se imprime sola con las fuentes reales a 1100 y 720 píxeles antes de publicar, porque la gente las lee en medio de una pantalla.
- **El PDF se imprime sin cabeza.** Un envoltorio de impresión y Chrome sin cabeza lo hacen, y se compara el número de páginas con el PDF anterior para asegurar que las reglas de diseño estrecho no dupliquen silenciosamente el número de páginas.
- **Los planes viven en el sitio, no en artefactos de chat.** El [armario de bobina](/projects/spool-cabinet) fue el primero en moverse, y cada plan desde entonces ha comenzado aquí.
