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

Der Nutzer öffnet die Review-App über einen dauerhaft nutzbaren, schwer
erratbaren Link mit kryptografisch zufälligem Zugriffstoken. Ein klassischer
Login ist für diesen MVP nicht vorgesehen. Der Link ist nur zusammen mit einer
serverseitigen Tokenprüfung gültig; eine lange, ungeprüfte URL genügt nicht.
Der Token darf nicht im Klartext protokolliert werden und soll später
widerrufbar beziehungsweise ersetzbar sein. Hostname sowie konkrete
Token-Persistenz und -Verwaltung werden mit dieser Entscheidung noch nicht
festgelegt.

Eine Review-Session enthält intern standardmäßig 20 Produkte. Session-ID und
Sessiongrenzen sind organisatorische Details und kein primärer Navigationsweg
für den Nutzer. Nach Öffnen des gültigen Review-Links zeigt die Oberfläche
automatisch das nächste noch nicht entschiedene Produkt mit den vorhandenen
Produkt-, Scout-, Bild-, Angebots- und Shopinformationen. Sie bietet die großen
mobilen Aktionen HIT, NO HIT und SPÄTER und wechselt nach erfolgreicher
Entscheidung unmittelbar zum nächsten offenen Produkt.

Angezeigt werden mindestens Produktname, Marke, Kategorie, Beschreibung,
Produktbilder, Scout-Begründung, Shop, Preis und Währung, Verfügbarkeit sowie
der Produktlink, soweit die jeweiligen Daten vorhanden sind.

Ist eine Session vollständig bearbeitet und sind weitere reviewfähige
Kandidaten vorhanden, wird die nächste Session automatisch beziehungsweise
nahtlos bereitgestellt. Solange Kandidaten vorhanden sind, kann der Nutzer den
Review-Fluss ohne Kenntnis oder manuellen Wechsel einer Session-ID fortsetzen.
Sind keine Kandidaten vorhanden, zeigt die App eine verständliche Leer- oder
Fertigansicht und erzeugt keine leere Session.

Der gleiche gültige Review-Link kann auf mehreren Geräten verwendet werden.
PostgreSQL bleibt die zentrale fachliche Wahrheit; lokaler Browserzustand ist
nicht maßgeblich. Entscheidungen werden bei jedem Request serverseitig gegen
den aktuellen Zustand validiert. Bereits entschiedene oder veraltete
Session-Items dürfen nicht still doppelt bewertet werden. Bei einem
Parallelitätskonflikt lädt die App kontrolliert das nächste aktuell offene
Produkt. Eine konkrete Locking-Architektur wird hiermit nicht festgelegt.

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
- Interne 20er-Sessions bleiben erhalten, unterbrechen aber nicht den
  kontinuierlichen Nutzerfluss.
- Mehrere Geräte teilen denselben serverseitigen Review-Zustand.
- Konkrete Token-Persistenz, Hostname, Hosting und Gestaltung werden separat
  entschieden beziehungsweise umgesetzt.
- HIT-Entscheidungen können später an Content-Erstellung, Posts und Assets,
  Veröffentlichung und Performance-Analyse angeschlossen werden. Diese
  Folgepipeline ist nicht Bestandteil des aktuellen UI-MVP.

## Verworfene beziehungsweise nicht gewählte Alternativen

- React für den ersten MVP.
- Next.js für den ersten MVP.
- Separate Single-Page-Anwendung.
- Eigener Review-Microservice.
- Session-ID-Navigation als primärer Nutzerfluss.
- Ausschließlich lokaler Browserzustand als fachliche Wahrheit.
- Ungeprüfte lange URL ohne serverseitige Tokenvalidierung.
- Fachliche Review-Logik in Templates oder HTTP-Routen.
- Automatisierte HIT-, NO-HIT- oder SPÄTER-Entscheidungen.
