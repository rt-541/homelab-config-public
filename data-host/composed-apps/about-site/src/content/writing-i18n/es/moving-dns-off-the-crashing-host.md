---
title: "Moviendo DNS del host que se caía"
dek: "DNS y DHCP dejaron a un host de Docker con el hábito de caídas para un par de contenedores Pi-hole en dos nodos Proxmox, y el mismo patrón ahora afecta al plano de control, al monitor de tiempo de actividad y al stack de métricas."
lang: es
source: moving-dns-off-the-crashing-host
source_hash: d9b8203886d15206
model: qwen3-14b
---

DNS y DHCP se usaban anteriormente como un Pi-hole en Docker en nemesis, la máquina principal de Docker, con un segundo Pi-hole en devastator que solo respondía DNS. Cuando el host que alojaba ese contenedor se fue, nada en la red podía resolver un nombre hasta que volvió.

## ¿Por qué el host era el problema

nemesis es una máquina virtual en el nodo Proxmox sienar, y tiene un historial de fallos. A través de agosto y septiembre, registró una serie de fallos del kernel con diferentes firmas. Un volcado de memoria mostró que un puntero de mapeo de página estaba exactamente un bit alejado del valor real. El veredicto fue memoria defectuosa en un host sin ECC, no un error del kernel. Cada fallo cuesta entre ocho y diez minutos de reinicio.

El movimiento mismo fue forzado anteriormente, en junio, por un fallo diferente. Un salto en el enlace del clúster dividió los dos nodos Proxmox, uno perdió el quórum y se atascó, y tuvo que ser reiniciado. Mientras estaba caído, no había DNS en ninguna parte.

## El par

DNS y DHCP ahora se ejecutan en dos pequeños contenedores, uno en cada nodo Proxmox: `dns-incomm` y `dns-sienar`. Cada uno es un LXC Debian 12 con privilegios ejecutando Pi-hole v6 nativamente, no en Docker. keepalived mantiene una dirección virtual entre ellos. El miembro incomm es el maestro; si su Pi-hole deja de responder, la dirección se mueve a sienar.

DHCP sigue la misma dirección. El script de notificación de keepalived activa DHCP en el miembro que posee la dirección y lo desactiva en el otro, y solo actúa ante un cambio real de estado, por lo que los dos nunca asignan concesiones al mismo tiempo. El propio DHCP del router está apagado. Los clientes obtienen la dirección compartida como su servidor DNS, por lo que un fallo de conmutación no cambia nada en su lado.

Los registros y las reservas se editan solo en el primario. nebula-sync los copia al secundario.

Los antiguos Pi-holes en Docker permanecieron activos durante un período de prueba como punto de rollback, luego fueron descomisionados.

## Un registro para cada servicio

El DNS interno ahora lleva un solo comodín: cada nombre bajo el dominio del homelab se resuelve al host del proxy inverso. Un nuevo servicio web necesita una regla de enrutamiento en el proxy y nada más: no es necesario agregar, olvidar o dejar atrás un registro por servicio. Fuera de la red, los mismos nombres se resuelven a través del proveedor de DNS público.

Pi-hole v6 también registra los nombres de host de las máquinas que toman un contrato de alquiler, por lo que cada host obtiene un nombre sin que nadie lo escriba a mano.

## El mecanismo que aún parecía estar activo

El repositorio del anfitrión de Docker aún contiene un playbook de Ansible que escribe entradas DNS en `custom.list`, la manera de Pi-hole v5 para agregar registros locales. Pi-hole v6 los mantiene en `pihole.toml` bajo `dns.hosts`, y el antiguo contenedor al que se dirigía ya no existe. El playbook es una operación sin efecto. No falla; simplemente publica nada.

Una vez se añadió un registro allí, parecía terminado, pero tuvo que revertirse cuando resultó que no alcanzaba a ningún resolutor. Cuando un servicio se mueve, el viejo método de cambiarlo debe eliminarse o marcarse claramente, porque un mecanismo que corre limpio y hace nada se ve exactamente como uno que funciona.

## Nombres, no direcciones

La computadora de escritorio que alberga los almacenes de notas tiene una reserva de DHCP, por lo que su dirección nunca debería cambiar. Dos veces lo hizo. En junio, una conexión SSH a la dirección reservada devolvió "No hay ruta al host", mientras que la misma conexión por nombre pasó directamente; el nombre siguió al contrato real de la máquina y la dirección fija era antigua. En septiembre ocurrió nuevamente, y las sincronizaciones de los almacenes que usaban directamente la dirección fallaron silenciosamente. La causa aún está abierta.

La regla: alcanzar hosts por nombre. Una dirección codificada es tan buena como la reserva detrás de ella, y nada advierte cuando esta se vuelve obsoleta.

## La plataforma de control

El par DNS se convirtió en la plantilla. Ahora hay cuatro pares de LXCs, cada uno asignado a nodos físicos en lugar de vivir dentro de un VM que pueda fallar:

- **Control:** tarkin en incomm (primario) y pellaeon en sienar (failover), llevando OpenTofu, Ansible y un clon del repositorio de infraestructura. pellaeon extrae el repositorio cada diez minutos.
- **DNS:** el par de Pi-hole mencionado anteriormente.
- **Monitor de tiempo de actividad:** Uptime Kuma en ambos nodos. Solo el miembro que posee la dirección compartida envía alertas, y sus contenedores de monitoreo se reconcilian cada dos minutos con lo que realmente está en ejecución.
- **Observabilidad:** Prometheus con 30 días de retención, Grafana y un clúster de dos miembros de Alertmanager que se comunican entre sí para que cada alerta llegue una vez a Discord. Los exportadores cubren hosts, datos SMART de disco y la API de Proxmox.

Los maestros del monitor y la observabilidad residen en sienar, el nodo con suministro de energía redundante; un watcher no debe compartir su destino con lo que está vigilando. Los cambios de la flota se ejecutan desde tarkin a partir del repositorio de infraestructura, no como SSH ad-hoc desde dondequiera que se realice la sesión, por lo que cada cambio permanece documentado.

## ¿Qué no funcionó

- **La primera alerta de temperatura.** Se activó en el umbral propio del sensor "high". La etiqueta varía según el chip: el i7-12700K en incomm reporta 80 C como "high", que es su temperatura normal de funcionamiento, por lo que paginaba constantemente. La regla ahora usa umbrales absolutos en el núcleo más caliente, advirtiendo a 95 C y crítico a 98 C.
- **Luego la alerta fue correcta.** incomm sufrió un fallo grave por un problema térmico en julio, y más tarde funcionó a 92 a 100 C con una carga del CPU del 11 por ciento. Eso es enfriamiento, no carga, y aún necesita una corrección de hardware.
- **Servicios empaquetados en LXC.** Pi-hole FTL, Prometheus y Grafana envían unidades de systemd endurecidas que necesitan un drop-in antes de iniciar en un contenedor.
- **La configuración de Pi-hole sigue siendo imperativa.** El wildcard y la configuración de keepalived se aplicaron manualmente en ambos miembros y aún no están en Ansible.

## ¿Qué se lleva adelante

Cada nuevo servicio de núcleo recibe la misma forma: dos LXCs en dos nodos, una dirección compartida, un escritor sincronizando con el otro, y alertas desde el miembro que posee la dirección. Nombres sobre direcciones, un wildcard sobre muchas entradas, y un mecanismo reemplazado se elimina para que no pueda fingir funcionar.
