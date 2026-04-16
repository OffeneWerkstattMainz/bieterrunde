from decimal import Decimal

from django.core.exceptions import ValidationError
from django.forms import (
    ModelForm,
    HiddenInput,
    TextInput,
    Form,
    FileField,
    BooleanField,
    CharField,
    DecimalField,
    IntegerField,
    RadioSelect,
)

from voting.models import Voting, Vote, Voter, VotingVoter


class InvalidFormMixin:
    def is_valid(self) -> bool:
        res = super().is_valid()
        if not res:
            for field in self.errors:
                self.fields[field].widget.attrs.update(
                    {"aria-invalid": "true", "aria-describedby": f"{field}_invalid"}
                )
        return res


class VotingForm(InvalidFormMixin, ModelForm):
    class Meta:
        model = Voting
        exclude = ["owner", "voters"]
        localized_fields = ["date"]


class VoteForm(ModelForm):
    class Meta:
        model = Vote
        fields = ["voting_round", "member_id", "amount"]
        localized_fields = ["amount"]
        widgets = {
            "member_id": TextInput(attrs={"autofocus": True, "pattern": "[0-9]*"}),
            # "amount": TextInput(attrs={"autofocus": True, "pattern": "[0-9]*"}),
            "voting_round": HiddenInput(),
        }


class BidImportForm(InvalidFormMixin, Form):
    bids = FileField(label="Absenz-Gebote")


class VoterRegistrationForm(InvalidFormMixin, Form):
    attending = BooleanField(
        label="Ich werde teilnehmen",
        required=False,
        widget=RadioSelect(choices=((False, "Nein"), (True, "Ja"))),
    )
    bid_round_1 = DecimalField(
        label="Gebot Runde 1 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )
    bid_round_2 = DecimalField(
        label="Gebot Runde 2 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )
    bid_round_3 = DecimalField(
        label="Gebot Runde 3 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )

    def clean(self):
        cleaned_data = super().clean()

        attending = cleaned_data.get("attending")
        bid_round_1 = cleaned_data.get("bid_round_1")

        if not attending and not bid_round_1:
            self.add_error("bid_round_1", "Gebote sind erforderlich, wenn du nicht teilnimmst.")
            self.add_error("bid_round_2", "Gebote sind erforderlich, wenn du nicht teilnimmst.")
            self.add_error("bid_round_3", "Gebote sind erforderlich, wenn du nicht teilnimmst.")

        bids = self.get_bids()
        bid_matrix = [bid is None for bid in bids.values()]
        match bid_matrix:
            case [True, False, _]:
                self.add_error("bid_round_1", "Es darf keine Lücken in den Geboten geben.")
            case [False, True, False]:
                self.add_error("bid_round_2", "Es darf keine Lücken in den Geboten geben.")
            case [True, True, False]:
                self.add_error("bid_round_1", "Es darf keine Lücken in den Geboten geben.")
                self.add_error("bid_round_2", "Es darf keine Lücken in den Geboten geben.")

        last = 0
        for round_number, bid in bids.items():
            if bid is None:
                break
            if bid < 0:
                self.add_error(
                    f"bid_round_{round_number}",
                    "Gebote dürfen nicht negativ sein.",
                )
                continue
            if bid < last:
                self.add_error(
                    f"bid_round_{round_number}",
                    "Gebote dürfen nicht niedriger sein als vorherige Runden.",
                )
            last = bid

    def get_bids(self) -> dict[int, Decimal | None]:
        """Return {round_number: amount} where amount can also be None"""
        return {
            round_number: self.cleaned_data.get(f"bid_round_{round_number}")
            for round_number in range(1, 4)
        }


class VotingVoterAddForm(InvalidFormMixin, Form):
    member_id = IntegerField(label="Mitgliedsnummer")
    absent_from_round = IntegerField(label="Abwesend ab Runde", required=False)
    bid_round_1 = DecimalField(
        label="Gebot Runde 1 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )
    bid_round_2 = DecimalField(
        label="Gebot Runde 2 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )
    bid_round_3 = DecimalField(
        label="Gebot Runde 3 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )

    def __init__(self, *args, voting=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.voting = voting

    def clean_member_id(self):
        member_id = self.cleaned_data["member_id"]
        if not Voter.objects.filter(member_id=member_id).exists():
            raise ValidationError("Kein Mitglied mit dieser Nummer gefunden.")
        if (
            self.voting
            and VotingVoter.objects.filter(voting=self.voting, voter__member_id=member_id).exists()
        ):
            raise ValidationError("Dieses Mitglied nimmt bereits an dieser Bieterrunde teil.")
        if self.voting and self.voting.rounds_started:
            raise ValidationError(
                "Teilnehmer können nicht hinzugefügt werden, nachdem die erste Runde begonnen hat."
            )
        return member_id

    def get_bids(self):
        """Return {round_number: amount} for non-empty bid fields."""
        bids = {}
        for round_number in range(1, 4):
            amount = self.cleaned_data.get(f"bid_round_{round_number}")
            if amount is not None:
                bids[round_number] = amount
        return bids


class VotingVoterQuickAddForm(InvalidFormMixin, Form):
    member_ids = CharField(
        label="Mitgliedsnummern (kommagetrennt)",
        widget=TextInput(attrs={"placeholder": "z.B. 101, 102, 103"}),
    )

    def __init__(self, *args, voting=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.voting = voting

    def clean_member_ids(self):
        raw = self.cleaned_data["member_ids"]
        errors = []
        member_ids = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                member_ids.append(int(part))
            except ValueError:
                errors.append(f"'{part}' ist keine gültige Nummer.")
        if errors:
            raise ValidationError(errors)
        if not member_ids:
            raise ValidationError("Bitte mindestens eine Mitgliedsnummer eingeben.")
        missing = set(member_ids) - set(
            Voter.objects.filter(member_id__in=member_ids).values_list("member_id", flat=True)
        )
        if missing:
            raise ValidationError(
                f"Unbekannte Mitgliedsnummern: {', '.join(str(m) for m in sorted(missing))}"
            )
        if self.voting:
            already = set(
                VotingVoter.objects.filter(
                    voting=self.voting, voter__member_id__in=member_ids
                ).values_list("voter__member_id", flat=True)
            )
            if already:
                raise ValidationError(
                    f"Bereits teilnehmend: {', '.join(str(m) for m in sorted(already))}"
                )
            if self.voting.rounds_started:
                raise ValidationError(
                    "Teilnehmer können nicht hinzugefügt werden, "
                    "nachdem die erste Runde begonnen hat."
                )
        return member_ids


class VotingVoterEditForm(InvalidFormMixin, Form):
    name = CharField(label="Name", max_length=255)
    absent_from_round = IntegerField(label="Abwesend ab Runde", required=False)
    bid_round_1 = DecimalField(
        label="Gebot Runde 1 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )
    bid_round_2 = DecimalField(
        label="Gebot Runde 2 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )
    bid_round_3 = DecimalField(
        label="Gebot Runde 3 (€)", required=False, max_digits=10, decimal_places=2, localize=True
    )

    def get_bids(self):
        """Return {round_number: amount} for non-empty bid fields."""
        bids = {}
        for round_number in range(1, 4):
            amount = self.cleaned_data.get(f"bid_round_{round_number}")
            if amount is not None:
                bids[round_number] = amount
        return bids
