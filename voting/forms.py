from django.forms import (
    ModelForm,
    HiddenInput,
    TextInput,
    Form,
    FileField,
    BooleanField,
    DecimalField,
    CheckboxInput,
)

from voting.models import Voting, Vote


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
        widget=CheckboxInput(attrs={"role": "switch"}),
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

    def get_bids(self):
        """Return {round_number: amount} for non-empty bid fields."""
        bids = {}
        for round_number in range(1, 4):
            amount = self.cleaned_data.get(f"bid_round_{round_number}")
            if amount is not None:
                bids[round_number] = amount
        return bids
