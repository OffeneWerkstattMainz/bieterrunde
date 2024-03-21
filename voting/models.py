import uuid
from contextlib import suppress

from django.db import models
from django.db.models import Sum, Q


class Voting(models.Model):
    id = models.UUIDField(primary_key=True, editable=False, default=uuid.uuid4)
    datetime = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    name = models.CharField("Bezeichnung", max_length=255)
    budget_goal = models.DecimalField("Ziel-Budget", max_digits=10, decimal_places=2)
    voter_count = models.IntegerField("Teilnehmeranzahl")
    total_count = models.IntegerField("Mitgliederanzahl")

    class Meta:
        ordering = ["-datetime"]

    def __str__(self):
        return self.name

    @property
    def active_round(self) -> "VotingRound | None":
        with suppress(VotingRound.DoesNotExist):
            return self.rounds.get(active=True)

    @property
    def active_or_last_round(self):
        if active := self.active_round:
            return active
        return self.rounds.order_by("-round_number").first()

    def new_round(self):
        active_round = self.active_round
        if active_round:
            if not active_round.is_complete:
                raise ValueError(f"Active round {active_round.round_number} is not complete")
            active_round.active = False
            active_round.save()
        round_number = self.rounds.count() + 1
        self.rounds.create(round_number=round_number, active=True)

    @property
    def average_contribution(self):
        return self.budget_goal / self.total_count


class VotingRound(models.Model):
    id = models.AutoField(primary_key=True)
    datetime = models.DateTimeField(auto_now_add=True)
    voting = models.ForeignKey(Voting, on_delete=models.CASCADE, related_name="rounds")
    round_number = models.IntegerField("Runde")
    active = models.BooleanField("Aktiv")

    class Meta:
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

    @property
    def is_complete(self):
        return self.votes.count() == self.voting.voter_count

    @property
    def percent_complete(self):
        return self.votes.count() / self.voting.voter_count * 100

    @property
    def budget_result(self):
        vote_sum = self.votes.aggregate(sum=Sum("amount"))["sum"] or 0
        average_contribution = self.voting.average_contribution
        average_sum = average_contribution * (self.voting.total_count - self.voting.voter_count)
        result = dict(
            vote_sum=vote_sum,
            average_sum=average_sum,
            average_contribution=average_contribution,
            average_participants=self.voting.total_count - self.voting.voter_count,
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
        ordering = ["member_id"]
        unique_together = ("voting_round", "member_id")

    def __str__(self):
        return f"{self.member_id} - {self.amount}"

    def validate_unique(self, exclude=None):
        super().validate_unique(exclude=exclude)
