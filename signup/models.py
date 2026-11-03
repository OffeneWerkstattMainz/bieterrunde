from django.db import models


class PendingSignup(models.Model):
    """Which mails an unconfirmed signup in Webling already got."""

    member_id = models.PositiveIntegerField(unique=True, help_text="Webling-Objekt-ID")
    requested_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Anmeldung {self.member_id}"
