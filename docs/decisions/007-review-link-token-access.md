# ADR 007: Fragmentbasierter Token-Bootstrap für die Review-App

## Status

**Angenommen**

## Kontext

Die mobile Review-App benötigt für den MVP einen dauerhaft nutzbaren Zugang,
der ohne klassisches Login auf mehreren Geräten verwendet werden kann. Der
Review-Link selbst dient als Zugriffsschlüssel, darf aber weder nur durch seine
Länge geschützt noch als Klartext-Geheimnis in PostgreSQL abgelegt werden.

Ein geheimer Token im HTTP-Pfad nach dem bisherigen Prinzip `/r/{token}` oder
in einem Query-Parameter kann bereits vor der Anwendung in Request-Logs von
Hosting-Provider, Edge, Reverse Proxy oder ASGI-Server erscheinen. Eine
Redaktion innerhalb der FastAPI-Anwendung kann dieses vorgelagerte Risiko nicht
zuverlässig beseitigen.

Die bestehende Review-Domäne bleibt fachlich führend. Das Zugriffsmodell muss
deshalb eine stabile serverseitige Review-Identität bereitstellen, ohne eine
User-, Passwort-, Rollen- oder OAuth-Architektur einzuführen.

## Entscheidung

Der dauerhaft nutzbare geheime Review-Link verwendet den Token ausschließlich
im URL-Fragment:

```text
https://<review-host>/#<token>
```

Der Hostname bleibt offen. Der Fragmentteil nach `#` wird vom Browser nicht als
Bestandteil des HTTP-Requests an Server, Reverse Proxy oder Hosting-Edge
übertragen. Ein Token im Pfad oder Query-Parameter ist für den Review-Zugriff
nicht zulässig.

Der vollständige Token wird mit einer kryptografisch sicheren Zufallsquelle
erzeugt, ist ausreichend lang und praktisch nicht erratbar. PostgreSQL
speichert ausschließlich den SHA-256-Hash des vollständigen Tokens, niemals
den Klartext-Token. Tokenwerte dürfen weder im Klartext protokolliert noch in
Fehlermeldungen gespiegelt werden.

### Bootstrap

Beim erstmaligen Öffnen läuft der Zugriff wie folgt ab:

1. Der Browser lädt eine öffentliche Bootstrap-Seite ohne Token im HTTP-Request.
2. Minimales lokales JavaScript liest den Token aus `window.location.hash`.
3. Das JavaScript sendet den Token ausschließlich im Body eines HTTPS-Requests
   an `POST /review/access`. Request-Bodies mit Zugangstokens dürfen nicht
   protokolliert werden.
4. Der Server bildet den SHA-256-Hash über den vollständigen Token, sucht den
   passenden Review-Link-Datensatz und verlangt `revoked_at IS NULL`.
5. Nach erfolgreicher Prüfung erzeugt der Server einen manipulationssicheren
   Review-Zugriffskontext. Das Fragment wird mit Browser-Navigation
   beziehungsweise `history.replaceState` aus der sichtbaren URL entfernt.
6. Die weitere Navigation erfolgt tokenfrei über Routen wie `GET /review` und
   `POST /review/decision`.

Ungültige oder widerrufene Tokens erzeugen keinen Zugriffskontext. Der Token
wird weder in Antworten noch in Fehlern oder Redirect-Zielen gespiegelt.

### Cookie-basierter Zugriffskontext

Für den MVP wird ein kryptografisch signierter, serverseitig verifizierter
Cookie verwendet. Der Cookie darf die nicht geheime `review_link.id` und die
für Versionierung beziehungsweise Gültigkeitsprüfung nötigen Metadaten
enthalten, aber niemals den Review-Token. Eine ungeschützte `review_link.id`
allein gilt nicht als vertrauenswürdiger Zugriffsnachweis.

Die Signatur verwendet ein ausreichend starkes, ausschließlich als
Environment Secret bereitgestelltes Geheimnis, beispielsweise
`REVIEW_COOKIE_SIGNING_SECRET`. Dieses Secret wird weder im Repository
gespeichert noch protokolliert.

Der Cookie wird mindestens mit folgenden Eigenschaften gesetzt:

- `HttpOnly`,
- `Secure` im öffentlichen HTTPS-Betrieb,
- `SameSite=Strict`, solange der beschlossene Bootstrap-Fluss dadurch nicht
  beeinträchtigt wird,
- Host-only ohne unnötiges `Domain`-Attribut,
- auf die Review-Routen begrenzter `Path`.

Bei jedem fachlichen Review-Request prüft der Server die Cookie-Signatur und
lädt den referenzierten Review-Link-Datensatz erneut mit `revoked_at IS NULL`.
Damit beendet der Widerruf des zugrundeliegenden Review-Links auch bestehende
Cookie-Kontexte. Ein separates persistiertes Sessionmodell ist für den MVP
nicht erforderlich.

### Identität und CSRF

Jeder Review-Link besitzt einen stabilen internen Datensatz mit eigener UUID.
Diese UUID ist nicht geheim. Nach erfolgreicher Signatur- und
Widerrufsprüfung wird die menschliche Benutzerreferenz ausschließlich
serverseitig daraus abgeleitet:

```text
decided_by_user_ref = "review_link:<token_record_id>"
```

Der Browser darf `decided_by_user_ref` weder in Formularen noch über Query,
Header oder Cookie frei bestimmen. Der Human Review Decision Service erhält
ausschließlich die serverseitig erzeugte Referenz.

Für zustandsändernde Browser-Requests kombiniert der MVP `SameSite=Strict` mit
einer exakten serverseitigen `Origin`-Prüfung gegen den konfigurierten
kanonischen HTTPS-Review-Origin. Fehlende oder abweichende Origin-Angaben werden
bei diesen Requests abgelehnt. Diese Kombination ist für den dedizierten
same-origin MVP ohne zusätzliches CSRF-Token vorgesehen. Falls später
Cross-Site-Nutzung erforderlich wird, muss die Entscheidung neu bewertet und
gegebenenfalls ein eigener CSRF-Token ergänzt werden.

### Persistenz und Multi-Device

Die bestehende minimale Persistenz eines Review-Link-Datensatzes bleibt:

- `id` als UUID,
- `token_hash` als eindeutiger SHA-256-Hash des vollständigen Tokens,
- `created_at`,
- `revoked_at` als nullable Widerrufszeitpunkt.

Der signierte Cookie benötigt keine zusätzliche Datenbanktabelle. Migration
008 bleibt unverändert ausreichend.

Ein oder mehrere aktive Review-Link-Datensätze sind technisch zulässig;
praktisch wird zunächst ein persönlicher aktiver Link verwendet. Derselbe
ursprüngliche `#token`-Link darf auf mehreren Geräten verwendet werden. Jedes
Gerät erzeugt daraus seinen eigenen sicheren Cookie-Kontext, alle Kontexte
repräsentieren jedoch dieselbe Review-Identität
`review_link:<token_record_id>`.

PostgreSQL bleibt die zentrale fachliche Wahrheit. Der Zugriffskontext selbst
löst keine Parallelitätsprobleme. Vor jeder Entscheidung muss der aktuelle
Datenbankzustand serverseitig geprüft werden. Bereits entschiedene oder
veraltete Session-Items dürfen nicht still doppelt bewertet werden. Bei einem
Konflikt wird kontrolliert das nächste aktuelle Produkt geladen.

## Konsequenzen

- Der geheime Review-Token erscheint weder im HTTP-Pfad noch im Querystring und
  damit nicht in den üblichen Provider-, Edge-, Proxy- oder Uvicorn-Pfadlogs.
- Der Klartext-Token existiert nach dem Bootstrap nicht in der normalen
  Review-Navigation.
- Der serverseitig verifizierte Cookie ist Zugriffsnachweis, aber nicht die
  fachliche Identität; diese bleibt die aktive Review-Link-UUID.
- Ein kompromittierter Link wird durch Setzen von `revoked_at` deaktiviert und
  kann durch einen neuen Link ersetzt werden.
- Für den MVP sind keine User-Tabelle, Passwörter, Login-Maske,
  Rollenverwaltung, OAuth oder persistierte Login-Sessions erforderlich.
- Die bestehende Eligibility-, Session- und Decision-Logik bleibt unverändert
  die fachliche Quelle der Review-App.

## Verworfene beziehungsweise nicht gewählte Alternativen

- Geheimer Token im Pfad nach dem Prinzip `/r/{token}`.
- Geheimer Token als Query-Parameter.
- Speicherung des Klartext-Tokens in PostgreSQL.
- Protokollierung von Bootstrap-Request-Bodies oder Tokenwerten.
- Unsignierte `review_link.id` als vertrauenswürdiger Cookie.
- Serverseitig persistierte Zugriffssessions für den MVP, da der signierte
  Cookie mit erneuter Widerrufsprüfung ausreicht.
- Frei vom Browser übermitteltes `decided_by_user_ref`.
- Klassisches Benutzerkonto mit Passwort, OAuth oder Rollenverwaltung für den
  ersten MVP.
- Ausschließlich lokaler Browserzustand als fachliche Wahrheit.
