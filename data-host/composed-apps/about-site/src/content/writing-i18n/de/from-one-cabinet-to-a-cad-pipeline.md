---
title: "Von einem Schrank zu einer CAD-Pipeline"
dek: "Wie ein einzelner Spulenschrank-Plan zu einer Methode für die Erstellung von Bauplänen wurde: ein Python-Modul pro Bau, Zeichnungen und Prüfungen aus denselben Zahlen, Preise aus echten Listen, und eine Fähigkeit, die die Lehren behält."
lang: de
source: from-one-cabinet-to-a-cad-pipeline
source_hash: b5b5727fe04eb573
model: qwen3-14b
---

Der erste physische Plan auf dieser Seite war ein [Schrank für 3D-Druck-Filament](/projects/spool-cabinet). Er begann als Claude.ai-Artifact und wurde am selben Tag hierher verschoben, weil ein Plan in einem Chat schwer zu finden, zu überarbeiten oder zu verlinken ist.

## Der Spool-Schrank, vier Überarbeitungen in zwei Tagen

Revision A (2026-09-12) war ein Schrank mit Acryl-Türen und einem Heizkasten, der bei 75 C lief. Am selben Abend erhielt er ein Fusion 360-Skript, eine STEP-Datei und eine GLB-Datei, sodass der Plan ein bearbeitbares Modell und nicht nur Zeichnungen enthielt.

- **B** senkte den Trockner auf 65 C. Die Ablage enthält PLA, PETG und TPU, und PLA sollte nicht viel über 55 C gelagert werden.
- **C** befestigte die Ablagen mit Taschenschrauben und 1x3-Auflagebalken. Klemmbücher auf einer belasteten 46 in Spanne würden sich verziehen.
- **D** (2026-09-13) baute den Schrank um, um ihn mit temperierten Glas-Türen von IKEA OXBERG zu versehen, entfernte den Heizkasten und fügte eine Einkaufsliste hinzu, in der jeder Preis mit einer Liste verglichen wurde. Das Trocknen wurde zu einer Aufgabe für einen gekauften Dehydrator.

Eine Version mit zwei Bays, die 112 Spulen aufnehmen konnte, hielt etwa eine Stunde, bevor sie auf eine BILLY-Breite reduziert wurde: zwei OXBERG-Türen, 56 Spulen, die mit einem 4 in Neigung an der Seite stehen. Die früheren Höhenpläne zeigten die Spulen als Kreise von vorn, was falsch war, wenn die Spulen entlang der Schienen standen; der Eigentümer bemerkte das und korrigierte die Neigung und die Zeichnungen gemeinsam.

Die ersten Preisabschätzungen waren in beide Richtungen falsch: zu hoch für Sperrholz und Ständer, zu niedrig für Acryl und Poplar. Danach war ein Preis eine Liste, die an diesem Tag mit dem Namen des Geschäfts gelesen wurde, oder es wurde aus dem Gesamtpreis ausgeschlossen.

## Der Garagenladen, ein ganzer Raum

Die [Garagenwerkstatt](/projects/garage-shop) (2026-09-18) war ein größeres Problem: ein Raum mit einem abgestellten LKW, einem Wandregal, rollenden Werkzeugen, einem Staubwagen und einem Unterpanel. Die Revision A wurde anhand einer angenommenen Garage erstellt. Die Revision B (2026-09-19) wurde anhand der gemessenen Garage erstellt, mit einer Landung über der Rückwand, einer Haustür, die sich an einem anderen Ort befand als die Fotos es vermuteten, und ohne Handkreissäge.

Ein Raum mit so vielen beweglichen Teilen konnte nicht durch bloßes Anschauen auf einer Flachzeichnung überprüft werden.

## shopcad: ein Modul, jede Ausgabe

Also am 2026-09-18 wurde das CAD zu einem Framework. Jeder Bau ist ein Python-Modul. Sein `DEFAULTS` enthält jede Zahl, die eine Person ändern würde, in Zoll. Eine `build`-Funktion platziert Kästen und Zylinder anhand dieser Zahlen, und eine `checks`-Funktion gibt Pass oder Nicht-Pass zurück, mit den Zahlen in der Nachricht.

Aus diesem einen Modul entstanden:

- ein three.js-Viewer mit Zuständen (Türen geöffnet, Bank umgedreht);
- eine STEP-Datei für die Szene und eine pro Bau;
- PNG-Renditionen für die Blätter, erstellt mit headless Chrome und Software-WebGL;
- ein Fusion 360-Skript, dessen Benutzerparameter dieselben Zahlen sind;
- die Prüfungen, die den Export stoppen, wenn eine Zahl nicht mehr funktioniert.

Der Spool-Schrank wurde am selben Tag mit zehn Prüfungen neu erstellt. Die Garage erreichte bei Revision B 24 Prüfungen und später 40. Die Regel, die daraus entstand: Wenn das Modell mit einem Blatt nicht übereinstimmt, ist das Modell in der Regel richtig, weil es die Geometrie schließen musste. Ein Schrank auf einem französischen Klemmholz steht 1,5 Zoll vom Wand ab, unabhängig davon, was das Blatt sagt.

## Schreiben Sie es als Fähigkeiten auf

Der Workflow ging in ein Claude Code-Plugin namens `workshop`, in einem persönlichen Skill-Marktplatz, der im homelab-Repo gehalten wird. Es hat zwei Skills. `build-plan` ist für das Design-Dialog, die ingenieurtechnischen Prüfungen, das Zeichnungsset, die Preise und die Lieferung verantwortlich. `shopcad-model` ist für das Plan-Modul und seine Ausgaben zuständig. Version 1.1.0 integrierte, was der Garage und der Felsenscreen gelehrt hatten, sodass der nächste Plan dies nicht erneut lernt.

## Der Felsenbildschirm, ein kleiner Jig

Der [Felsen-Screen](/projects/rock-screen) (2026-09-19) reinigt Kieselsteine unter einem Pool in 50 lb Leinenbeutel. Es ist ein 24 x 48 in geneigter Träger auf einem 2x4-Fußbrett, um 9 in hinter der Entleerungsende gekippt, so dass es bei Beladung mit etwa 23 lb am Griff um 35 Grad kippt und durch ein Sperrholz-Funnel in einen auf einem Handwagen stehenden Beutel abläuft.

Seine Zeichnungen werden durch ein Skript aus geometrischen Konstanten generiert, anstatt von Hand gezeichnet zu werden. Die Größe des Beutels bestimmt den Auslauf, und der 50 lb-Beutel zwang einen 11 x 11 in Auslauf auf 9 x 9. Eine Konstante geändert, und der Funnel, die Materialliste und die Kopie folgten. Die Füllregel wurde auch zu einer Blattlinie: Felsen wiegen etwa 100 lb pro Kubikfuß, also ist ein Beutel drei Schaufeln, 45 lb, und etwa 60 Beutel machen einen Kubikmeter.

## Dann der Hinterhof

Der nächste Plan war ein Deck und ein Terrassenbereich, der aus Drohnenfotos erstellt wurde, und er brachte das Framework ins Freie und in die photo-stilistische Darstellung. Diese Geschichte ist in [einem Hinterhof, erstellt aus Drohnenfotos](/writing/backyard-from-drone-photos); der Plan befindet sich unter [/projects/backyard](/projects/backyard).

## Was weitergeführt wird

- **Jede Grenze wird zu einer Blattlinie oder einem Modellcheck.** Ein Schwingradius, ein Arbeitsbereich, ein Sackgewicht oder eine Regalbreite ist entweder auf einem Blatt gedruckt oder vom Modell erzwungen, am besten beides.
- **Preise stammen nur von Listen, die tatsächlich gelesen wurden.** Der Laden wird benannt, das Datum wird aufgezeichnet, und ein Preis, der nicht gelesen werden konnte, wird als „nicht gelesen“ markiert und aus dem Gesamtbetrag ausgeschlossen.
- **Seiten werden bei Desktop- und schmaler Breite gerendert und geprüft.** Jedes Blatt wird einzeln mit den realen Schriften bei 1100 und 720 px gerendert, bevor es veröffentlicht wird, weil Menschen diese auf halbem Monitor lesen.
- **Das PDF wird headless gedruckt.** Ein Druckumhüllung und headless Chrome erledigen dies, und die Seitenzahl wird mit der vorherigen PDF-Datei verglichen, damit die Regeln für die schmale Layout nicht still die Seitenzahl verdoppeln.
- **Pläne leben auf der Website, nicht in Chat-Artefakten.** Der [Spulenregal](/projects/spool-cabinet) war der erste, der sich bewegte, und jeder Plan seitdem begann hier.
