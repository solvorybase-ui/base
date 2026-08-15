# ADR 003: Menschliche Produktentscheidung

## Status

**Angenommen**

## Kontext

Product Scout und Product Evaluator unterstützen die Auswahl, sollen aber nicht die endgültige redaktionelle Entscheidung übernehmen.

## Entscheidung

Die endgültige Produktentscheidung wird ausschließlich durch den Nutzer getroffen. Zulässige Entscheidungen sind `HIT`, `NO HIT` und `SPÄTER`.

Mindestens gespeichert werden Produkt, Entscheidung, Zeitpunkt und entscheidender Benutzer.

- **HIT:** Startet über die Orchestrierung Affiliate Enrichment und Content Creation parallel.
- **NO HIT:** Sperrt dauerhaft den regulären Auswahlprozess. Es gibt keinen automatischen Wiederaufnahmeprozess. Eine Begründung ist nicht erforderlich.
- **SPÄTER:** Erzeugt keine zeitbasierte Wiedervorlage. Eine erneute Review erfolgt nur bei relevanter Produktänderung.

Der Product Evaluator wird im MVP nur auf ausdrückliche Nutzeranforderung ausgeführt und nicht dauerhaft operativ gespeichert.

## Konsequenzen

- Redaktionelle Verantwortung bleibt menschlich.
- NO-HIT-Produkte kehren nicht automatisch zurück.
- SPÄTER erfordert eine Änderungsdetektion.
- Menschliche Review bleibt notwendig.

## Verworfene beziehungsweise nicht gewählte Alternativen

- Vollautomatische HIT-Entscheidung.
- Automatische NO-HIT-Wiederaufnahme.
- Zeitbasierte SPÄTER-Wiedervorlage.
- Automatischer Evaluator für jedes Produkt.
- Verpflichtende NO-HIT-Begründung.
