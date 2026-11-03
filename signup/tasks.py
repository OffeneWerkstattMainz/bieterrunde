from logging import getLogger

from django.conf import settings
from django_tasks import task

from core.webling_api import WeblingAPI
from signup.services import process_pending

log = getLogger(__name__)


@task()
def process_signups() -> dict[str, int]:
    """Send double opt-in mails for new Webling signups, remind and delete unconfirmed ones."""
    with WeblingAPI(settings.WEBLING_API_KEY) as api:
        stats = process_pending(api)
    log.info(f"Anmeldungen verarbeitet: {stats}")
    return stats
