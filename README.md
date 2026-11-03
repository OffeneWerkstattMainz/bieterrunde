# OWM Vereinsportal

Das OWM Vereinsportal ist ein Django-Backend für vereinsrelevante Aufgaben der
[Offenen Werkstatt Mainz e.V.](https://offenewerkstattmainz.de).
Jede Aufgabe ist eine eigene Django-App:

| App      | Pfad            | Zweck                                                   |
|----------|-----------------|---------------------------------------------------------|
| `core`   | `/`             | Startseite, gemeinsames Layout, statische Dateien       |
| `voting` | `/bieterrunde/` | Interaktive Bieterrunde (siehe unten)                   |
| `signup` | `/anmeldung/`   | Double-Opt-In für das Webling-Anmeldeformular (s. u.)   |

Das Django-Projektpaket (Settings, URLs, WSGI) liegt in `owm_portal/`.

# Mitgliedsanmeldung (Double-Opt-In)

Das Webling-WordPress-Plugin legt neue Mitglieder sofort in Webling an und kann kein
Double-Opt-In. Die App `signup` ergänzt das:

1. Das Anmeldeformular des Plugins trägt neue Mitglieder in die Webling-Gruppe
   `SIGNUP_PENDING_GROUP_ID` ein.
2. Die Task `signup.tasks.process_signups` prüft diese Gruppe alle `SIGNUP_INTERVAL` Sekunden
   (Standard 120) und schickt neuen Einträgen eine Mail mit Bestätigungslink. Eingeplant wird sie
   vom RQ-Cron-Scheduler (`manage.py rqcron owm_portal.cron`, Container `cron`), ausgeführt vom
   normalen `worker`. Pro E-Mail-Adresse wird nur der
   älteste Eintrag angeschrieben.
3. Der Link führt auf `/anmeldung/bestaetigen/<token>/`. Erst der Klick auf „Anmeldung
   bestätigen“ (POST) verschiebt das Mitglied in die Gruppe `SIGNUP_CONFIRMED_GROUP_ID` und
   meldet die Anmeldung an `SIGNUP_NOTIFY_EMAILS`. So bestätigen Mailscanner, die Links vorab
   öffnen, nichts versehentlich.
4. Unbestätigte Einträge bekommen nach `SIGNUP_REMINDER_DAYS` (3) Tagen eine Erinnerung und werden
   nach `SIGNUP_EXPIRY_DAYS` (14) Tagen in Webling gelöscht.

Ob eine Anmeldung bestätigt ist, ergibt sich aus der Gruppe. Die Fristen zählen ab dem
Anlagezeitpunkt des Mitglieds (`meta.created` der Webling-API), zusätzliche Webling-Felder sind
nicht nötig. Das Portal merkt sich nur, welche Mails schon verschickt wurden (Model
`PendingSignup`, ohne personenbezogene Daten). Der `WEBLING_API_KEY` braucht Schreibrecht auf
beide Gruppen.

| Variable                    | Bedeutung                                                         |
|-----------------------------|-------------------------------------------------------------------|
| `SIGNUP_PENDING_GROUP_ID`   | Webling-Gruppe des Anmeldeformulars (unbestätigt)                 |
| `SIGNUP_CONFIRMED_GROUP_ID` | Webling-Gruppe für bestätigte Anmeldungen                         |
| `SIGNUP_BASE_URL`           | Öffentliche URL des Portals für die Links, z. B. `https://portal.ow-mainz.de` |
| `SIGNUP_NOTIFY_EMAILS`      | Empfänger der Meldung über bestätigte Anmeldungen, durch Komma getrennt |
| `SIGNUP_INTERVAL`           | Sekunden zwischen zwei Abfragen, Standard 120 (Container `cron`)   |
| `SIGNUP_REMINDER_DAYS`      | Tage bis zur Erinnerung, Standard 3                               |
| `SIGNUP_EXPIRY_DAYS`        | Tage bis zur Löschung, Standard 14                                |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` | Mailversand (StartTLS) |

# Bieterrunde

## Was ist das?

Die App `voting` dient zum interaktiven Abhalten von [Bieterrunden](https://www.solidarische-landwirtschaft.org/fileadmin/media/solidarische-landwirtschaft.org/Solawis-aufbauen/Vorlagen-Dokumente/Netzwerk-Solawi-Bieterrunde.pdf).
Hier wurde die Variante "mit Richtwert" umgesetzt.


## Warum?

Die [Offenen Werkstatt Mainz e.V.](https://offenewerkstattmainz.de) verwendet Bieterrunden um auf solidarische weise Mitgliedsbeiträge festzulegen.
Auf vergangenen Mitgliederversammlungen wurde dies mit Zettel und Stift durchgeführt und anschließend manuell ausgewertet.

Da dieser Prozess sehr Zeitaufwendig ist, entstand die Idee ein Tool zu entwickeln, welches diesen Prozess vereinfacht und beschleunigt.

## Wie funktioniert es?

TBD

## Dev Setup

Das Projekt nutzt [mise](https://mise.jdx.dev) als dependency manager.
Ein development setup kann mit den folgenden Befehlen aufgesetzt werden:

```bash
mise install
uv sync
```

## Upgrade von der alten „bieterrunde“-Installation

Mit dem Umbau zum OWM Vereinsportal haben sich geändert:

- Docker-Image: `ghcr.io/offenewerkstattmainz/owm-portal` (Variable `OWM_PORTAL_IMAGE`
  statt `BIETERRUNDE_IMAGE`)
- Datenbankname: `owm_portal` statt `bieterrunde` (überschreibbar per `DB_NAME`)
- Die Bieterrunde liegt jetzt unter `/bieterrunde/`. Alte Links werden dauerhaft weitergeleitet.

Die bestehende Datenbank muss einmalig umbenannt werden, bevor das neue Image startet:

```bash
docker compose stop web worker
docker compose exec db psql -U postgres -c 'ALTER DATABASE bieterrunde RENAME TO owm_portal;'
docker compose up -d
```
