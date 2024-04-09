import pytest
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_bids():
    from voting.models import Bid, Voting

    owner = User.objects.create_user("owner")
    voting = Voting.objects.create(
        name="Test Voting",
        budget_goal=100,
        voter_count=2,
        total_count=2,
        owner=owner,
    )
    Bid.objects.create(voting=voting, member_id=1, round_number=1, amount=1)
    Bid.objects.create(voting=voting, member_id=1, round_number=2, amount=2)
    Bid.objects.create(voting=voting, member_id=2, round_number=1, amount=1)
    Bid.objects.create(voting=voting, member_id=2, round_number=2, amount=2)
    Bid.objects.create(voting=voting, member_id=2, round_number=3, amount=3)

    active_round = voting.new_round()

    assert active_round.round_number == 1
    assert active_round.is_complete is True
    assert active_round.votes.get(member_id=1).amount == 1
    assert active_round.votes.get(member_id=2).amount == 1

    active_round = voting.new_round()

    assert active_round.round_number == 2
    assert active_round.is_complete is True
    assert active_round.votes.filter(member_id=1).first().amount == 2
    assert active_round.votes.filter(member_id=2).first().amount == 2

    active_round = voting.new_round()

    assert active_round.round_number == 3
    assert active_round.is_complete is True
    # Important: The last bid of member 1 is 2, not 3
    assert active_round.votes.filter(member_id=1).first().amount == 2
    assert active_round.votes.filter(member_id=2).first().amount == 3
