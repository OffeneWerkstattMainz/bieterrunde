import datetime
import re
from copy import deepcopy

import pytest
from django.core import signing
from django.urls import reverse
from django.utils import timezone

from signup import services, tasks, views
from signup.models import PendingSignup
from signup.services import make_token, process_pending

PENDING = 100
CONFIRMED = 200
OTHER = 300
NOW = timezone.make_aware(datetime.datetime(2026, 11, 2, 12, 0))


class FakeWeblingAPI:
    def __init__(self, members: dict[int, dict]):
        self.members = members

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def fetch_members_by_group_id(self, group_id):
        return {
            member_id: deepcopy(member)
            for member_id, member in self.members.items()
            if group_id in member["parents"]
        }

    def fetch_member(self, member_id):
        return deepcopy(self.members.get(member_id))

    def update_member(self, member_id, properties=None, parents=None):
        self.members[member_id]["properties"].update(properties or {})
        if parents:
            self.members[member_id]["parents"] = parents

    def delete_member(self, member_id):
        del self.members[member_id]


def created(days=0, hours=0):
    return timezone.localtime(NOW - datetime.timedelta(days=days, hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def make_member(member_id, email="ada@example.org", parents=(PENDING,), created_at=None):
    return {
        "id": member_id,
        "meta": {"created": created_at or created(hours=1), "lastmodified": None},
        "parents": list(parents),
        "properties": {"Vorname": "Ada", "Name": "Lovelace", "E-Mail": email},
    }


@pytest.fixture(autouse=True)
def signup_settings(settings):
    settings.SIGNUP_PENDING_GROUP_ID = PENDING
    settings.SIGNUP_CONFIRMED_GROUP_ID = CONFIRMED
    settings.SIGNUP_BASE_URL = "https://portal.example.org/"
    settings.SIGNUP_NOTIFY_EMAILS = ["vorstand@example.org"]
    settings.SIGNUP_REMINDER_DAYS = 3
    settings.SIGNUP_EXPIRY_DAYS = 14
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture
def api(monkeypatch):
    api = FakeWeblingAPI({})
    monkeypatch.setattr(views, "WeblingAPI", lambda api_key: api)
    return api


@pytest.mark.django_db
def test_process_pending_requests_confirmation_once(mailoutbox):
    api = FakeWeblingAPI({1: make_member(1, created_at="2026-11-01 18:30:00")})

    assert process_pending(api, now=NOW)["requested"] == 1
    assert process_pending(api, now=NOW)["requested"] == 0

    [mail] = mailoutbox
    assert mail.to == ["ada@example.org"]
    assert "Hallo Ada" in mail.body
    assert "15.11.2026" in mail.body
    assert re.search(r"https://portal\.example\.org/anmeldung/bestaetigen/\S+/", mail.body)
    assert PendingSignup.objects.get(member_id=1).requested_at == NOW


@pytest.mark.django_db
def test_process_pending_ignores_other_groups(mailoutbox):
    api = FakeWeblingAPI({1: make_member(1, parents=[OTHER])})

    process_pending(api, now=NOW)

    assert mailoutbox == []
    assert not PendingSignup.objects.exists()


@pytest.mark.django_db
def test_process_pending_skips_member_without_created(mailoutbox):
    member = make_member(1)
    member["meta"]["created"] = None
    api = FakeWeblingAPI({1: member})

    assert process_pending(api, now=NOW)["requested"] == 0
    assert mailoutbox == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "members",
    [
        pytest.param({1: make_member(1, email="kaputt")}, id="invalid-email"),
        pytest.param({1: make_member(1, email="")}, id="missing-email"),
        pytest.param(
            {0: make_member(0, parents=[CONFIRMED]), 1: make_member(1)}, id="already-confirmed"
        ),
    ],
)
def test_process_pending_skips_without_mail(mailoutbox, members):
    api = FakeWeblingAPI(members)

    assert process_pending(api, now=NOW) == dict(requested=0, reminded=0, deleted=0, skipped=1)
    # Only reported once
    assert process_pending(api, now=NOW)["skipped"] == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_process_pending_mails_duplicate_address_once(mailoutbox):
    api = FakeWeblingAPI({1: make_member(1), 2: make_member(2, email="ADA@example.org ")})

    stats = process_pending(api, now=NOW)

    assert stats["requested"] == 1
    assert stats["skipped"] == 1
    [mail] = mailoutbox
    assert make_token(1, "ada@example.org") in mail.body


@pytest.mark.django_db
def test_process_pending_reminds_once(mailoutbox):
    api = FakeWeblingAPI({1: make_member(1, created_at=created(days=2, hours=23))})
    process_pending(api, now=NOW)
    assert process_pending(api, now=NOW)["reminded"] == 0

    later = NOW + datetime.timedelta(hours=2)
    assert process_pending(api, now=later)["reminded"] == 1
    assert process_pending(api, now=later)["reminded"] == 0

    request, reminder = mailoutbox
    assert reminder.subject.startswith("Erinnerung")
    assert "13.11.2026" in reminder.body
    assert PendingSignup.objects.get(member_id=1).reminded_at == later


@pytest.mark.django_db
def test_process_pending_no_reminder_for_skipped(mailoutbox):
    api = FakeWeblingAPI({1: make_member(1, email="kaputt", created_at=created(days=1))})
    process_pending(api, now=NOW)

    assert process_pending(api, now=NOW + datetime.timedelta(days=3))["reminded"] == 0
    assert mailoutbox == []


@pytest.mark.django_db
def test_process_pending_deletes_expired(mailoutbox):
    api = FakeWeblingAPI(
        {
            1: make_member(1, created_at=created(days=14)),
            2: make_member(2, email="bob@example.org", created_at=created(days=13, hours=23)),
        }
    )
    PendingSignup.objects.create(member_id=1, requested_at=NOW, reminded_at=NOW)
    PendingSignup.objects.create(member_id=2, requested_at=NOW, reminded_at=NOW)

    stats = process_pending(api, now=NOW)

    assert stats["deleted"] == 1
    assert list(api.members) == [2]
    assert list(PendingSignup.objects.values_list("member_id", flat=True)) == [2]


@pytest.mark.django_db
def test_process_pending_forgets_confirmed(mailoutbox):
    api = FakeWeblingAPI({1: make_member(1, parents=[CONFIRMED])})
    PendingSignup.objects.create(member_id=1, requested_at=NOW)

    process_pending(api, now=NOW)

    assert not PendingSignup.objects.exists()


@pytest.mark.django_db
def test_confirm_flow(client, api, mailoutbox):
    api.members[1] = make_member(1, parents=[PENDING, OTHER])
    url = reverse("signup:confirm", args=[make_token(1, "ada@example.org")])

    response = client.get(url)
    assert response.status_code == 200
    assert response.context["state"] == "confirm"
    # GET alone must not confirm (mail scanners open links)
    assert api.members[1]["parents"] == [PENDING, OTHER]

    response = client.post(url, follow=True)
    assert response.status_code == 200
    assert response.context["state"] == "done"
    assert api.members[1]["parents"] == [OTHER, CONFIRMED]
    [mail] = mailoutbox
    assert mail.to == ["vorstand@example.org"]
    assert "Ada Lovelace" in mail.subject
    assert "E-Mail: ada@example.org" in mail.body

    # Opening the link again just shows the success page
    response = client.post(url)
    assert response.status_code == 200
    assert response.context["state"] == "done"
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_confirm_without_notify_emails(client, api, mailoutbox, settings):
    settings.SIGNUP_NOTIFY_EMAILS = []
    api.members[1] = make_member(1)

    client.post(reverse("signup:confirm", args=[make_token(1, "ada@example.org")]))

    assert CONFIRMED in api.members[1]["parents"]
    assert mailoutbox == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "member, email",
    [
        pytest.param(None, "ada@example.org", id="deleted"),
        pytest.param(make_member(1), "eve@example.org", id="email-changed"),
        pytest.param(make_member(1, parents=[OTHER]), "ada@example.org", id="moved"),
    ],
)
def test_confirm_rejects(client, api, member, email):
    if member:
        api.members[1] = member

    response = client.post(reverse("signup:confirm", args=[make_token(1, email)]))

    assert response.status_code == 410
    assert response.context["state"] == "expired"
    if member:
        assert CONFIRMED not in api.members[1]["parents"]


@pytest.mark.django_db
def test_confirm_invalid_token(client, api):
    api.members[1] = make_member(1)
    token = make_token(1, "ada@example.org")

    response = client.post(reverse("signup:confirm", args=[token[:-2] + "xx"]))

    assert response.status_code == 404
    assert response.context["state"] == "invalid"
    assert CONFIRMED not in api.members[1]["parents"]


@pytest.mark.django_db
def test_confirm_expired_token(client, api, monkeypatch):
    api.members[1] = make_member(1)
    token = make_token(1, "ada@example.org")

    def expired(*args, **kwargs):
        raise signing.SignatureExpired()

    monkeypatch.setattr(services.signing, "loads", expired)
    response = client.get(reverse("signup:confirm", args=[token]))

    assert response.status_code == 410
    assert response.context["state"] == "expired"


@pytest.mark.django_db
def test_process_signups_task(monkeypatch, mailoutbox):
    api = FakeWeblingAPI({1: make_member(1)})
    monkeypatch.setattr(tasks, "WeblingAPI", lambda api_key: api)

    assert tasks.process_signups.call()["requested"] == 1
    assert len(mailoutbox) == 1
