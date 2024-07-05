from datetime import timedelta

from django.core.management import BaseCommand
from django.utils import timezone

from voting.models import Voting


class Command(BaseCommand):
    def handle(self, *args, **options):
        count, deleted = Voting.objects.filter(
            created_at__lte=timezone.now() - timedelta(days=14)
        ).delete()
        self.stdout.write(
            self.style.SUCCESS("Successfully cleaned up votings")
            + self.style.NOTICE(f"\n  - Deleted {count} rows.")
        )
        if deleted:
            self.stdout.write(
                "    - "
                + "\n    - ".join(f"{self.style.SQL_TABLE(k)}: {v}" for k, v in deleted.items())
            )
