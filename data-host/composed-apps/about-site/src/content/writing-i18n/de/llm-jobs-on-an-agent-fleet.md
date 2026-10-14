---
title: "LLM-Aufgaben auf einer Agentenflotte"
dek: "Der fire-and-forget-Arbeitsauftragsdienst für LLM im Homelab, zunächst als Warteschlange vor dem LiteLLM-Gateway erstellt, dann neu aufgebaut, sodass jeder Auftrag eine Einmal-Aufgabe für eine NanoClaw-Agentengruppe ist, mit lokalen, Claude- und Blender-Renderebenen."
lang: de
source: llm-jobs-on-an-agent-fleet
source_hash: a4f84adc1c843c27
model: qwen3-14b
---

Einige LLM-Arbeiten passen nicht in die Sitzung, die sie sich vorstellen: Hunderte von Zusammenfassungen, eine Charge an Klassifizierungen, ein langer Entwurf mit geringem Risiko, alles Private, das auf dem LAN bleiben sollte. Der Homelab hat einen kleinen Dienst dafür. Ein Aufrufer sendet einen Prompt und eine Ebene, erhält sofort eine Job-ID und sammelt das Ergebnis später ein. Dieser Dienst wurde bereits zweimal gebaut.

## Version 1: eine Warteschlange und ein Gateway

Die Version im Juni 2026 lief auf nemesis als zwei Stacks. `llm-queue` war eine FastAPI-App mit einem Web-Dashboard, einer REST-API und einem MCP-Endpunkt, alles über eine SQLite-Datenbank im WAL-Modus. Aufrufer wählten einen Fähigkeitsalias (`fast` auf dem B70's vLLM, `background` und `reasoning` auf CPU Ollama), und jeder Alias hatte seinen eigenen Worker, sodass ein langsamer CPU-Auftrag niemals einen GPU-Auftrag blockierte.

Die zweite Phase platzierte ein LiteLLM-Gateway vor den Modellen. Das Gateway erteilte jedem Benutzer einen virtuellen Schlüssel, und dieser Schlüssel war das Login überall: Web-Oberfläche, REST und MCP. Die Warteschlange begrenzte Jobs auf eine Hash des Schlüssels und ließ jeden Job über das Gateway als dieser Benutzer laufen, sodass die Quoten an einem Ort lagen. Das bedeutete, dass der Worker den Schlüssel des Aufrufers nach dem Rückgabevereinbarung benötigte, also trug jede Job-Zeile den Schlüssel Fernet-verschlüsselt, und der Worker entschlüsselte ihn, führte den Job aus und entfernte ihn nach Abschluss oder Abbruch des Jobs. LiteLLM würde seine Schlüssel nicht in SQLite speichern, also benötigte das Gateway auch einen Postgres-Sidecar.

Es funktionierte, und es war eine Menge Maschinerie.

## Die Flotte, auf die es migrierte

Im September bekam das homelab eine NanoClaw-Flotte auf devastator. NanoClaw läuft Claude Code-Agenten in Containern, organisiert als Agentengruppen: jede Gruppe hat ihre eigenen Anweisungen, ihre eigenen Fähigkeiten, ihre eigenen Mounts und Umgebungen und wird für Nachrichten aus einem Kanal oder für geplante und einmalige Aufgaben geweckt. Einige Gruppen kommunizieren direkt mit Anthropic. Andere laufen auf qwen3-14b, die von vLLM auf dem lokalen B70 bereitgestellt und über einen kleinen Normalisierungsproxy erreicht werden, der die API des lokalen Modells genug wie Anthropics verhält, damit der Claude Code-Harness funktioniert (es faltet Systemnachrichten, begrenzt Ausgabetoken und schaltet den Denkmodus von qwen3 aus).

Diese Flotte hatte bereits die Routing, Zugriffssteuerung und Audit durchgeführt, die die Warteschlange für sich selbst gebaut hatte. Und nichts hatte die Warteschlange in 30 Tagen genutzt.

## Version zwei: Jobs als Agentenaufgaben

Am 2026-09-19 wurden die Warteschlange und der Gateway abgebaut und aus dem Repository entfernt. Der Ersatz, `llm-jobs`, ist ein Python-Standardbibliotheksdienst, der als systemd-Benutzerunit auf devastator läuft. Er besitzt zwei Dinge, Schlüssel und Jobs, beide in einer SQLite-Datei. Alles andere ist NanoClaw.

Ein Job verläuft wie folgt:

1. Ein Aufrufer sendet einen Prompt und eine Ebene.
2. Der Dienst erstellt eine einmalige NanoClaw-Aufgabe in der Agentengruppe dieser Ebene.
3. Der Container der Gruppe wird mit einem kurzen Worker-Vertrag vorgestellt: führe genau den Job aus, liefere einmalig, keine Kanalbeiträge, keine Fragen.
4. Der Agent ruft das MCP-Tool des Dienstes `deliver_result` mit der Job-ID und seiner Antwort auf, oder mit einem Fehlermeldung, wenn der Job nicht durchgeführt werden kann.
5. Der Aufrufer fragt ab und ruft die Daten ab.

Claude Code-Sitzungen erreichen es als MCP-Server mit drei Tools, die wichtig sind: `submit_job`, `get_status` und `get_result` (plus `list_tiers`, `list_jobs` und `cancel_job`). Ein typischer Aufruf sieht wie folgt aus:

```
submit_job(
  tier="local",
  prompt="Summarize the release notes below in five bullets for a homelab operator. <notes...>",
  params={"max_words": 150}
)
```

Der Prompt muss selbstständig sein; der Worker sieht nichts anderes. Die `params` Hinweise werden zu Zeilen im Worker-Vertrag. Schlüssel sind Bearer-Schlüssel, die pro Besitzer begrenzt sind: ein Aufrufer sieht nur seine eigenen Aufgaben, und die Ergebnisse werden 30 Tage lang gespeichert. Eine Aufgabe läuft pro Tier gleichzeitig ab, und eine Aufgabe, die innerhalb ihres Timeout keine Lieferung hat, wird als fehlgeschlagen markiert und ihre Aufgabe wird abgebrochen.

## Drei Tiers

- **local** läuft auf der `jobs-local` Gruppe: qwen3-14b über den Proxy, wobei Anthropic im Container blockiert ist. Kostenlos und privat. Eine triviale Aufgabe kam nach 16 Sekunden zurück.
- **claude** läuft auf `jobs-claude`: Sonnet, abgerechnet. Eine triviale Aufgabe benötigte 50 Sekunden. NanoClaw hat keine pro-Gruppe Nutzungsgrenze, daher erzwingt der Dienst eine: tägliche Schlüsselobergrenzen pro Schlüssel, plus eine tägliche Obergrenze für Aufgaben und Ausgabetoken, die jeder Schlüssel teilt. Unabhängig davon, wie viele Schlüssel vorhanden sind, hat das abgerechnete Tier eine Obergrenze.
- **render**, hinzugefügt am 2026-09-26, läuft auf `jobs-render`. Der Prompt ist ein JSON-Rezept (ein Modell-URL, Ansichten, Proben, Größe), die Gruppe hat eine `blender-render` Fähigkeit und eine nur-lese Blender-Installation, und es rendert Stillleben headless mit Cycles. Ein Tier kann nach Artefakten fragen, und dieses tut es: jede Aufgabe erhält ihr eigenes Verzeichnis, das in den Container gemountet wird, `get_result` listet die Dateien, und der Dienst liefert sie dem Besitzer der Aufgabe. Mit `"photo": true` im Rezept ruft der Worker auch `request_photo` für jede Ansicht ab und fragt `photo_status`. Das schaltet einen Durchlauf über den GPU-Verwalter auf devastator, der die B70 von vLLM an ein FLUX Kontext-Bildmodell verleiht, wenn die Karte leer ist, und ein Foto neben jedem Render schreibt.

Die Worker-Tools (`deliver_result`, `request_photo`, `photo_status`) sind nur für Worker sichtbar.

## Was nicht funktioniert hat

- **qwen3 kann keine Toolaufrufe über den Proxy durchführen.** Plain-Text-Aufgaben funktionieren auf der lokalen Ebene. Hinter dem Proxy schlägt qwen3-14b bei Tool-Aufrufen mit der Fehlermeldung "Content block is not a text block" fehl, und eine Renderaufgabe besteht aus nichts anderem als Toolaufrufen. Die Renderebene läuft stattdessen auf Sonnet, unter einem eigenen kleinen täglichen Limit; eine Renderaufgabe benötigt nur wenige dieser Aufrufe.
- **Keine GPU in Agent-Containern.** NanoClaw hat keine Geräte-Übergabe, daher rendert Blender auf der CPU, etwa 35 Sekunden pro Ansicht bei 128 Proben. Der Schritt für Fotos erhält die GPU, weil der Arbiter auf dem Host läuft, außerhalb von NanoClaw, und der Worker ihn über MCP um Fotos bittet.

## Was weitergegeben wird

Die zweite Version ist kleiner, weil sie Dinge nicht mehr besitzt, die bereits von einem anderen System besessen werden. Der Job-Service behält Schlüssel, Aufgaben, Limits und Artefakte; NanoClaw behält Modelle, Container, Fähigkeiten und Anmeldeinformationen. Eine neue Ebene ist eine neue Agentengruppe mit eigenen Anweisungen und Fähigkeiten, plus einem Eintrag in der Ebentabelle, und so kam ein Blender-Rendern eine Woche später ohne Änderung an der Art, wie Aufrufer ihre Anfragen stellen. Und das Liefervertrag ist für jede Ebene gleich: der Worker ruft ein Tool genau einmal auf und hört dann auf.
