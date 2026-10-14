---
title: "Ein Hinterhof, gezeichnet aus Drohnenfotos, gerendert vom Homelab"
dek: "Fünf Überarbeitungen einer Terrasse, eines Steinpflasters und eines Feuerkreises an einem Tag, wobei jede Zeichnung, Prüfung und Menge von einem Python-Modul stammt, und photoartige Ansichten von einem Blender-Arbeiter auf der NanoClaw-Flotte plus FLUX Kontext auf einer gemeinsam genutzten GPU."
lang: de
source: backyard-from-drone-photos
source_hash: 59600bce7c2bd0bb
model: qwen3-14b
---

Der Auftrag kam als Satz und als Ordner mit acht Drohnenfotos: ein Komposit-Deck mit einer Treppe an einer Ecke und einer weiteren zur Stein-Terrasse, eine Reihe von Nadelbäumen entlang der hinteren Zaunlinie, ein Französischer Abfluss, an dem der Garten überflutet, und einen Platz zum Anbauen von Gemüse. Keine Maßbandmessungen. Das Ergebnis hatte die gleiche Form wie die anderen Pläne auf dieser Seite: ein Zeichensatz, den man einem Auftragnehmer geben könnte, ein PDF, ein 3D-Modell und eine Preisliste, bei der jede Zeile eine tatsächlich gelesene Angabe ist.

## Das Grundstück von oben betrachtet

Drohnenfotos enthalten mehr als nur Bilder. Die Flugrichtung in den Metadaten jedes Bildes bestimmte, in welche Richtung das Haus zeigt (der eigene Kippmechanismus der Kamera auf dieser Drohne ist nicht vertrauenswürdig; die Flugrichtung ist es), und eine bekannte Breite im Bild gab eine Skala: das Haus war ungefähr 52 Fuß breit, der Garten etwa 50 Fuß tief. Alles in der Version A ist als Schätzung markiert, und der erste Blatt listet die sechs Messungen auf, die es zur Version B machen.

Die Fotos enthalten auch GPS-Koordinaten. Diese verlassen nie die Arbeitskopie; nichts, was hier veröffentlicht wird, sagt, wo das Haus ist.

## Ein Modul, viele Ausgaben

Der Plan lebt in einer einzigen Python-Datei. Seine `DEFAULTS` enthalten jede Zahl, die eine Person ändern könnte: Grundstück, Haus, Bucht, Schornstein, Deck, Treppe, Terrasse, Feuerkreis, Bäume, Abfluss. Alles andere leitet sich von ihnen ab, einschließlich der Geländekante, die eine Ebene ist, die zum hinteren Zaun und zum Eckenabfluss abfällt.

Aus diesem einen Modul entstehen:

- die 3D-Datei, exportiert als GLB, STEP und ein Fusion 360-Skript;
- die fünfzehn SVG-Zeichnungen auf den Blättern (Grundriss, Schnitt, Tragwerk, Ansichten, Treppen, Terrasse, Feuerkreis, Sitzwand, Kräutergarten, AC-Screen, Bäume, Abfluss);
- die Mengen, mit denen die Angebote übereinstimmen sollten (Bohlen, Schutz, Pfeiler, Tonnen Flagstein, Kubikyard Unterlage, Wandstein);
- etwa vierzig Prüfungen, die den Export verhindern, wenn eine Zahl nicht mehr funktioniert: Treppenstufen über 7,75 Zoll, ein Träger mit Überstand über ein Viertel seiner Spannweite, ein Feuerkreis zu nahe am Arborvitae, Stühle, die nicht mehr auf den Stein passen.

Das ist am wichtigsten, wenn sich das Design verändert, und es veränderte sich viel.

## Fünf Überarbeitungen an einem Tag

Überarbeitung A platzierte eine Garten-Terrasse nördlich einer breiten Plattform, einen Feuerkreis im Westen und neun schräg gestellte Green Giants entlang der Zaunlinie. Dann sah der Eigentümer es an.

- **A2.** Die Plattform wurde auf die Schiebetür reduziert, die Terrasse wurde zu einem 16 Fuß großen Quadrat aus trocken verlegtem Buff-Flagstein, die Bäume wurden zu fünf American Pillar Arborvitae in einer Reihe, und der Garten verschwand.
- **A3.** Der Feuerkreis wurde in die nordwestliche Ecke der Terrasse verlegt, der Kräutergarten wurde zu einem Stein-Beet, das von der Ziegelwand abgestellt ist, und das AC erhielt einen Screen. Der "Tür" für den Landungssteg, den ich gezeichnet hatte, stellte sich als ein Wohnzimmerfenster heraus.
- **A4.** Eine Treppe statt zwei, der Schieberegler wurde als der tatsächliche schräge Bucht gezeichnet, die Ecken der Plattform wurden in 45 Grad geschnitten, und ein Blackstone-Griddle und ein Rauchofen entlang der östlichen Leitstange.
- **A5.** Eine Steinsitzwand um den Feuerkreis, der Sessel-Set wurde auf die Terrasse verlegt, eine entlüftete Schürze unter der Plattform, und der AC-Screen öffnete sich auf seiner westlichen Seite. Der Eigentümer fragte, ob ein dreiseitiger fester Screen den Kühler beeinträchtigen würde. Es würde: Die Einheit zieht Luft durch ihre Seiten an und drückt sie durch den oberen Teil aus, und ein Kasten um sie herum führt ihr eigene Abgasung zu.

Jede Überarbeitung regenerierte das Modell, die Zeichnungen, die Mengen, das Budget und ein PDF und veröffentlichte die Seite erneut. Eine Änderung wie „Ecken abschneiden“ beeinflusste den Grundriss der Terrasse, die Träger, die Geländer, die Kanten, die Sockelleiste und den Steinbelag um die Terrasse, und nichts davon wurde von Hand neu gezeichnet.

Einige der Dinge, die die Prüfungen entlang des Weges erfassten: ein Feuerkorb, der nur als aufgelistetes tragbares Gerät in den Garten passte (der veröffentlichte Abstandscode für ein offenes Holzfeuer beträgt 25 Fuß; der Eigentümer hat ihre eigenen Abstände festgelegt, und der Plan dokumentiert beide), eine Terrasse, die nicht an der Mauer aus Ziegelsteinen hängen konnte (ein Ledger darf nicht an einer Verkleidung befestigt werden, also steht sie auf ihren eigenen beiden Trägern), und ein Terrassenbereich, der auf der niedrigen Seite höher als der Rasen stand, den jetzt die Sitzwand abhält.

## Das Modell so aussehen lassen wie ein Garten

Die ersten Renditebilder waren ehrlich und hässlich: Stufenweise Grasfliesen, Bäume, die wie Torten gestapelt waren, und Möbel als Kästen. Das CAD-Framework kannte nur Kästen und Zylinder, also lernte es vier weitere Formen: extrudierte Polygone (unregelmäßige Steinplatten, gekrümmte Sitzwände, Treppenlaufträger), eine Platte mit geneigter Oberseite (ein glatter Boden), Kegel (Bäume, Sonnenschirme) und ein Satteldach. Die Steinplatten stammen aus einem gestörten Gitter, das auf das Terrassenquadrat und den runden Abschlussbereich geschnitten wird, sodass keine zwei Steine sich überschneiden.

Dann Photoreal. Der erste Versuch war eine Einzelinstallation von Blender auf dem Rechner, der die Sitzung ausführte, was der falsche Ort dafür ist. Der bessere Ort ist die NanoClaw-Flotte, die bereits Jobarbeiter hinter einem kleinen Jobdienst ausführt. Also gibt es jetzt eine Renderebene:

- ein Aufrufer sendet ein JSON-Rezept (die Modell-URL und die Ansichten) an den Job-Service;
- eine NanoClaw-Agentengruppe, `jobs-render`, erwacht mit einer `blender-render` Fähigkeit, führt Blender headless aus und schreibt die Bilder in einen pro-Job-Artifact-Ordner;
- der Job-Service listet diese Dateien im Ergebnis auf und liefert sie an die Person, die den Job eingereicht hat.

Das Plan-Modul trägt sein eigenes Rendite-Rezept mit sich: welche Teile Ziegel, Schiefer, Verbundmaterial, Steinplatten, Wandstein, Gras oder Laub sind, drei Kamera-Ansichten, die Sonne (niedrig aus dem Nordwesten, sodass die nördlichen Seiten beleuchtet werden) und eine unendliche Grundebene, die dem Gelände folgt. Die Materialien sind prozedural, gefärbt durch die eigene Farbe jedes Teils, sodass keine Texturdateien mit dem Modell reisen.

![Der Hinterhof aus nördlicher Richtung, gerendert vom Render-Tier in Blender](/plans/backyard/model/cycles-north.png)

Korrekt, beleuchtet und immer noch offensichtlich ein Modell. Bessere Materialien hätten es nur zu einem besseren Modell gemacht, daher übergibt der letzte Schritt das Rendern einem Tool, das Fotos erstellt: FLUX.1 Kontext, ein Bildbearbeitungsmodell, das ein Bild plus eine Anweisung ("wandle diese 3D-Rendite in ein echtes Foto um; behalte jeden Gegenstand an seinem Platz") nimmt und die Oberflächen neu zeichnet, während die Anordnung und die Kamera erhalten bleiben.

Es läuft auf dem Intel B70 des Render-Hosts, der normalerweise das Sprachmodell der Flotte (vLLM) und Plex hostet. Die beiden können nicht gleichzeitig auf den Speicher der Grafikkarte zugreifen, also überlässt ein kleiner Arbitrierer sie zeitweise. Fotoanfragen warten in der Warteschlange; wenn vLLM eine Minute lang inaktiv war und nichts anderes auf der Grafikkarte läuft, stoppt es vLLM, startet ComfyUI mit Kontext, führt die gesamte Warteschlange aus und übergibt die Grafikkarte dann zurück. Anfragen an das Sprachmodell während eines Wechsels warten stattdessen an seinem Proxy, anstatt zu scheitern. Ein Foto benötigt etwa 55 Sekunden, der Wechsel zurück etwa eine Minute, und der Render-Worker fragt einfach für jedes Bild einer Ansicht nach einem Foto und wartet.

![Die gleiche Ansicht als Fotografie](/plans/backyard/model/photo-north.png)

![Aus der nordöstlichen Richtung](/plans/backyard/model/photo-ne.png)

![Aus der westlichen Richtung](/plans/backyard/model/photo-west.png)

Das Deck, die abgerundeten Ecken, der Feuerkreis und die Sitzwand, der gesicherte Lüftungskanal und die fünf Säulen sind an den Stellen, an denen sie im Plan vorgesehen sind. Die Wälder und Felder jenseits der Zaun sind die Erfindung des Modells.

## Was nicht funktioniert hat

- **Das lokale Modell konnte es nicht antreiben.** Das kostenlose Tier von qwen3-14b, hinter seinem Proxy, scheiterte beim ersten Tool-Call-Schritt ("Content block is not a text block"). Einfache Textaufgaben funktionieren; eine Aufgabe, die eine Datei schreiben und einen Befehl ausführen muss, funktioniert noch nicht. Der Render-Worker läuft stattdessen auf Sonnet, begrenzt auf 30 Aufgaben pro Tag, da jede Aufgabe nur drei Tool-Aufrufe erfordert.
- **Blender kann die GPU nicht erreichen.** NanoClaw's Container-Runner hat keine Gerätewechselung, also läuft der Blender-Schritt auf dem CPU (etwa 35 Sekunden pro Ansicht bei 128 Proben). Der Foto-Schritt erhält die GPU, weil der Arbitrierer außerhalb von NanoClaw, auf dem Host, läuft.
- **Die offizielle Blender-Download-Quelle ist hinter einem Bot-Check gesichert.** Ein Universitäts-Spiegel bietet das gleiche Archiv an.

## Was weitergeführt wird

Der nächste physische Plan erhält photo-stilisierte Ansichten zum Preis eines `RENDER` Blocks in seinem Modul und eine Aufgabe mit `"photo": true`. Die Render-Ebene weiß nichts über Hinterhöfe; sie nimmt jedes GLB und ein Rezept entgegen. Und die Lektion aus den Revisionen ist dieselbe wie bei der Garage und dem Spulenschrank: wenn die Zeichnungen, das Modell, die Prüfungen und die Einkaufsliste alle aus denselben Zahlen stammen, kann der Eigentümer fünfmal am Tag seine Meinung ändern und der Plan bleibt dabei.

Das Zeichnungsset ist unter [/plans/backyard/](/plans/backyard/) und die Projektseite unter [/projects/backyard](/projects/backyard).
