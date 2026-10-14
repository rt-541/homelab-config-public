---
title: "Eine Claude Code-Konfiguration auf jedem Rechner"
dek: "Ein persönlicher Plugin-Marktplatz für die Skills, ein Plugin, das bei Session-Start die globale Konfiguration abruft und lokale Änderungen zurücksendet, und ein Review-Bot, der saubere Pull-Requests landet."
lang: de
source: one-claude-config-on-every-machine
source_hash: 29dccfd0b07ab734
model: qwen3-14b
---

Claude Code läuft hier auf Windows-Clienten, Linux-Clienten und RHEL-Servern. Jeder hat eine globale `CLAUDE.md`, eine `settings.json`, einige Fähigkeiten und Befehle, und jeder hatte sich in eine leicht unterschiedliche Menge entwickelt. Das alte Fix war manuelles Kopieren oder eine Ansible-Rolle, die Dateien verteilt hat, wenn jemand daran erinnert wurde, sie auszuführen. Beides bemerkte keine Änderung, die auf einem Gerät vorgenommen wurde, die nie zurückkehrte.

## Ein Marktplatz für die Fähigkeiten

Claude Code kann Plugins aus einem Marktplatz installieren, und ein Marktplatz ist einfach ein Git-Repo mit einer Manifestdatei, die seine Plugins auflistet. Am 2026-09-18 wurde ein privates Repo zu einem solchen. Es listet jetzt fünf Plugins:

- **workshop**: die build-plan- und shopcad-model-Fähigkeiten hinter den physischen Plänen auf dieser Seite;
- **homelab-ops**: die Fähigkeit, die LLM-Aufträge an die homelab-Flotte sendet;
- **gpu-llm**: eine Fähigkeit plus ein MCP-Server für ein auf Anfrage lokales Modell auf einem Gaming-GPU;
- **docs-tools**: Mermaid-Diagramme und Obsidian-Markdown;
- **config-sync**: das Plugin, das alles andere aktuell hält.

Die meisten begannen als lose Fähigkeiten in einem dotfiles-Repo. Das gpu-llm-Plugin existierte nur auf einem Gerät, in einem Commit, der nie gepusht wurde. Es wurde aus diesem Checkout in den Marktplatz gezogen und geändert, um seinen Host über einen DNS-Namen anstelle einer bereits veralteten IP-Adresse zu erreichen.

## Zwei Quellen der Wahrheit

Das dotfiles-Repo ist die Quelle der Wahrheit für Dateien: die globale `CLAUDE.md`, `settings.json`, die Fähigkeiten, die keine Plugins sind, und die Befehle. Der Marktplatz ist die Quelle der Wahrheit für Plugins, und eine Änderung eines Plugins wird durch das Erhöhen seiner Version übertragen. Projektbezogene Speicher, `settings.local.json`, Anmeldeinformationen und Zwischenspeicher werden nie berührt.

## config-sync

Der config-sync-Plugin, erstellt am 2026-09-19, ist ein Bash-Skript und ein `SessionStart`-Hook. Bei jedem Sitzungsstart hashiert er jedes verfolgte Element und wendet das Sicherere an. Die Netzwerkaktivitäten (dotfiles-Checkout beschleunigen, den Marketplace aktualisieren, jeden aufgelisteten Plugin installieren oder aktualisieren) finden maximal einmal alle 24 Stunden statt. Wenn alles im Einklang ist, gibt es nichts aus. Wenn etwas eine Entscheidung benötigt, gibt es Zeilen, die mit `config-sync:` beginnen, und eine Fähigkeit im selben Plugin erklärt Claude, wie diese gelesen und entschieden werden sollen.

Der Teil, der es sicher macht, ist eine kleine Zustandsdatei, die den zuletzt angewandten Hash für jedes Element enthält. Das verwandelt jede Vergleichsoperation in eine Dreier-Vergleichsoperation:

- Das Repo hat sich verändert und die lokale Kopie nicht: wende es an, still und leise;
- Die lokale Kopie hat sich verändert und das Repo nicht: melde es und überschreibe es nie; `push` trägt die Änderung zurück ins Repo, damit die anderen Maschinen sie aufnehmen;
- Beide haben sich verändert: melde einen Konflikt; `--force` auf `apply` oder `push` wählt den Sieger.

`settings.json` wird als JSON verglichen, wobei die Reihenfolge der Schlüssel ignoriert wird, so dass eine umgeordnete Datei nicht als Änderung zählt.

Die Oberfläche des Skripts ist klein:

```
config-sync.sh status              # what differs, changes nothing
config-sync.sh apply [--force]     # pull, apply safe updates, update plugins
config-sync.sh push [-m msg]       # fold local edits back, commit, push
config-sync.sh diff <key>          # installed vs repo for one item
```

Auf einer neuen Maschine ist das Bootstrap-Verfahren zwei Zeilen: den Marketplace registrieren und config-sync installieren, gefolgt von einem Neustart. Der Hook der ersten Sitzung klont das dotfiles-Repo und installiert die globale Konfiguration sowie die anderen vier Plugins. Windows führt es unter Git Bash aus.

Die Tests führen fünfzehn Prüfungen an einem temporären Heimat- und dotfiles-Repo durch, mit einem gestubbeden `claude`-Binary und ohne Netzwerk. Auf der ersten echten Maschine übernahm `status` alle neun verfolgten Elemente als bereits im Schritt vorhanden, und der erste `push` brachte einen neuen Abschnitt der globalen `CLAUDE.md` zurück ins Repo.

## Ein Review-Bot, später

Am 2026-09-24 wurde eine GitHub Action hinzugefügt, um jeden Pull Request zu überprüfen, der nicht als Entwurf markiert ist, und eine Genehmigung oder eine Anfrage zur Änderung an den Kopf-Commit anzuhängen, sowie die sauberen Pull Requests zu mergen. Es wird nur gemerged, wenn der Kopf-Commit nicht verschoben wurde, keine `no-automerge`-Beschriftung vorhanden ist und nichts unter den Verzeichnissen workflow oder plugin geändert wurde. Die erste Version überprüfte mit Claude; eine Folge am selben Abend wanderte die Überprüfung auf den kostenlosen lokalen Modell auf der NanoClaw-Flotte, damit sie im LAN bleiben. Da der Bot keine Änderungen an seinem eigenen workflow-Verzeichnis mergen wird, benötigte der Pull Request, der ihn hinzufügt, einen Menschen, um ihn zu mergen.

## Was nicht funktioniert hat

- **Der push-only Ansible Role.** Er wird als Ausweichlösung beibehalten, aber das Pushen von Konfigurationen kann keine Änderungen am entfernten Ende erkennen. Das Pullen beim Start der Sitzung kann das jedoch.
- **Das Schreiben des Plugins an die richtige Stelle.** Der Auto-Modus von Claude Code weigerte sich, das Skript und die Hookdatei in das Plugin-Verzeichnis zu schreiben, da dies als Selbstmodifikation markiert wurde. Das Staging an einem anderen Ort und das anschließende Kopieren in das Zielverzeichnis war jedoch erlaubt. Der Review-Bot stieß auf die gleiche Wand in seinem Merge-Skript ("Merge ohne Review") und wurde erst nachdem der Besitzer ihn außerhalb des Auto-Modus genehmigte, geschrieben.
- **Teststubs in `/tmp`.** `/tmp` wird `noexec` auf dem Hauptserver gemountet, sodass die dort platzierten Stub-Binärdateien stillgeschaltet werden und die echte Datei ausgeführt wird. Für config-sync laufen die Stubs nun durch `sh`. Für den Review-Bot erreichten die Tests das echte GitHub CLI, erhielten eine 422 und posteten nichts; `gh` wird nun als Shell-Funktion gestubbed.

## Was weitergegeben wird

Ein globales Edit hat nun einen Pfad: es wird auf jedem beliebigen Gerät `push` vorgenommen, und der Rest konvergiert beim nächsten Start der Sitzung. Eine neue verfolgte Datei ist ein Fall im Skript und eine Versionserhöhung. Die Kopien der Fähigkeiten im dotfiles-Repository, die in Plugins verschoben wurden, sind immer noch vorhanden und werden einmal ausgeführt, sobald alle Geräte config-sync ausführen.
