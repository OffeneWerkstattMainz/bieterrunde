from django import template

from voting.models import Voting, VotingRound

register = template.Library()


@register.inclusion_tag("voting/tags/voting_info.html")
def voting_info(voting: Voting):
    return dict(voting=voting)


@register.inclusion_tag("voting/tags/round_info.html")
def round_info(voting: Voting):
    return dict(voting=voting)


@register.inclusion_tag("voting/tags/messages.html", takes_context=True)
def messages(context: dict):
    return context


@register.inclusion_tag("voting/tags/manage_round_info.html")
def manage_round_info(voting_round: VotingRound):
    return dict(voting_round=voting_round)
