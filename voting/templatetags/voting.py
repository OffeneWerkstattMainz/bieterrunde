from django import template

from voting.models import Voting

register = template.Library()


@register.inclusion_tag("voting/tags/voting_info.html")
def voting_info(voting: Voting):
    return dict(voting=voting)


@register.inclusion_tag("voting/tags/round_info.html")
def round_info(voting: Voting):
    return dict(voting=voting)
