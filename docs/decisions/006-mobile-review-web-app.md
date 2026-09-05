# ADR 006: Mobile Review-Web-App im bestehenden Python-Backend

## Status

**Angenommen**

## Kontext

Für den ersten Human-Review-Schritt benötigt Solvory eine schlanke, mobil gut
nutzbare Oberfläche. Review Candidate Eligibility, Review Session Builder und
Human Review Decision Service bestehen bereits als fachliche Backend-Logik.

Eine separate Single-Page-Anwendung oder zusätzliche Laufzeitkomponente würde
für diesen MVP unnötige Frontend- und Betriebs-Komplexität erzeugen. Die
Benutzeroberfläche darf außerdem keine Review-Regeln duplizieren oder selbst
zur fachlich führenden Instanz werden.

## Entscheidung

Die erste Review-App wird als mobile-first Web-Anwendung mit FastAPI und
serverseitig gerendertem HTML im bestehenden Python-Backend umgesetzt.

Für den MVP gelten folgende technische Grenzen:

- kein React,
- kein Next.js,
- keine separate SPA,
- keine neue Microservice-Architektur,
- keine eigene globale Produktstatus-Logik.

Die Web-Oberfläche ist ausschließlich Darstellungsschicht. HTTP-Routen und
Templates verwenden die bestehenden Review-Backend-Services und enthalten
keine parallele Eligibility- oder Decision-Logik. Templates und Routen führen
keine direkten SQL-Schreiboperationen aus.

Eine Review-Session enthält standardmäßig 20 Produkte. Die Oberfläche zeigt
jeweils ein Produkt mit den vorhandenen Produkt-, Scout-, Bild-, Angebots- und
Shopinformationen sowie den Fortschritt innerhalb der Session. Sie bietet die
großen mobilen Aktionen HIT, NO HIT und SPÄTER und wechselt nach erfolgreicher
Entscheidung zum nächsten Produkt.

Die endgültige Entscheidung bleibt ausschließlich menschlich. Der Product
Scout entscheidet niemals HIT, NO HIT oder SPÄTER. Der Product Evaluator und
administrative NO-HIT-Overrides sind nicht Bestandteil dieser ersten
Review-Oberfläche.

## Konsequenzen

- Die erste Review-Oberfläche bleibt klein und mobile-first.
- Fachregeln verbleiben in der bestehenden Review-Domäne und bleiben unabhängig
  von der Darstellung testbar.
- Das bestehende Python-Backend ist zugleich technische Laufzeit der ersten
  Review-Web-App; es entsteht kein zusätzlicher Service.
- Serverseitiges HTML reduziert Frontend-Abhängigkeiten und kann später ersetzt
  werden, ohne die fachlichen Review-Services zu ersetzen.
- Authentifizierung, Hosting und konkrete Gestaltung werden separat entschieden
  beziehungsweise umgesetzt.

## Verworfene beziehungsweise nicht gewählte Alternativen

- React für den ersten MVP.
- Next.js für den ersten MVP.
- Separate Single-Page-Anwendung.
- Eigener Review-Microservice.
- Fachliche Review-Logik in Templates oder HTTP-Routen.
- Automatisierte HIT-, NO-HIT- oder SPÄTER-Entscheidungen.
