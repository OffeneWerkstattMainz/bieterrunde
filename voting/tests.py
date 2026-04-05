import io
from contextlib import nullcontext
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from voting.models import Bid, Vote, Voting, VotingRound


def make_voting(owner, voter_count=2, total_count=2, budget_goal=Decimal("100")):
    return Voting.objects.create(
        name="Test Voting",
        budget_goal=budget_goal,
        voter_count=voter_count,
        total_count=total_count,
        owner=owner,
    )


def cast_votes(voting_round, amounts):
    for i, amount in enumerate(amounts, start=1):
        Vote.objects.create(voting_round=voting_round, member_id=i, amount=amount)


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
    "csv_string, expected_bid_count, expected_voter_count, raises_exception",
    [
        ("1,1,2\n", 1, 3, False),
        ("1;1;2\n2;1;2;3", 2, 4, False),
        ("id;r1;r2;r3\n1;1;2\n2;1;2;3", 2, 4, False),
        ("1,1\n2,1\n3,1", 3, 5, False),
        ("1,1\n1,1", 0, 0, IntegrityError),
    ],
)
def test_bids_import_csv(csv_string, expected_bid_count, expected_voter_count, raises_exception):
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
        assert voting.voter_count == expected_voter_count


# ---------------------------------------------------------------------------
# Voting.clean() validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_voting_clean_budget_goal_too_low():
    owner = User.objects.create_user("owner2")
    voting = make_voting(owner, budget_goal=0)
    with pytest.raises(ValidationError) as exc:
        voting.clean()
    assert "budget_goal" in exc.value.message_dict


@pytest.mark.django_db
def test_voting_clean_voter_count_exceeds_total():
    owner = User.objects.create_user("owner3")
    voting = make_voting(owner, voter_count=5, total_count=3)
    with pytest.raises(ValidationError) as exc:
        voting.clean()
    assert "voter_count" in exc.value.message_dict


# ---------------------------------------------------------------------------
# VotingRound.new_round() guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_round_raises_when_previous_incomplete():
    owner = User.objects.create_user("owner4")
    voting = make_voting(owner, voter_count=2, total_count=2)
    voting.new_round()  # round 1, no votes cast → incomplete
    with pytest.raises(ValueError, match="not complete"):
        voting.new_round()


# ---------------------------------------------------------------------------
# VotingRound.apply_bids() double-apply guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_apply_bids_raises_when_already_applied():
    owner = User.objects.create_user("owner5")
    voting = make_voting(owner)
    round = voting.new_round()
    with pytest.raises(ValueError, match="already applied"):
        round.apply_bids()


# ---------------------------------------------------------------------------
# VotingRound.budget_result
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "vote_amounts, budget_goal, total_count, expected_success",
    [
        ([50, 50], 100, 2, True),  # exactly meets goal
        ([60, 60], 100, 2, True),  # exceeds goal
        ([30, 30], 100, 2, False),  # falls short, no absent members
        ([30, 30], 100, 4, True),  # vote_sum=60 + avg_sum=(100/4)*2=50 = 110 >= 100
        ([10, 10], 100, 4, False),  # vote_sum=20 + avg_sum=50 = 70 < 100
    ],
)
def test_budget_result(vote_amounts, budget_goal, total_count, expected_success):
    owner = User.objects.create_user(f"owner_br_{budget_goal}_{total_count}_{sum(vote_amounts)}")
    budget_goal = Decimal(budget_goal)
    voter_count = len(vote_amounts)
    voting = make_voting(
        owner, voter_count=voter_count, total_count=total_count, budget_goal=budget_goal
    )
    round = voting.new_round()
    cast_votes(round, vote_amounts)
    result = round.budget_result
    assert result["success"] is expected_success
    assert result["vote_sum"] == sum(vote_amounts)
    assert result["difference"] == result["result"] - budget_goal


# ---------------------------------------------------------------------------
# View tests
# ---------------------------------------------------------------------------


@pytest.fixture
def owner(db):
    return User.objects.create_user("viewowner", password="pass")


@pytest.fixture
def voting(owner):
    return make_voting(owner)


@pytest.mark.django_db
def test_index_unauthenticated(client):
    response = client.get(reverse("voting:index"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_index_shows_own_votings(client, owner, voting):
    client.force_login(owner)
    response = client.get(reverse("voting:index"))
    assert voting.name in response.content.decode()


@pytest.mark.django_db
def test_voting_create_get(client, owner):
    client.force_login(owner)
    response = client.get(reverse("voting:create"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_voting_create_post_valid(client, owner):
    client.force_login(owner)
    response = client.post(
        reverse("voting:create"),
        {"name": "Neue Runde", "budget_goal": "500", "voter_count": "3", "total_count": "5"},
    )
    assert response.status_code == 302
    assert Voting.objects.filter(name="Neue Runde", owner=owner).exists()


@pytest.mark.django_db
def test_voting_create_post_invalid(client, owner):
    client.force_login(owner)
    response = client.post(
        reverse("voting:create"),
        {"name": "Test", "budget_goal": "0", "voter_count": "5", "total_count": "3"},
    )
    assert response.status_code == 200  # re-renders form


@pytest.mark.django_db
def test_get_voting_non_owner_redirects(client, voting):
    other = User.objects.create_user("other", password="pass")
    client.force_login(other)
    response = client.get(reverse("voting:manage", args=[voting.id]))
    assert response.status_code == 302
    assert response["Location"] == reverse("voting:index")


@pytest.mark.django_db
def test_voting_new_round_creates_round(client, owner, voting):
    client.force_login(owner)
    response = client.post(reverse("voting:new-round", args=[voting.id]))
    assert response.status_code == 302
    assert voting.rounds.count() == 1


@pytest.mark.django_db
def test_voting_new_round_incomplete_shows_error(client, owner, voting):
    client.force_login(owner)
    voting.new_round()  # round 1, incomplete
    response = client.post(reverse("voting:new-round", args=[voting.id]))
    assert response.status_code == 302
    assert voting.rounds.count() == 1  # no second round created


@pytest.mark.django_db
def test_voting_vote_get(client, owner, voting):
    round = voting.new_round()
    response = client.get(reverse("voting:vote", args=[voting.id]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_voting_vote_post_saves_vote(client, owner, voting):
    round = voting.new_round()
    Vote.objects.create(voting_round=round, member_id=2, amount=50)  # one pre-existing vote
    response = client.post(
        reverse("voting:vote", kwargs={"voting_id": voting.id, "voting_round_id": round.id}),
        {"voting_round": round.id, "member_id": 1, "amount": "42"},
    )
    assert response.status_code == 302
    assert round.votes.filter(member_id=1, amount=42).exists()


@pytest.mark.django_db
def test_voting_export_csv(client, owner, voting):
    client.force_login(owner)
    round = voting.new_round()
    cast_votes(round, [40, 60])
    response = client.get(reverse("voting:export", args=[voting.id]))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    content = response.content.decode()
    assert "member_id" in content
    assert "40" in content


@pytest.mark.django_db
def test_voting_export_incomplete_round_returns_no_content(client, owner, voting):
    client.force_login(owner)
    voting.new_round()  # incomplete — no votes
    response = client.get(reverse("voting:export", args=[voting.id]))
    assert response.status_code == 204


@pytest.mark.django_db
def test_voting_import_bids_non_htmx_redirects(client, owner, voting):
    client.force_login(owner)
    response = client.post(reverse("voting:import-bids", args=[voting.id]))
    assert response.status_code == 302


@pytest.mark.django_db
def test_voting_import_bids_htmx_post_valid(client, owner, voting):
    client.force_login(owner)
    csv_content = b"1,10,20\n2,15,25\n"
    response = client.post(
        reverse("voting:import-bids", args=[voting.id]),
        {"bids": io.BytesIO(csv_content)},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert response["HX-Refresh"] == "true"
    assert voting.bids.count() == 4
