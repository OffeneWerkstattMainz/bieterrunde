"""
Double-Opt-In für Mitgliedsanmeldungen über das Webling-WordPress-Plugin.

Das Plugin legt neue Mitglieder direkt in der Webling-Gruppe ``SIGNUP_PENDING_GROUP_ID`` an.
``process_pending()`` verschickt für diese Einträge Bestätigungslinks, erinnert und löscht
unbestätigte Einträge. Ob eine Anmeldung bestätigt ist, ergibt sich allein aus der Gruppe; die
Fristen zählen ab dem Anlagezeitpunkt in den Webling-Metadaten. Das Portal merkt sich nur, welche
Mails schon verschickt wurden (``PendingSignup``).
"""

from datetime import datetime, timedelta
from logging import getLogger

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core.webling_api import WeblingAPI
from signup.models import PendingSignup

log = getLogger(__name__)

PROP_EMAIL = "E-Mail"
PROP_FIRSTNAME = "Vorname"
PROP_LASTNAME = "Name"

TOKEN_SALT = "signup.confirm"


def pending_group_id() -> int:
    if not settings.SIGNUP_PENDING_GROUP_ID:
        raise ImproperlyConfigured("SIGNUP_PENDING_GROUP_ID ist nicht gesetzt")
    return settings.SIGNUP_PENDING_GROUP_ID


def confirmed_group_id() -> int:
    if not settings.SIGNUP_CONFIRMED_GROUP_ID:
        raise ImproperlyConfigured("SIGNUP_CONFIRMED_GROUP_ID ist nicht gesetzt")
    return settings.SIGNUP_CONFIRMED_GROUP_ID


def member_email(member: dict) -> str:
    return (member["properties"].get(PROP_EMAIL) or "").strip().lower()


def is_valid_email(email: str) -> bool:
    try:
        validate_email(email)
    except ValidationError:
        return False
    return True


def member_created(member: dict) -> datetime | None:
    """When the member was created in Webling (``meta.created``, local time)."""
    created = (member.get("meta") or {}).get("created")
    if not created:
        return None
    return timezone.make_aware(datetime.fromisoformat(created))


def make_token(member_id: int, email: str) -> str:
    return signing.dumps({"m": member_id, "e": email}, salt=TOKEN_SALT)


def read_token(token: str) -> tuple[int, str]:
    """Raises ``signing.SignatureExpired`` or ``signing.BadSignature``."""
    data = signing.loads(
        token, salt=TOKEN_SALT, max_age=timedelta(days=settings.SIGNUP_EXPIRY_DAYS + 1)
    )
    return data["m"], data["e"]


def confirm_url(member: dict) -> str:
    if not settings.SIGNUP_BASE_URL:
        raise ImproperlyConfigured("SIGNUP_BASE_URL ist nicht gesetzt")
    token = make_token(member["id"], member_email(member))
    return settings.SIGNUP_BASE_URL.rstrip("/") + reverse("signup:confirm", args=[token])


def send_confirmation_request(member: dict, created: datetime, reminder: bool = False) -> None:
    context = dict(
        firstname=(member["properties"].get(PROP_FIRSTNAME) or "").strip(),
        url=confirm_url(member),
        delete_on=created + timedelta(days=settings.SIGNUP_EXPIRY_DAYS),
        reminder=reminder,
    )
    subject = "Bitte bestätige deine Anmeldung bei der Offenen Werkstatt Mainz"
    if reminder:
        subject = f"Erinnerung: {subject}"
    send_mail(
        subject,
        render_to_string("signup/email/confirmation_request.txt", context),
        None,
        [member_email(member)],
    )


def notify_board(member: dict) -> None:
    if not settings.SIGNUP_NOTIFY_EMAILS:
        return
    props = member["properties"]
    fields = {
        name: ", ".join(value) if isinstance(value, list) else "Ja" if value is True else value
        for name, value in props.items()
        if value not in (None, "", [], False) and not isinstance(value, dict)
    }
    name = f"{props.get(PROP_FIRSTNAME) or ''} {props.get(PROP_LASTNAME) or ''}".strip()
    try:
        send_mail(
            f"Neue bestätigte Mitgliedsanmeldung: {name}",
            render_to_string("signup/email/board_notification.txt", dict(fields=fields)),
            None,
            settings.SIGNUP_NOTIFY_EMAILS,
        )
    except Exception:
        # The confirmation itself already happened in Webling, don't fail the request because of
        # the notification
        log.exception(f"Benachrichtigung über Anmeldung {member['id']} fehlgeschlagen")


def confirm_member(api: WeblingAPI, member: dict) -> None:
    parents = [group for group in member.get("parents", []) if group != pending_group_id()]
    api.update_member(member["id"], parents=[*parents, confirmed_group_id()])
    log.info(f"Anmeldung {member['id']} bestätigt")
    notify_board(member)


def process_pending(api: WeblingAPI, now: datetime | None = None) -> dict[str, int]:
    """
    Handle all members in the pending group, counting from their creation in Webling:

    - new entries get a confirmation request right away
    - after ``SIGNUP_REMINDER_DAYS`` they get one reminder
    - after ``SIGNUP_EXPIRY_DAYS`` they are deleted from Webling

    Per e-mail address only the oldest pending entry gets mails, newer duplicates and entries for
    addresses that are already confirmed silently expire.
    """
    now = now or timezone.now()
    stats = dict(requested=0, reminded=0, deleted=0, skipped=0)

    pending = api.fetch_members_by_group_id(pending_group_id())
    # Forget entries that were confirmed, deleted or moved by hand
    PendingSignup.objects.exclude(member_id__in=pending).delete()
    confirmed_emails = {
        member_email(member)
        for member in api.fetch_members_by_group_id(confirmed_group_id()).values()
    }
    primary_ids = {}
    for member_id in sorted(pending):
        primary_ids.setdefault(member_email(pending[member_id]), member_id)

    for member_id in sorted(pending):
        member = pending[member_id]
        email = member_email(member)
        created = member_created(member)
        if created is None:
            log.warning(f"Anmeldung {member_id}: kein Anlagedatum in Webling, übersprungen")
            continue
        should_mail = (
            is_valid_email(email)
            and primary_ids[email] == member_id
            and email not in confirmed_emails
        )
        state, is_new = PendingSignup.objects.get_or_create(member_id=member_id)

        if is_new:
            if should_mail:
                send_confirmation_request(member, created)
                state.requested_at = now
                state.save()
                stats["requested"] += 1
            else:
                log.warning(f"Anmeldung {member_id}: ungültige oder doppelte E-Mail, keine Mail")
                stats["skipped"] += 1
            continue

        age = now - created
        if age >= timedelta(days=settings.SIGNUP_EXPIRY_DAYS):
            api.delete_member(member_id)
            state.delete()
            log.info(f"Unbestätigte Anmeldung {member_id} nach {age.days} Tagen gelöscht")
            stats["deleted"] += 1
        elif (
            age >= timedelta(days=settings.SIGNUP_REMINDER_DAYS)
            and state.requested_at
            and not state.reminded_at
            and should_mail
        ):
            send_confirmation_request(member, created, reminder=True)
            state.reminded_at = now
            state.save()
            stats["reminded"] += 1

    return stats
