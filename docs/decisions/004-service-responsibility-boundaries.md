# ADR 004: Fachliche Servicegrenzen und Verantwortlichkeiten

## Status

**Angenommen**

## Kontext

Solvory umfasst mehrere fachlich unterschiedliche Aufgaben. Ohne klare Grenzen können Services fremde Fachzustände verändern oder Fachlogik kann unkontrolliert in Benutzeroberflächen, Datenbankmechanismen oder Orchestrierung verteilt werden.

## Entscheidung

Solvory verwendet fachliche Services als verbindliche Bezeichnung für abgegrenzte Verantwortlichkeiten. Ein fachlicher Service ist keine automatisch getrennt deployte technische Komponente. Mehrere Services dürfen innerhalb derselben Anwendung oder Laufzeitkomponente umgesetzt werden.

Orchestrierung koordiniert Serviceaufrufe, enthält aber nicht die zentrale Fachlogik. Benutzeroberflächen stellen Daten dar und erfassen Benutzerhandlungen, sind aber nicht führend für Fachregeln.

## Konsequenzen

- Verantwortlichkeiten werden eindeutig.
- Fachlogik bleibt testbar und versionierbar.
- Eine spätere technische Aufteilung bleibt möglich.
- Servicegrenzen müssen im Code konsequent eingehalten werden.
- Die technische Berechtigungsmatrix ist noch zu erstellen.

## Verworfene beziehungsweise nicht gewählte Alternativen

- Verpflichtende Microservice-Architektur.
- Eine zentrale Anwendung ohne fachliche Modulgrenzen.
- Fachlogik primär in n8n.
- Fachlogik primär in der mobilen Web-App.
