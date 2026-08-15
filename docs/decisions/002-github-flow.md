# ADR 002: GitHub-Flow und versionierte Projektänderungen

## Status

**Angenommen**

## Kontext

Solvory benötigt einen nachvollziehbaren Änderungsprozess für Quellcode, Dokumentation, ADRs, Datenbankmigrationen, Prompts, Tests und Automatisierungsdefinitionen.

## Entscheidung

GitHub ist die zentrale technische Quelle. `main` ist der stabile Branch. Größere Änderungen erhalten einen verständlich benannten Feature-Branch, kleine nachvollziehbare Commits und einen Pull Request vor dem Merge. Ein zusätzlicher `develop`-Branch wird derzeit nicht eingeführt.

Für größere Änderungen gilt:

> Idee → Diskussion → Entscheidung → Dokumentation → Implementierung → Test → Merge

## Konsequenzen

- Änderungen bleiben nachvollziehbar.
- Architekturentscheidungen und Implementierungen können verbunden werden.
- Pull Requests ermöglichen Prüfung.
- Der formale Aufwand steigt.
- Direkte Änderungen an `main` sind zu vermeiden.

## Verworfene beziehungsweise nicht gewählte Alternativen

- Zusätzlicher `develop`-Branch.
- Direkte Implementierung auf `main`.
- Unversionierte Datenbankänderungen.
- Dokumentation außerhalb des Repositorys als alleinige Quelle.
