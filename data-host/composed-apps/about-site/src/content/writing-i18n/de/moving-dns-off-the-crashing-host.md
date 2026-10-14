---
title: "DNS von dem abstürzenden Host entfernen"
dek: "DNS und DHCP verließen einen Docker-Host mit einem Panik-Verhalten für ein Paar Pi-hole-Container auf zwei Proxmox-Knoten, und dasselbe Muster übernimmt nun die Steuerungsebene, den Uptime-Monitor und die Metrics-Stack."
lang: de
source: moving-dns-off-the-crashing-host
source_hash: d9b8203886d15206
model: qwen3-14b
---

DNS und DHCP liefen früher als Pi-hole in Docker auf nemesis, dem Haupt-Docker-Host, mit einer zweiten Pi-hole auf devastator, die nur DNS-Anfragen beantwortete. Als der Host, der diesen Container hostete, nicht mehr erreichbar war, konnte nichts auf dem Netzwerk einen Namen auflösen, bis er wieder verfügbar war.

## Warum der Host das Problem war

nemesis ist eine virtuelle Maschine auf dem Proxmox-Knoten sienar und hat eine Crash-Geschichte. Im August und September zeigte sie eine Serie von Kernel-Panics mit unterschiedlichen Signaturen. Ein Crash-Dump zeigte, dass der Mapping-Pointer einer Seite genau einen Bit-Abstand vom tatsächlichen Wert hatte. Das Urteil lautete auf fehlerhaues Speicher auf einem Host ohne ECC, nicht auf einen Kernel-Bug. Jeder Panic kostet 8 bis 10 Minuten für einen Neustart.

Der Umzug selbst wurde bereits früher, im Juni, durch einen anderen Fehler erzwungen. Ein Cluster-Link-Flap teilte die beiden Proxmox-Knoten, einer verlor das Quorum und hing fest, und musste daher neu gestartet werden. Während dieser Zeit gab es keinen DNS-Service irgendwo.

## Das Paar

DNS und DHCP laufen nun in zwei kleinen Containern, jeweils auf einem Proxmox-Knoten: `dns-incomm` und `dns-sienar`. Jeder ist ein privilegierter Debian 12 LXC, der Pi-hole v6 nativ ausführt, nicht in Docker. keepalived hält eine virtuelle Adresse zwischen ihnen. Der incomm-Member ist der Master; wenn sein Pi-hole aufhört, auf Anfragen zu antworten, wechselt die Adresse zu sienar.

DHCP folgt der gleichen Adresse. Das notify-Skript von keepalived schaltet DHCP für den Member ein, der die Adresse hält, und für den anderen aus, und es handelt sich nur bei einem echten Zustandswechsel, sodass die beiden nie gleichzeitig Leases vergeben. Der eigene DHCP-Server des Routers ist ausgeschaltet. Die Clients erhalten die gemeinsame Adresse als ihre DNS-Server, sodass ein Failover auf ihrer Seite nichts verändert.

Einträge und Reservierungen werden nur auf dem Primärsystem bearbeitet. nebula-sync kopiert sie auf das Sekundärsystem.

Die alten Docker-Pi-holes blieben noch eine Zeit lang online, um als Rollback zu dienen, und wurden anschließend abgeschaltet.

## Eine Eintragung für jeden Dienst

Der interne DNS trägt nun einen einzigen Wildcard: Jeder Name unter dem homelab-Domain wird auf den Reverse Proxy-Host gelöst. Ein neuer Webdienst benötigt nur eine Routing-Regel auf dem Proxy und nichts weiter: keine pro-Dienst-Eintragung, die vergessen oder zurückgelassen werden könnte. Außerhalb des Netzwerks lösen die gleichen Namen sich über den öffentlichen DNS-Anbieter.

Pi-hole v6 registriert auch die Hostnamen der Maschinen, die einen Lease erhalten, sodass jedem Host ein Name zugewiesen wird, ohne dass jemand dies manuell notieren müsste.

## Das Mechanismus, der immer noch lebendig aussah

Das Docker-Host-Repository enthält immer noch ein Ansible-Playbook, das DNS-Einträge in `custom.list` schreibt, die Art und Weise, wie Pi-hole v5 lokale Einträge hinzufügt. Pi-hole v6 speichert sie in `pihole.toml` unter `dns.hosts`, und das alte Container-Image, das es zielte, existiert nicht mehr. Das Playbook ist ein no-op. Es schlägt nicht fehl; es veröffentlicht einfach nichts.

Ein Eintrag wurde dort einmal hinzugefügt, schien fertig zu sein und musste später rückgängig gemacht werden, als sich herausstellte, dass er keinen Resolver erreichte. Wenn ein Dienst migriert wird, muss die alte Methode, ihn zu ändern, gelöscht oder deutlich markiert werden, denn ein Mechanismus, der sauber läuft und nichts tut, sieht genauso aus wie einer, der funktioniert.

## Namen, nicht Adressen

Der Desktop, der die Notizschätze enthält, hat eine DHCP-Reservierung, sodass seine Adresse nie ändern sollte. Zweimal änderte sie sich jedoch. Im Juni gab es bei einer SSH-Verbindung zur reservierten Adresse die Meldung „No route to host“, während die gleiche Verbindung über den Namen problemlos funktionierte; der Name folgte der tatsächlichen Lease des Rechners, und die festgelegte Adresse war veraltet. Im September geschah es erneut, und die Schatz-Synchronisationen, die die Adresse direkt verwendeten, schlugen stumm fehl. Die Ursache ist bis heute ungeklärt.

Die Regel: erreiche Hosts über ihren Namen. Eine hartcodierte Adresse ist nur so gut wie die hinter ihr stehende Reservierung, und nichts warnt, wenn diese veraltet.

## Die Steuerungsebene

Die DNS-Paarung wurde zur Vorlage. Es gibt nun vier Paare von LXCs, die jeweils an physische Knoten gebunden sind, anstatt in einem VM zu leben, das abstürzen kann:

- **Steuerung:** tarkin auf incomm (primär) und pellaeon auf sienar (Backup), die OpenTofu, Ansible und eine Kopie des Infrastruktur-Repositories beherbergen. pellaeon zieht das Repository alle zehn Minuten.
- **DNS:** das oben genannte Pi-hole-Paar.
- **Uptime-Überwachung:** Uptime Kuma auf beiden Knoten. Nur der Mitglied, das die gemeinsame Adresse hält, sendet Warnmeldungen, und seine Container-Überwachungen werden alle zwei Minuten mit dem tatsächlich laufenden System abgeglichen.
- **Beobachtbarkeit:** Prometheus mit einer Speicherzeit von 30 Tagen, Grafana und ein Alertmanager-Cluster mit zwei Mitgliedern, der sich so abstimmt, dass jede Warnung einmal in Discord ankommt. Exporter überwachen Hosts, Festplatten-SMART-Daten und die Proxmox-API.

Die Überwachung und Beobachtbarkeit-Master-Systeme befinden sich auf sienar, dem Knoten mit der redundanten Stromversorgung; ein Watcher sollte nicht das gleiche Schicksal teilen wie das Objekt, das er überwacht. Änderungen der Flotte werden von tarkin aus dem Infrastruktur-Repository durchgeführt, nicht als ad-hoc SSH von irgendeinem Ort, wo die Sitzung gerade stattfindet, damit jede Änderung schriftlich festgehalten bleibt.

## Was nicht funktioniert hat

- **Der erste Temperaturalarm.** Er löste sich aus, sobald der Sensor seine eigene "hohen" Schwellenwert überschritt. Die Bezeichnung variiert je nach Chip: bei dem i7-12700K in incomm wird 80 C als "hoch" gemeldet, was seine normale Betriebstemperatur ist, wodurch es ständig Alarm auslöste. Die Regel verwendet jetzt absolute Schwellenwerte auf dem heißesten Kern, mit einer Warnung bei 95 C und einem kritischen Schwellenwert bei 98 C.
- **Dann war der Alarm richtig.** incomm stürzte im Juli aufgrund eines thermischen Fehlers ab und lief später bei einer CPU-Auslastung von etwa 11 Prozent bei Temperaturen zwischen 92 und 100 C. Das ist Kühlung, nicht Last, und es benötigt immer noch eine Hardware-Behebung.
- **Verpackte Dienste in LXC.** Pi-hole FTL, Prometheus und Grafana liefern verstärkte systemd-Einheiten, die vor dem Start in einem Container mit einem drop-in-Datei bearbeitet werden müssen.
- **Die Pi-hole-Konfiguration ist immer noch imperativ.** Die Wildcard und die keepalived-Konfiguration wurden manuell auf beiden Mitgliedern angewendet und sind noch nicht in Ansible enthalten.

## Was weitergeführt wird

Jeder neue Kernservice erhält die gleiche Struktur: zwei LXCs auf zwei Knoten, eine gemeinsame Adresse, ein Schreiber, der mit dem anderen synchronisiert, und Warnungen von dem Mitglied, das die Adresse hält. Namen statt Adressen, eine Wildcard statt vielen Einträgen, und ein ersetzteter Mechanismus wird entfernt, damit er nicht vorgibt zu funktionieren.
