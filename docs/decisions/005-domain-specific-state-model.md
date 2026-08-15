# ADR 005: Domänenspezifisches Zustandsmodell

## Status

**Angenommen**

## Kontext

Ein Produkt durchläuft mehrere unabhängige Prozesse, die parallel oder zeitversetzt ablaufen können. Ein einzelner globaler Produktstatus könnte nicht korrekt ausdrücken, dass ein Produkt gleichzeitig HIT, im Affiliate Enrichment ausstehend, im Content-Prozess fertig und im Publishing blockiert ist.

## Entscheidung

Solvory verwendet kein einzelnes globales Produktstatusfeld. Jede Domäne führt ihren eigenen Zustand:

- Import in `import_runs`,
- Scout in `scout_results`,
- menschliche Entscheidung in `reviews`,
- Affiliate in `affiliate_links`,
- Content in `content_assets`,
- Publishing in `publications`,
- technische Ausführung in `automation_runs`.

Die Produktentität speichert die fachliche Produktidentität, nicht den zusammengefassten Zustand aller Prozesse.

## Konsequenzen

- Parallele Prozesse können korrekt dargestellt werden.
- Zustände besitzen klare fachliche Eigentümer.
- Abfragen zum Gesamtzustand müssen mehrere Domänen berücksichtigen.
- Benutzeroberflächen benötigen eine zusammengesetzte Darstellung.
- Inkonsistente Kombinationen müssen durch Regeln und Tests verhindert werden.

## Verworfene beziehungsweise nicht gewählte Alternativen

- Ein globaler Produktstatus.
- Globaler Status plus zusätzliche Domänenstatus.
- Zustandsführung ausschließlich in der Orchestrierung.
- Zustandsableitung ausschließlich aus technischen Logs.
