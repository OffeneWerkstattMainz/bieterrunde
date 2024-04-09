from contextlib import nullcontext

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError

from voting.models import Bid, Voting


@pytest.mark.django_db
def test_bids():
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "csv_string, expected_bid_count, raises_exception",
    [
        ("1,1,2\n", 1, False),
        ("1;1;2\n2;1;2;3", 2, False),
        ("id;r1;r2;r3\n1;1;2\n2;1;2;3", 2, False),
        ("1,1\n2,1\n3,1", 0, ValueError),
        ("1,1\n1,1", 0, IntegrityError),
    ],
)
def test_bids_import_csv(csv_string, expected_bid_count, raises_exception):
    owner = User.objects.create_user("owner")
    voting = Voting.objects.create(
        name="Test Voting",
        budget_goal=100,
        voter_count=2,
        total_count=2,
        owner=owner,
    )

    with pytest.raises(raises_exception) if raises_exception else nullcontext():
        voting.import_bids_csv(csv_string.splitlines())
        assert voting.bid_count == expected_bid_count
