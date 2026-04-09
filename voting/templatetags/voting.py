from operator import itemgetter

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
    if not voting_round:
        return dict(voting_round=None, voter_entries=[])

    votes_by_member = {v.member_id: v for v in voting_round.votes.all()}
    voter_entries = []
    for vv in voting_round.voting.voting_voters.select_related("voter").all():
        vote = votes_by_member.get(vv.voter.member_id)
        voter_entries.append(
            {
                "member_id": vv.voter.member_id,
                "voter": vv.voter,
                "voting_voter": vv,
                "vote": vote,
                "has_voted": vote is not None,
            }
        )
    # Non-voters first, then voters; within each group sorted by member_id
    voter_entries.sort(key=itemgetter("has_voted", "member_id"))

    return dict(voting_round=voting_round, voter_entries=voter_entries)
