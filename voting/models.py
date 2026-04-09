import csv
import uuid
from contextlib import suppress
from itertools import groupby
from logging import getLogger
from operator import attrgetter

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.db.transaction import atomic

log = getLogger(__name__)


class Voter(models.Model):
    """A member of the association, reusable across votings."""

    id = models.AutoField(primary_key=True)
    member_id = models.IntegerField("Mitgliedsnummer", unique=True)
    name = models.CharField("Name", max_length=255)

    class Meta:
        verbose_name = "Wähler"
        verbose_name_plural = "Wähler"
        ordering = ["member_id"]

    def __str__(self):
        return f"{self.name} (#{self.member_id})"


class Voting(models.Model):
    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    name = models.CharField("Bezeichnung", max_length=255)
    budget_goal = models.DecimalField("Ziel-Budget", max_digits=10, decimal_places=2)
    total_count = models.PositiveIntegerField(
        "Mitgliederanzahl",
        validators=[MinValueValidator(1)],
        help_text="Anzahl der Mitglieder insgesamt",
    )
    date = models.DateField("Datum")
    voters = models.ManyToManyField(Voter, through="VotingVoter", related_name="votings")

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
        if errors:
            raise ValidationError(errors)

    @property
    def voter_count(self):
        return self.voters.count()

    @property
    def active_round(self) -> "VotingRound | None":
        with suppress(VotingRound.DoesNotExist):
            return self.rounds.get(active=True)
        return None

    @property
    def active_or_last_round(self):
        if active := self.active_round:
            return active
        return self.rounds.order_by("-round_number").first()

    def present_voter_count(self, round_number=None):
        """Count of voters who are present (not absent) for the given round."""
        qs = self.voting_voters.all()
        if round_number:
            return qs.filter(
                models.Q(absent_from_round__isnull=True)
                | models.Q(absent_from_round__gt=round_number)
            ).count()
        return qs.filter(absent_from_round__isnull=True).count()

    def absent_voter_count(self, round_number=None):
        """Count of voters who are absent for the given round."""
        qs = self.voting_voters.all()
        if round_number:
            return qs.filter(
                absent_from_round__isnull=False, absent_from_round__lte=round_number
            ).count()
        return qs.filter(absent_from_round__isnull=False).count()

    @property
    def local_voter_count(self):
        """Present voter count for the current/latest round."""
        active = self.active_or_last_round
        if active:
            return self.present_voter_count(active.round_number)
        return self.present_voter_count()

    @property
    def has_voters(self) -> bool:
        return self.voters.exists()

    def new_round(self) -> "VotingRound":
        if self.voter_count == 0:
            raise ValueError("Keine Teilnehmer vorhanden")
        active_round = self.active_round
        if active_round:
            if not active_round.is_complete:
                raise ValueError(f"Active round {active_round.round_number} is not complete")
            active_round.active = False
            active_round.save()
        round_number = self.rounds.count() + 1
        new_round = self.rounds.create(round_number=round_number, active=True)
        new_round.apply_absent_votes()
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
            member_id = int(row[0])
            for round_number, amount in enumerate(row[1:], start=1):
                if not amount:
                    continue
                self.bids.create(member_id=member_id, round_number=round_number, amount=amount)
            # Ensure voter exists and is linked to this voting, marked as absent
            voter, _ = Voter.objects.get_or_create(
                member_id=member_id,
                defaults={"name": f"Mitglied {member_id}"},
            )
            VotingVoter.objects.get_or_create(
                voting=self,
                voter=voter,
                defaults={"absent_from_round": 1},
            )


class VotingVoter(models.Model):
    """Through model linking a Voter to a Voting with per-voting attendance state."""

    id = models.AutoField(primary_key=True)
    voting = models.ForeignKey(Voting, on_delete=models.CASCADE, related_name="voting_voters")
    voter = models.ForeignKey(Voter, on_delete=models.CASCADE, related_name="voting_voters")
    absent_from_round = models.IntegerField(
        "Abwesend ab Runde", null=True, blank=True, default=None
    )

    class Meta:
        verbose_name = "Teilnahme"
        verbose_name_plural = "Teilnahmen"
        unique_together = ("voting", "voter")
        ordering = ["voter__member_id"]

    def __str__(self):
        return f"{self.voter} @ {self.voting}"

    def is_absent_for_round(self, round_number: int) -> bool:
        return self.absent_from_round is not None and self.absent_from_round <= round_number


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

    def apply_absent_votes(self):
        """Create Vote objects for all absent voters in this round.

        For each absent voter: use their bid if available, otherwise use average_contribution_target.
        """
        if self.bids_applied:
            raise ValueError("Bids already applied")

        # Group bids by member_id for quick lookup
        bids_by_member_id = {
            k: list(v)
            for k, v in groupby(
                self.voting.bids.all().order_by("member_id", "-round_number"),
                key=attrgetter("member_id"),
            )
        }

        # Find all absent voters for this round
        absent_voting_voters = self.voting.voting_voters.select_related("voter").filter(
            absent_from_round__isnull=False,
            absent_from_round__lte=self.round_number,
        )

        for vv in absent_voting_voters:
            member_id = vv.voter.member_id
            bids = bids_by_member_id.get(member_id, [])

            # Find the most applicable bid (highest round_number <= current round)
            vote_amount = None
            for bid in bids:
                if bid.round_number <= self.round_number:
                    vote_amount = bid.amount
                    break

            # If no bid found, use average
            if vote_amount is None:
                vote_amount = self.voting.average_contribution_target

            Vote.objects.create(
                voting_round=self,
                member_id=member_id,
                amount=vote_amount,
            )
            log.debug(
                f"Applied absent vote for member {member_id} "
                f"in round {self.round_number}: {vote_amount}"
            )

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
    def present_voter_count(self):
        return self.voting.present_voter_count(self.round_number)

    @property
    def absent_voter_count(self):
        return self.voting.absent_voter_count(self.round_number)

    @property
    def local_vote_count(self):
        """Votes from present (in-person) voters only."""
        return self.votes.count() - self.absent_voter_count

    @property
    def percent_complete(self):
        if self.voting.voter_count == 0:
            return 0
        return self.votes.count() / self.voting.voter_count * 100

    @property
    def percent_complete_local(self):
        present = self.present_voter_count
        if present == 0:
            return 0
        return self.local_vote_count / present * 100

    @property
    def budget_result(self):
        vote_sum = self.votes.aggregate(sum=Sum("amount"))["sum"] or 0
        average_contribution_target = self.voting.average_contribution_target
        voter_count = self.voting.voter_count
        average_participants = self.voting.total_count - voter_count
        average_sum = average_contribution_target * average_participants
        result = dict(
            vote_sum=vote_sum,
            average_sum=average_sum,
            average_contribution_target=average_contribution_target,
            average_participants=average_participants,
            average_contribution_voters=vote_sum / voter_count if voter_count else 0,
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
