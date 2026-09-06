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
erratbaren Link mit kryptografisch zufälligem Zugriffstoken im URL-Fragment
nach dem Prinzip `https://<review-host>/#<token>`. Ein klassischer Login ist
für diesen MVP nicht vorgesehen. Der Fragment-Token wird nicht im HTTP-Pfad
oder Querystring übertragen. Eine öffentliche Bootstrap-Seite liest ihn lokal
im Browser aus und sendet ihn ausschließlich im Body eines HTTPS-Requests zur
serverseitigen Prüfung. Nach erfolgreicher Prüfung wird das Fragment entfernt
und die weitere Review-Navigation erfolgt über tokenfreie URLs.

Der Server richtet dafür einen kryptografisch signierten, serverseitig
verifizierten Cookie-Kontext ein. Dieser enthält niemals den Review-Token und
ist mit `HttpOnly`, `Secure` im öffentlichen HTTPS-Betrieb und
`SameSite=Strict` geschützt. Die zugrundeliegende Review-Link-UUID und ihr
Widerrufsstatus werden bei fachlichen Requests serverseitig erneut geprüft.
Zustandsändernde Requests erfordern zusätzlich eine exakte Origin-Prüfung.
Details des Zugriffs- und CSRF-Modells legt ADR 007 fest.

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

Der gleiche gültige Fragment-Link kann auf mehreren Geräten verwendet werden.
Jedes Gerät erhält nach erfolgreichem Bootstrap einen eigenen sicheren
Cookie-Kontext, der dieselbe serverseitige Review-Identität repräsentiert.
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
- Hostname, Hosting und Gestaltung werden separat entschieden beziehungsweise
  umgesetzt; Token-Bootstrap und Zugriffskontext sind in ADR 007 festgelegt.
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
- Geheimer Token im HTTP-Pfad oder Querystring.
- Fachliche Review-Logik in Templates oder HTTP-Routen.
- Automatisierte HIT-, NO-HIT- oder SPÄTER-Entscheidungen.
