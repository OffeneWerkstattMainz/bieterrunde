from django.forms import ModelForm, HiddenInput, TextInput

from voting.models import Voting, Vote


class VotingForm(ModelForm):
    class Meta:
        model = Voting
        exclude = ["owner"]


class VoteForm(ModelForm):
    class Meta:
        model = Vote
        fields = ["voting_round", "member_id", "amount"]
        widgets = {
            "member_id": TextInput(attrs={"autofocus": True, "pattern": "[0-9]*"}),
            # "amount": TextInput(attrs={"autofocus": True, "pattern": "[0-9]*"}),
            "voting_round": HiddenInput(),
        }
