# ADR 001: Zentrale PostgreSQL-Datenbank

## Status

**Angenommen**

## Kontext

Die frühere dateibasierte JSON-Pipeline diente als Prototyp. Mit zunehmender Anzahl von Produkten, Importläufen, Reviews, Affiliate-Angeboten, Content-Assets, Veröffentlichungen und Performance-Daten entstehen Anforderungen an konsistente Beziehungen, parallele Verarbeitung, Transaktionen, zentrale Datenverantwortung und historische Nachvollziehbarkeit.

## Entscheidung

Solvory verwendet PostgreSQL als zentrale operative Datenbank. Supabase stellt im aktuellen Zielbild die gehostete PostgreSQL-Umgebung bereit. Die Kernanwendung soll fachlich mit PostgreSQL arbeiten. Supabase-spezifische Logik wird auf begründete Anwendungsfälle begrenzt. Die offizielle Datenbankstruktur wird durch versionierte SQL-Migrationen im GitHub-Repository verwaltet.

## Konsequenzen

- Zentrale Quelle für operative Daten.
- Konsistente Beziehungen und bessere Analysefähigkeit.
- Schemaänderungen werden reproduzierbar.
- Migration, Berechtigungen, Backups und Umgebungen müssen definiert werden.
- Die bestehende Supabase-Struktur darf nicht ungeprüft übernommen werden.

## Verworfene beziehungsweise nicht gewählte Alternativen

- Dauerhafte JSON-Dateien als operative Datenbank.
- ChatGPT-Projektchats als operative Datenhaltung.
- Supabase-spezifische Plattformlogik als Kernarchitektur.
- Sofortiger Wechsel auf eine andere Datenbanktechnologie.
