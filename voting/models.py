import csv
import uuid
from contextlib import suppress
from itertools import groupby
from logging import getLogger
from operator import attrgetter

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum, Q
from django.db.transaction import atomic

log = getLogger(__name__)


class Voting(models.Model):
    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    name = models.CharField("Bezeichnung", max_length=255)
    budget_goal = models.DecimalField("Ziel-Budget", max_digits=10, decimal_places=2)
    voter_count = models.PositiveIntegerField(
        "Teilnehmeranzahl",
        validators=[MinValueValidator(1)],
        help_text="Anzahl der Teilnehmer vor Ort (inkl. im Voraus abgegebener Gebote).",
    )
    total_count = models.PositiveIntegerField(
        "Mitgliederanzahl",
        validators=[MinValueValidator(1)],
        help_text="Anzahl der Mitglieder insgesamt.",
    )

    class Meta:
        verbose_name = "Bieterrunde"
        verbose_name_plural = "Bieterrunden"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if self.budget_goal < 1:
            errors["budget_goal"] = "Das Ziel-Budget muss größer als 0 sein."
        if self.voter_count > self.total_count:
            errors["voter_count"] = (
                "Die Teilnehmeranzahl darf nicht kleiner als die Mitgliederanzahl sein."
            )
        if errors:
            raise ValidationError(errors)

    @property
    def active_round(self) -> "VotingRound | None":
        with suppress(VotingRound.DoesNotExist):
            return self.rounds.get(active=True)

    @property
    def active_or_last_round(self):
        if active := self.active_round:
            return active
        return self.rounds.order_by("-round_number").first()

    @property
    def local_voter_count(self):
        return self.voter_count - self.bid_count

    @property
    def bid_count(self):
        # Since bids fall back to the last round given, we can just count the bids of the first round
        return self.bids.filter(round_number=1).count()

    def new_round(self) -> "VotingRound":
        active_round = self.active_round
        if active_round:
            if not active_round.is_complete:
                raise ValueError(f"Active round {active_round.round_number} is not complete")
            active_round.active = False
            active_round.save()
        round_number = self.rounds.count() + 1
        new_round = self.rounds.create(round_number=round_number, active=True)
        new_round.apply_bids()
        return new_round

    @property
    def average_contribution_target(self):
        return self.budget_goal / self.total_count

    @atomic
    def import_bids_csv(self, csv_lines: list[str]):
        for row in csv.reader(csv_lines, delimiter=";" if ";" in csv_lines[0] else ","):
            if not row or not row[0].isdigit():
                # Skip empty lines, headers and/or comments
                continue
            for round_number, amount in enumerate(row[1:], start=1):
                if not amount:
                    continue
                self.bids.create(member_id=row[0], round_number=round_number, amount=amount)
        self.voter_count += self.bid_count
        self.save()


class Bid(models.Model):
    id = models.AutoField(primary_key=True)
    datetime = models.DateTimeField(auto_now_add=True)
    voting = models.ForeignKey(Voting, on_delete=models.CASCADE, related_name="bids")
    round_number = models.IntegerField("Runde")
    member_id = models.IntegerField("Mitgliedsnummer")
    amount = models.DecimalField("Gebot", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Absenz-Gebot"
        verbose_name_plural = "Absenz-Gebote"
        ordering = ["voting", "member_id", "round_number"]
        unique_together = ("voting", "member_id", "round_number")

    def __str__(self):
        return f"M{self.member_id}: #{self.round_number} - {self.amount} €"


class VotingRound(models.Model):
    id = models.AutoField(primary_key=True)
    datetime = models.DateTimeField(auto_now_add=True)
    voting = models.ForeignKey(Voting, on_delete=models.CASCADE, related_name="rounds")
    round_number = models.IntegerField("Runde")
    active = models.BooleanField("Aktiv")
    bids_applied = models.BooleanField("Gebote angewendet", default=False)

    class Meta:
        verbose_name = "Abstimmungsrunde"
        verbose_name_plural = "Abstimmungsrunden"
        ordering = ["voting", "round_number"]
        constraints = [
            models.UniqueConstraint(fields=["voting", "round_number"], name="unique_round_number"),
            models.UniqueConstraint(
                fields=["voting", "active"],
                condition=models.Q(active=True),
                name="unique_active_round",
            ),
        ]

    def __str__(self):
        return f"{self.voting.name} - Runde {self.round_number}"

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        if self.is_complete:
            self.active = False
        return super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def apply_bids(self):
        if self.bids_applied:
            raise ValueError("Bids already applied")
        bids_by_member_id = {
            k: list(v)
            for k, v in groupby(
                self.voting.bids.all().order_by("member_id", "-round_number"),
                key=attrgetter("member_id"),
            )
        }
        log.debug(f"Bids by member ID: {bids_by_member_id}")
        for member_id, bids in bids_by_member_id.items():
            for bid in bids:
                if bid.round_number > self.round_number:
                    continue
                Vote.objects.create(voting_round=self, member_id=member_id, amount=bid.amount)
                log.debug(
                    f"Applying bid for member {bid.member_id} for round {bid.round_number} to round {self.round_number}."
                )
                break
        self.bids_applied = True
        self.save()

    @property
    def is_complete(self):
        if self.id is None:
            return False
        return self.votes.count() == self.voting.voter_count

    @property
    def is_active_or_last(self):
        return self == self.voting.active_or_last_round

    @property
    def percent_complete(self):
        return self.votes.count() / self.voting.voter_count * 100

    @property
    def percent_complete_local(self):
        return self.local_vote_count / self.voting.local_voter_count * 100

    @property
    def local_vote_count(self):
        return self.votes.count() - self.voting.bid_count

    @property
    def budget_result(self):
        vote_sum = self.votes.aggregate(sum=Sum("amount"))["sum"] or 0
        average_contribution_target = self.voting.average_contribution_target
        average_sum = average_contribution_target * (
            self.voting.total_count - self.voting.voter_count
        )
        result = dict(
            vote_sum=vote_sum,
            average_sum=average_sum,
            average_contribution_target=average_contribution_target,
            average_participants=self.voting.total_count - self.voting.voter_count,
            average_contribution_voters=vote_sum / self.voting.voter_count,
            result=vote_sum + average_sum,
            difference=(vote_sum + average_sum) - self.voting.budget_goal,
            success=vote_sum + average_sum >= self.voting.budget_goal,
        )
        return result


class Vote(models.Model):
    id = models.AutoField(primary_key=True)
    datetime = models.DateTimeField(auto_now_add=True)
    voting_round = models.ForeignKey(VotingRound, on_delete=models.CASCADE, related_name="votes")
    member_id = models.IntegerField("Mitgliedsnummer")
    amount = models.DecimalField("Beitrag", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Stimme"
        verbose_name_plural = "Stimmen"
        ordering = ["member_id"]
        unique_together = ("voting_round", "member_id")

    def __str__(self):
        return f"{self.member_id} - {self.amount}"
