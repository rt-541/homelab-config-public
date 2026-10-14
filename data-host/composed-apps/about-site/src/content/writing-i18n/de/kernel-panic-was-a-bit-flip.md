---
title: "Der Kernel-Panic war ein Bit-Flip"
dek: "Ein Docker-Host, der immer wieder in kswapd abstürzte, schien ein Kernel-Problem zu haben; ein Absturz-Protokoll zeigte einen umgedrehten Bit in einer Seitenstruktur, und am nächsten Tag brachte dieselbe unzuverlässige Hardware den Docker-Daemon und alle Container auf dem Host für zehn Stunden zum Absturz."
lang: de
source: kernel-panic-was-a-bit-flip
source_hash: 8e84a1680f9e6fd1
model: qwen3-14b
---

Der Haupt-Docker-Host des Homelabs ist nemesis, ein virtueller Maschine mit RHEL 9 auf einem Proxmox-Host namens sienar. Wenn er abstürzt, ist jeder Dienst dahinter bis kdump fertig ist und die VM neu gestartet wird, also ungefähr zehn Minuten pro Mal, nicht erreichbar. Im Sommer stürzte er häufig ab.

## Ein Muster, das auf den Kernel hindeutete

In den ersten beiden Wochen im August gab es neun Abstürze bei einem Kernel-Release, sieben davon waren der gleiche NULL-Pointer-Dereferenzierung innerhalb `kswapd0`, dem Page-Reclaim-Thread des Kernels. Das sieht nach einem Kernel-Bug aus, und die offensichtliche Lösung war ein Kernel-Update. Das Update wurde am 24. August bereitgestellt und der Host sah sechs Tage lang sauber aus.

Dann drei weitere Ereignisse, alle auf dem neuen Kernel:

- **30. August:** ein Absturz, "stack-protector: Kernel stack is corrupted in futex_parse_waitv", auf einem Thread, der einem headless Browser gehört.
- **12. September:** eine `refcount_t: underflow; use-after-free` Warnung während des Freigebens von Anmeldeinformationen.
- **13. September:** ein weiterer `kswapd0` Oops, diesmal ein schlechter Seitenfehler in einem Spinlock-slow-Pfad, erreicht von der MGLRU (multi-generational LRU) Reclaim-Code.

Der Auslöser war nicht der Speicherbedarf: die VM war mit 22% genutzt und der Swap-Platz war leer. kswapd läuft kontinuierlich nur, weil der Page-Cache immer die VM füllt, also berührt er mehr Seiten als alles andere und ist der wahrscheinlichste Code, der auf eine beschädigte Seite stößt.

Drei Korruptions-Signaturen in unabhängigen Subsystemen innerhalb von zwei Wochen sehen nicht nach einem einzigen Kernel-Bug aus.

## Was der vmcore sagte

Mit `crash` und dem passenden `kernel-debuginfo` konnte der September 13 Dump manuell durchlaufen werden. Reclaim hatte einen Lock durch `folio->mapping->host` genommen, und diese Lock-Adresse lag innerhalb des dentry Slabs. Durchlaufen vom Folio zurück:

```
folio->mapping (observed)   ffff89417d547db0
real i_data of that inode   ffff89417d547df0
difference                  0x40, one bit
```

Der beobachtete Zeiger befindet sich innerhalb eines aktiven XFS-Inodes (einem 19 GB großen Film auf dem Medien-Array) und kann nicht der `i_data` eines Inodes in dieser Slab-Layout sein, also ist er beschädigt, nicht veraltet. Ein Bit in einem `struct page` hatte sich umgedreht.

Der August 30-Dump bestätigte dies: der Stack-Schutzmechanismus hatte ausgelöst, doch die Stack-, Task- und per-CPU-Canaries waren zu Dump-Zeit alle identisch. Der Vergleich hatte einmal einen falschen Wert gelesen.

Das Hardware-Untergrund erklärt, warum. sienar ist eine X299-Platte mit einem i7-7820X und nicht-ECC-Speicher (der Kernel-Log sagt `EDAC skx: ECC is disabled on imc 0`), und es wurde KSM ausgeführt, das identische Seiten über Gäste zusammenführt. Die führende Hypothese wurde zu Host-Speicher oder CPU-Instabilität, nicht zu einem RHEL-Kernel-Defekt.

## Der nächste Tag

Am 14. September zeigte sich dieselbe Instabilität im Benutzerbereich. dockerd starb mit einem Go-Laufzeit-Fatal-Fehler, `found pointer to free object`, was bedeutet, dass der Garbage Collector Heap-Korruption bemerkt. Der neu gestartete Daemon tötete alle verwaisten Container: 49 von ihnen über 21 Compose-Projekte, einschließlich des Edge-Proxy, dieser Website, des Medien-Stacks und des Discord-Bots.

`restart: unless-stopped` brachte genau einen davon zurück.

## Was es kostete

- **Etwa zehn Stunden eines dunklen Hosts,** von morgen bis abend.
- **Ein Uptime-Monitor, der es nicht erkennen konnte.** Der Monitor erstellt seine Container-Prüfungen dynamisch und entfernt diejenigen für Container, die nicht laufen, also sieht eine Massen-Stop-Prüfung wie weniger Monitore aus, nicht rote. Nur fünf statische Prüfungen wurden rot.
- **Ein Straggler, der seit vier Wochen offline war.** Nach dem Panik am 13. September wurde ein Dienst noch immer `Exited (255)` von einem Crash im August gefunden. Weder die Neustart-Richtlinie noch autoheal (das nur ungesunde laufende Container neu startet) hatten dies bemerkt.

Die Wiederherstellung erfolgte manuell: jedes Projekt wurde mit `docker compose up -d` aus dem Verzeichnis zurückgerufen, das in den Compose-Labels der Container genannt wurde.

## Was sich geändert hat

- **Stragglers beim Booten wiederherstellen.** `scripts/revive-stragglers.sh` sucht nach Containern, die mit Code 255 beendet wurden, eine Neustart-Richtlinie von `always` oder `unless-stopped` haben und von Compose verwaltet werden, und führt dann `docker compose up -d` für diese Dienste aus ihren eigenen Verzeichnissen aus. Absichtlich gestoppte Stacks beenden sich mit anderen Codes und werden in Ruhe gelassen. Eine systemd-Unit führt sie zwei Minuten nach dem Start von Docker aus.
- **live-restore konfiguriert.** Die Einstellung `live-restore` von Docker hält Container während eines Neustarts des Daemons am Laufen, sodass der nächste Crash von dockerd die Container nicht mitnehmen sollte. Sie ist in der Daemon-Konfiguration enthalten und greift beim nächsten Neuladen des Daemons in Kraft.
- **KSM ausgeschaltet auf sienar,** sodass eine umgedrehte Seite nicht in einen anderen Gast übertragen werden kann.
- **MGLRU-Schalter im Repository.** Ein Eintrag in tmpfiles.d deaktiviert die MGLRU-Rückgabefunktion:

```
  w /sys/kernel/mm/lru_gen/enabled - - - - n
  ```

Er ist noch nicht angewendet, und die RCA markiert ihn als optional: sie entfernt den Code-Pfad, der zweimal ausgelöst wurde, aber der nächste Flip würde einfach an einem anderen Ort landen.
- **vmcore-Bereinigung.** Seit spätem Juli deaktiviert eine tmpfiles.d-Regel kdump-Dumps, die älter als 14 Tage sind, sodass eine Serie von Panics den 20 GB `/var`-Volume nicht füllen kann (jeder Dump ist etwa 1 GB groß).
- **Eine RCA im Repository,** mit den Dump-Tabellen.

## Was immer noch offen ist

- Den nemesis VM für einige Wochen auf einen anderen Proxmox-Node verschieben, um ein A/B-Test durchzuführen. Wenn die Panics dort aufhören, ist sienar die Ursache.
- Memtest86+ auf sienar in einem Wartungsfenster ausführen.
- Ein Monitor für die Anzahl der laufenden Container hinzufügen, sodass ein Massen-Stop auch sichtbar ist, wenn die pro-Container-Prüfungen verschwinden.

## Was weitergeht

Ein Absturz, der immer in derselben Kernel-Funktion auftritt, ist kein Beweis für einen Kernel-Fehler; es kann beweisen, dass die Funktion am meisten Speicher berührt. Unterschiedliche Signaturen in unabhängigen Codeabschnitten auf demselben Gerät deuten unterhalb der Software hin, und ein Absturzdump plus Debug-Symbole können diese Vermutung in einen ein-Bit-Unterschied verwandeln. Auf der Docker-Seite: Eine Neustart-Richtlinie ist kein Wiederherstellungsplan nach einem uncleanen Absturz, und ein Monitor, der nur das laufende beobachtet, kann nicht berichten, was gestoppt wurde.
