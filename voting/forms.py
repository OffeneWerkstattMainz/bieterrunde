from django.forms import ModelForm, HiddenInput, TextInput, Form, FileField

from voting.models import Voting, Vote


class InvalidFormMixin:
    def is_valid(self) -> bool:
        res = super().is_valid()
        if not res:
            for field in self.errors:
                self.fields[field].widget.attrs.update({"aria-invalid": "true"})
        return res


class VotingForm(InvalidFormMixin, ModelForm):
    class Meta:
        model = Voting
        exclude = ["owner"]


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
    bids = FileField(label="Fern-Gebote")
