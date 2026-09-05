# ADR 007: Tokenbasierter Zugriff auf die Review-App

## Status

**Angenommen**

## Kontext

Die mobile Review-App benötigt für den MVP einen dauerhaft nutzbaren Zugang,
der ohne klassisches Login auf mehreren Geräten verwendet werden kann. Der
Review-Link selbst dient als Zugriffsschlüssel, darf aber weder nur durch seine
Länge geschützt noch als Klartext-Geheimnis in PostgreSQL abgelegt werden.

Die bestehende Review-Domäne bleibt fachlich führend. Das Zugriffsmodell muss
deshalb eine stabile serverseitige Review-Identität bereitstellen, ohne eine
User-, Passwort-, Rollen- oder OAuth-Architektur einzuführen.

## Entscheidung

Der Zugriff erfolgt über einen dauerhaft nutzbaren Review-Link nach folgendem
Prinzip:

```text
https://<host>/r/<token>
```

Der Hostname bleibt offen. Der vollständige Token wird mit einer
kryptografisch sicheren Zufallsquelle erzeugt, ist ausreichend lang und
praktisch nicht erratbar. Sein Klartext steht ausschließlich im Link
beziehungsweise im Request.

PostgreSQL speichert ausschließlich den SHA-256-Hash des vollständigen Tokens,
niemals den Klartext-Token. Tokenwerte dürfen weder im Klartext protokolliert
noch in Fehlermeldungen gespiegelt werden. Bei jedem Zugriff wird der im
Request enthaltene Token serverseitig gehasht und gegen einen aktiven,
nicht widerrufenen Review-Link-Datensatz geprüft. Eine lange URL ohne diese
serverseitige Prüfung gewährt keinen Zugriff.

Jeder Review-Link besitzt einen stabilen internen Datensatz mit eigener UUID.
Diese UUID ist nicht geheim. Die menschliche Benutzerreferenz wird
ausschließlich serverseitig daraus abgeleitet:

```text
decided_by_user_ref = "review_link:<token_record_id>"
```

Der Browser darf `decided_by_user_ref` nicht frei bestimmen oder mitsenden.
Der Human Review Decision Service erhält ausschließlich die serverseitig
erzeugte Referenz.

Für den MVP umfasst die minimale Persistenz eines Review-Link-Datensatzes:

- `id` als UUID,
- `token_hash` als Hash des vollständigen Tokens,
- `created_at`,
- `revoked_at` als nullable Widerrufszeitpunkt.

`token_hash` muss einen Review-Link eindeutig identifizieren. `updated_at` ist
für das beschlossene MVP-Verhalten nicht zwingend erforderlich. Weitere
Benutzer-, Rollen- oder Sitzungsfelder sind nicht erforderlich.

Ein oder mehrere aktive Review-Link-Datensätze sind technisch zulässig;
praktisch wird zunächst ein persönlicher aktiver Link verwendet. Ein Link wird
durch Setzen von `revoked_at` widerrufen. Ein widerrufener Token gewährt keinen
Zugriff mehr. Er kann später durch einen neuen, eigenständigen Link-Datensatz
ersetzt werden, ohne den alten Datensatz oder dessen historische Referenz zu
löschen.

Das Routing-Ziel lautet:

```text
GET /r/{token}
```

Der Server hasht den Token, sucht den aktiven passenden Review-Link-Datensatz
und verweigert bei ungültigem oder widerrufenem Token den Zugriff. Bei einem
gültigen Token lädt er den kontinuierlichen Review-Fluss. Spätere
Decision-POSTs laufen im selben tokenbasierten Kontext und verwenden die
serverseitig abgeleitete Benutzerreferenz.

Derselbe gültige Token darf auf mehreren Geräten verwendet werden. Alle Geräte
repräsentieren im MVP dieselbe Review-Identität; PostgreSQL bleibt die zentrale
fachliche Wahrheit. Der Token selbst löst keine Parallelitätsprobleme. Vor
jeder Entscheidung muss der aktuelle Datenbankzustand serverseitig geprüft
werden. Bereits entschiedene oder veraltete Session-Items dürfen nicht still
doppelt bewertet werden. Bei einem Konflikt wird kontrolliert das nächste
aktuelle Produkt geladen.

## Konsequenzen

- Für den MVP sind keine User-Tabelle, Passwörter, Login-Maske,
  Rollenverwaltung, OAuth oder Session-Cookies als fachliche Identität nötig.
- Ein kompromittierter Link kann durch Widerruf des zugehörigen Datensatzes
  deaktiviert und durch einen neuen Link ersetzt werden.
- Geräteübergreifende Entscheidungen besitzen dieselbe stabile,
  serverseitig abgeleitete Review-Identität.
- Die spätere Implementierung benötigt eine Schemaänderung, Token-Erzeugung,
  Hashvergleich und eine sichere Protokollierungsgrenze; diese sind nicht
  Bestandteil dieser Dokumentationsentscheidung.
- Die bestehende Eligibility-, Session- und Decision-Logik bleibt unverändert
  die fachliche Quelle der Review-App.

## Verworfene beziehungsweise nicht gewählte Alternativen

- Speicherung des Klartext-Tokens in PostgreSQL.
- Ungeprüfte lange URL als alleiniger Zugriffsschutz.
- Frei vom Browser übermitteltes `decided_by_user_ref`.
- Klassisches Benutzerkonto mit Passwort für den ersten MVP.
- OAuth oder Rollenverwaltung für den ersten MVP.
- Session-Cookies als fachliche Review-Identität.
- Ausschließlich lokaler Browserzustand als fachliche Wahrheit.
