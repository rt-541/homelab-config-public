---
title: "El pánico del kernel fue un bit invertido"
dek: "Un host de Docker que seguía paniquando en kswapd parecía tener un error en el núcleo; un volcado de error mostró un solo bit invertido en una estructura de página, y al día siguiente el mismo hardware inestable dejó caer el demonio de Docker y todos los contenedores en la máquina durante diez horas."
lang: es
source: kernel-panic-was-a-bit-flip
source_hash: 8e84a1680f9e6fd1
model: qwen3-14b
---

La máquina virtual principal del homelab es nemesis, una máquina virtual de RHEL 9 en un host Proxmox llamado sienar. Cuando se pana, cada sitio detrás de ella está caído hasta que kdump termina y la VM se reinicia, aproximadamente diez minutos cada vez. Durante el verano se panió mucho.

## Un patrón que apuntaba al kernel

En las primeras dos semanas de agosto hubo nueve pánicos en una construcción del kernel, siete de ellos el mismo error de desreferencia de puntero nulo dentro de `kswapd0`, el hilo de recuperación de páginas del kernel. Eso parece un error del kernel, y la solución obvia era una actualización del kernel. La actualización se implementó el 24 de agosto y el host parecía limpio durante seis días.

Luego tres más eventos, todos en el nuevo kernel:

- **30 de agosto:** un pánico, "stack-protector: El stack del kernel está corrupto en futex_parse_waitv", en un hilo perteneciente a un navegador sin cabeza.
- **12 de septiembre:** una advertencia `refcount_t: underflow; use-after-free` mientras se liberaban credenciales.
- **13 de septiembre:** otro Oops `kswapd0`, esta vez un error de página mal en el camino lento de spinlock, alcanzado desde el código de recuperación de LRU multi-generacional (MGLRU).

La presión de memoria no fue el disparador: la VM estaba al 22% usada con swap inactivo. kswapd corre constantemente solo porque el caché de páginas siempre llena la VM, por lo tanto, toca más páginas que cualquier otra cosa y es el código más probable para tropezar con una dañada.

Tres firmas de corrupción en sub sistemas no relacionados dentro de dos semanas no es lo que parece un solo error del kernel.

## Lo que dijo el vmcore

Con `crash` y el correspondiente `kernel-debuginfo`, el volcado del 13 de septiembre podría ser analizado a mano. La recuperación había tomado un bloqueo a través de `folio->mapping->host`, y esa dirección del bloqueo estaba dentro del dentry slab. Rastreando hacia atrás desde el folio:

```
folio->mapping (observed)   ffff89417d547db0
real i_data of that inode   ffff89417d547df0
difference                  0x40, one bit
```

El puntero observado se encuentra dentro de un inode XFS en ejecución (una película de 19 GB en el array de medios), y no puede ser el `i_data` de ningún inode en ese diseño de slab, por lo tanto, está corrupto, no caducado. Un bit en un `struct page` había cambiado.

El volcado del 30 de agosto coincidió: el protector de pila había disparado, pero las canarias de pila, tarea y por-CPU eran todas idénticas en el momento del volcado. La comparación había leído un valor incorrecto una vez.

La hardware subyacente explica por qué. sienar es una placa X299 con un i7-7820X y memoria no ECC (el registro del kernel dice `EDAC skx: ECC is disabled on imc 0`), y estaba ejecutando KSM, que fusiona páginas idénticas entre invitados. La hipótesis principal se convirtió en la flaqueza de la memoria o del CPU del host, no en un error del núcleo de RHEL.

## El día siguiente

El 14 de septiembre la misma flaqueza apareció en el espacio de usuario. dockerd murió con un error fatal del runtime de Go, `found pointer to free object`, que es cuando el recolector de basura detecta la corrupción del montículo. El demonio reiniciado mató a todos los contenedores huérfanos: 49 de ellos en 21 proyectos de compose, incluyendo el proxy de borde, este sitio, la pila de medios y el bot de Discord.

`restart: unless-stopped` devolvió exactamente uno de ellos.

## ¿Cuál fue el costo?

- **Aproximadamente diez horas de un host oscuro,** desde la mañana hasta la tarde.
- **Un monitor de disponibilidad que no lo detectó.** El monitor construye sus comprobaciones de contenedor dinámicamente y descarta las que corresponden a contenedores que no están en ejecución, por lo tanto, un cese masivo parece como menos monitores, no como rojos. Solo cinco comprobaciones estáticas se volvieron rojas.
- **Un contenedor que había estado caído durante cuatro semanas.** Después del pánico del 13 de septiembre, se encontró que un servicio aún estaba `Exited (255)` desde un crash en agosto. Ni la política de reinicio ni autoheal (que solo reinicia contenedores en ejecución que se consideran no saludables) lo detectaron.

La recuperación era manual: cada proyecto se recuperaba desde `docker compose up -d` en el directorio nombrado en las etiquetas de los contenedores de sus componetes.

## ¿Qué cambió

- **Revivir a los contenedores en el arranque.** `scripts/revive-stragglers.sh` encuentra contenedores que terminaron con código 255, tienen una política de reinicio de `always` o `unless-stopped` y están gestionados por compose, luego ejecuta `docker compose up -d` para esos servicios desde sus propios directorios. Los stacks detenidos deliberadamente terminan con otros códigos y se dejan solos. Una unidad systemd la ejecuta dos minutos después de que Docker inicie.
- **live-restore configurado.** La configuración `live-restore` de Docker mantiene los contenedores en ejecución durante una reinicialización del demonio, por lo que el próximo crash de dockerd no debería llevarse los contenedores consigo. Está en la configuración del demonio y se aplica al siguiente recarga del demonio.
- **KSM desactivado en sienar,** por lo que una página volteada no puede compartirse con otro invitado.
- **Conmutación de MGLRU en el repositorio.** Un entrada en tmpfiles.d desactiva la recuperación de MGLRU:

```
  w /sys/kernel/mm/lru_gen/enabled - - - - n
  ```

Aún no se ha aplicado, y el RCA la marca como opcional: elimina el camino de código que se activó dos veces, pero la próxima volteada solo terminaría en otro lugar.
- **Pruning de vmcore.** Desde finales de julio, una regla en tmpfiles.d elimina los volcados de kdump con más de 14 días, por lo que una serie de fallos no puede llenar el volumen de 20 GB `/var` (cada volcado es de aproximadamente 1 GB).
- **Un RCA en el repositorio,** con las tablas de volcados.

## ¿Qué sigue abierto

- Mover la VM nemesis a un nodo diferente de Proxmox durante unas semanas como prueba A/B. Si los fallos se detienen allí, sienar es la causa.
- Ejecutar memtest86+ en sienar durante una ventana de mantenimiento.
- Añadir un monitor en la cantidad de contenedores en ejecución, para que un paro masivo sea visible incluso cuando las verificaciones por contenedor desaparezcan.

## ¿Qué se lleva hacia adelante

Un error que siempre ocurre en la misma función del núcleo no es prueba de un error en el núcleo; puede ser prueba de que la función accede a la mayor cantidad de memoria. Diferentes firmas en código no relacionado en la misma máquina indican algo por debajo del software, y un volcado de error más los símbolos de depuración pueden convertir esa suposición en una diferencia de un bit. En el lado de Docker: una política de reinicio no es un plan de recuperación después de un error no limpio, y un monitor que solo observa lo que está en ejecución no puede reportar lo que dejó de funcionar.
