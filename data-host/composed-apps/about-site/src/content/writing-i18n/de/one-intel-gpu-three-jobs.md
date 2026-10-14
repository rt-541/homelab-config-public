---
title: "Eine Intel-GPU, drei Aufgaben"
dek: "Eine Intel Arc Pro B70 in einem RHEL-VM dient einem lokalen Sprachmodell, transcodiert für Plex und, wenn beide ruhig sind, wird sie für ein Bildmodell genutzt, wobei ein kleiner Schiedsrichter entscheidet, wer die Karte hat."
lang: de
source: one-intel-gpu-three-jobs
source_hash: 90b822f2afb6ceb3
model: qwen3-14b
---

Die Grafikkarte ist eine Intel Arc Pro B70: Battlemage, 32 GB, die an ein RHEL-VM namens devastator weitergeleitet wird. Sie wurde für eine Aufgabe gekauft, um einem lokalen Sprachmodell auf der NanoClaw-Flotte Agenten zu dienen. Sie endete mit drei: das Sprachmodell, Plex-Hardware-Transkodierung (plus einer Kampagne, die 4K-Remuxes über VAAPI neu kodiert, um Speicherplatz zurückzugewinnen), und seit heute, 3D-Rendern in Fotos umzuwandeln.

## Die Karte zum Erscheinen bringen

Der Treiber, der diese Karte kennt, ist `xe`, und die Geräte-ID muss darin enthalten sein. Der Kernel von RHEL 10.0 hatte sie nicht. Das In-Place-Upgrade von 9.6 hatte die Abonnement-Release auf 10.0 festgelegt, also bewegte sich `dnf update` den Kernel nie weiter. Das Festlegen des Releases auf 10.2 und das Aktualisieren brachten einen von Red Hat signierten Kernel mit der ID zurückportiert, und nach einem Neustart erschien die Karte:

```
Kernel driver in use: xe
```

zusammen mit einem Render-Node und den GuC- und HuC-Firmware, die von `linux-firmware` geladen werden. Der Plex-Container, der bereits `/dev/dri` gemountet hatte, erkannte den neuen Render-Node ohne Änderungen.

## Ein Modell mit vLLM bereitstellen

vLLM läuft vom Intel llm-scaler-Image (`intel/llm-scaler-vllm:0.14.0-b8.3.1`) aus, das über seine eigene oneAPI- und Level Zero-Stack mit der Grafikkarte kommuniziert, getrennt vom Medien-Treiber, den Plex verwendet. Das bereitgestellte Modell wurde in Schritten weiterentwickelt: Qwen2.5-7B, dann Qwen3-14B als AWQ, gefolgt von einem Test mit Qwen3-30B-A3B.

Die 30B ist ein Mischung aus Experten mit etwa 3,3B Parametern aktiv pro Token, sodass sie sich wie ein kleines Modell decodiert. Intels Rezepte zeigen es nur über zwei oder mehr Karten verteilt, da sie es in FP16 (etwa 61 GB) laufen lassen oder es in Echtzeit quantisieren, was zunächst das gesamte Modell in den Host-RAM lädt. Ein bereits auf INT4 quantisiertes Checkpoint ist etwa 17 GB groß und passt in einen B70. Es muss GPTQ sein: in diesem Image erhalten nur GPTQ-Checkpoints eine quantisierte Methode für die MoE-Schichten.

Für die Agenten waren zwei Einstellungen wichtig. Die erste war der Kontext. Allein das Agenten-Setup sendet etwa 16k Tokens von Prompt und Tool-Schemata, sodass das Fenster auf 32k, dann auf 64k mit statischem YaRN auf dem 7B (ein Faktor von 2 über seine 32k Basis, die Methode, die Qwen dokumentiert) erhöht wurde. Die zweite Einstellung war die Tool-Aufrufe. Ohne Parser gab das Modell seine Tool-Aufrufe als reinen Text zurück; mit dem aktivierten Hermes-Parser kamen sie als echte Aufrufe zurück:

```
- --enable-auto-tool-choice
- --tool-call-parser
- hermes
```

## Platz für Plex lassen

vLLM beanspricht zu Startzeit einen festen Anteil der Grafikkarte. Dieser Anteil ging von 0,75 über 0,80 und 0,92 bis zu 0,85, was ungefähr 4,8 GB für Plex lässt: zwei 4K HDR-Transkodierungen mit jeweils etwa 2 GB plus Spielraum für den Treiber. Ein dritter Stream fällt auf die CPU zurück. Das Modell bemerkte dies kaum; der KV-Cache hatte immer noch Platz für viele parallele Anfragen.

## Die Grafikkarte weitergeben

Bildgenerierung benötigt den Großteil der Grafikkarte, und vLLM kann während des Betriebs seinen Speicher nicht verkleinern. Es reserviert zu Startzeit und verkleinert sich nicht. Daher wechselt das Design die Nutzung statt den Pool zu teilen.

**Ein Aufzeichner.** Alle 60 Sekunden liest ein Root-Timer die DRM fdinfo aller Prozesse, wo der `xe` Treiber pro Client VRAM und die Zeit, in der der Engine beschäftigt ist, meldet. Clients werden nach ihrem Container benannt oder nach dem Befehlsnamen, daher zählt jeder Plex Transcoder-Prozess als `plex`. Er schreibt einen aktuellen Snapshot und eine monatliche Historie-Datei. Die Historie beantwortet auch eine offene Frage: Plex hat auf dieser Grafikkarte Hardwarebeschleunigung und viele Wiedergaben, aber es gab keine Aufzeichnung, wie oft es tatsächlich transkodierte.

**Ein Schlichter.** Ein kleiner Dienst verwaltet eine Warteschlange für Fotobegehren und einen Modus: `llm`, `swapping` oder `image`. Er wechselt erst zu `image`, wenn die Warteschlange nicht leer ist, vLLM seit 60 Sekunden keine laufenden, wartenden oder abgeschlossenen Anfragen hatte und der Aufzeichner keine anderen Clients auf der Grafikkarte anzeigt. Dann stoppt er vLLM, startet ComfyUI mit FLUX.1 Kontext, bearbeitet die Warteschlange und gibt die Grafikkarte zurück, sobald die Warteschlange leer ist oder 15 Minuten vergangen sind. Er erklärt `llm` erst, nachdem vLLM auf seine Gesundheitsprüfung reagiert hat.

**Ein Patientenproxy.** Die NanoClaw-Agenten erreichen vLLM über einen kleinen Proxy. Dieser liest den Modus des Arbiters und hält Anfragen an, solange der Modus nicht `llm` ist, und versucht, abgelehnte Verbindungen erneut herzustellen. Ein Agent, der während eines Wechsels spricht, wartet stattdessen, anstatt zu scheitern.

Gemessen am ersten Tag: der Wechsel zu `image` plus das erste Foto dauerte 85 Sekunden, jedes Foto danach 52 bis 62 Sekunden bei 1328x800 und 24 Schritten, und vLLM war 56 Sekunden nach der Rückgabe wieder gesund.

## Was nicht funktioniert hat

- **Ein Mainline-Kernel.** Der ELRepo-Kernel-ml erkennt die Grafikkarte, ist aber nicht signiert, und die VM startet mit Secure Boot. Die Firmware lehnte es ab, bevor der Userspace geladen wurde. Selbst mit einer selbst eingerichteten Maschinenbesitzer-Schlüssel-Signatur startete sie nicht. Sie wurde entfernt; diese VM läuft nur mit signierten Kernen von Red Hat.
- **Qwen3-32B.** Es wurde 252 Mal neu gestartet, was wie ein VRAM-Problem aussah. Der Kernel-Log sagte etwas anderes: ein Speicher cgroup Kill bei 8,3 GB RSS, was der `memory: 8G` Grenze im Kompositionsdatei entsprach. Die Grenze wurde für den nächsten Versuch auf 16 GB erhöht.
- **In-Place-Resizing.** Es gibt keine Möglichkeit, einem laufenden vLLM Speicher zurückzugeben, was der Grund dafür ist, dass der Arbiter existiert.

## Was weitergeführt wird

Der Plan ist ein zweiter B70. Die beiden Karten würden in einem zweiten Rechner einen Tensor-Parallel-Pool (TP=2, 64 GB) bilden, da der aktuelle Host eine Mini-ITX-Platte mit nur einem PCIe-Slot ist. Plex und der Transcode-Kampf würden dann auf Arc A380-Karten wechseln. Bis dahin gilt das Muster für jede gemeinsam genutzte Beschleunigungskarte: messen, wer darauf ist, bevor man etwas entscheidet, und wenn eine Arbeitslast nicht kleiner werden kann, tausche die ganze Karte anstelle davon, sie zu teilen.
