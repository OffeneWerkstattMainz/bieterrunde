import datetime
import io
from contextlib import nullcontext
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from voting.models import Bid, Vote, Voter, Voting, VotingVoter
from voting.utils.hmac_auth import compute_member_token, verify_member_token


def make_voter(member_id, name=None):
    """Get or create a global Voter object."""
    voter, _ = Voter.objects.get_or_create(
        member_id=member_id,
        defaults={"name": name or f"Voter {member_id}"},
    )
    return voter


def make_voting(owner, voter_count=2, total_count=2, budget_goal=Decimal("100")):
    voting = Voting.objects.create(
        name="Test Voting",
        budget_goal=budget_goal,
        total_count=total_count,
        owner=owner,
        date=datetime.date(2024, 1, 1),
    )
    for i in range(1, voter_count + 1):
        voter = make_voter(i)
        VotingVoter.objects.create(voting=voting, voter=voter)
    return voting


def cast_votes(voting_round, amounts):
    for i, amount in enumerate(amounts, start=1):
        Vote.objects.create(voting_round=voting_round, member_id=i, amount=amount)


# ---------------------------------------------------------------------------
# Bids (absent voters)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bids():
    owner = User.objects.create_user("owner")
    voting = Voting.objects.create(
        name="Test Voting",
        budget_goal=100,
        total_count=2,
        owner=owner,
        date=datetime.date(2024, 1, 1),
    )
    v1 = make_voter(1)
    v2 = make_voter(2)
    VotingVoter.objects.create(voting=voting, voter=v1, absent_from_round=1)
    VotingVoter.objects.create(voting=voting, voter=v2, absent_from_round=1)

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
        ("1,1,2\n", 1, 1, False),
        ("1;1;2\n2;1;2;3", 2, 2, False),
        ("id;r1;r2;r3\n1;1;2\n2;1;2;3", 2, 2, False),
        ("1,1\n2,1\n3,1", 3, 3, False),
        ("1,1\n1,1", 0, 0, IntegrityError),
    ],
)
def test_bids_import_csv(csv_string, expected_bid_count, expected_voter_count, raises_exception):
    owner = User.objects.create_user("owner")
    voting = Voting.objects.create(
        name="Test Voting",
        budget_goal=100,
        total_count=10,
        owner=owner,
        date=datetime.date(2024, 1, 1),
    )

    with pytest.raises(raises_exception) if raises_exception else nullcontext():
        voting.import_bids_csv(csv_string.splitlines())
        assert voting.bids.values("member_id").distinct().count() == expected_bid_count
        assert voting.voter_count == expected_voter_count


# ---------------------------------------------------------------------------
# Absent voters without bids get average
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_absent_voter_without_bids_gets_average():
    owner = User.objects.create_user("owner_avg")
    voting = Voting.objects.create(
        name="Test Voting",
        budget_goal=Decimal("100"),
        total_count=4,
        owner=owner,
        date=datetime.date(2024, 1, 1),
    )
    v1 = make_voter(101)
    v2 = make_voter(102)
    VotingVoter.objects.create(voting=voting, voter=v1)  # present
    VotingVoter.objects.create(voting=voting, voter=v2, absent_from_round=1)  # absent, no bids

    round1 = voting.new_round()

    # Absent voter should get average_contribution_target = 100/4 = 25
    assert round1.votes.filter(member_id=102).exists()
    assert round1.votes.get(member_id=102).amount == Decimal("25")

    # Round is not yet complete (present voter hasn't voted)
    assert round1.is_complete is False

    # Present voter votes
    Vote.objects.create(voting_round=round1, member_id=101, amount=50)
    assert round1.is_complete is True


# ---------------------------------------------------------------------------
# Voter leaves between rounds
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_voter_leaves_between_rounds():
    owner = User.objects.create_user("owner_leave")
    voting = Voting.objects.create(
        name="Test Voting",
        budget_goal=Decimal("100"),
        total_count=2,
        owner=owner,
        date=datetime.date(2024, 1, 1),
    )
    v1 = make_voter(201)
    v2 = make_voter(202)
    vv1 = VotingVoter.objects.create(voting=voting, voter=v1)
    VotingVoter.objects.create(voting=voting, voter=v2)

    # Both present in round 1
    round1 = voting.new_round()
    Vote.objects.create(voting_round=round1, member_id=201, amount=50)
    Vote.objects.create(voting_round=round1, member_id=202, amount=60)
    assert round1.is_complete is True

    # Voter 1 leaves before round 2
    vv1.absent_from_round = 2
    vv1.save()

    round2 = voting.new_round()
    # Voter 1 should get average (no bids) = 100/2 = 50
    assert round2.votes.get(member_id=201).amount == Decimal("50")
    # Voter 2 still needs to vote
    assert round2.is_complete is False
    Vote.objects.create(voting_round=round2, member_id=202, amount=55)
    assert round2.is_complete is True


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


# ---------------------------------------------------------------------------
# VotingRound.new_round() guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_round_raises_when_previous_incomplete():
    owner = User.objects.create_user("owner4")
    voting = make_voting(owner, voter_count=2, total_count=2)
    voting.new_round()  # round 1, no votes cast -> incomplete
    with pytest.raises(ValueError, match="not complete"):
        voting.new_round()


@pytest.mark.django_db
def test_new_round_raises_when_no_voters():
    owner = User.objects.create_user("owner_no_voters")
    voting = Voting.objects.create(
        name="Test Voting",
        budget_goal=100,
        total_count=2,
        owner=owner,
        date=datetime.date(2024, 1, 1),
    )
    with pytest.raises(ValueError, match="Keine Teilnehmer"):
        voting.new_round()


# ---------------------------------------------------------------------------
# VotingRound.apply_absent_votes() double-apply guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_apply_absent_votes_raises_when_already_applied():
    owner = User.objects.create_user("owner5")
    voting = make_voting(owner)
    round = voting.new_round()
    with pytest.raises(ValueError, match="already applied"):
        round.apply_absent_votes()


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
# HMAC auth tokens
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_hmac_token_compute_and_verify():
    token = compute_member_token(42)
    assert verify_member_token(42, token) is True
    assert verify_member_token(43, token) is False
    assert verify_member_token(42, "wrong") is False


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
        {"name": "Neue Runde", "budget_goal": "500", "total_count": "5", "date": "2024-01-01"},
    )
    assert response.status_code == 302
    assert Voting.objects.filter(name="Neue Runde", owner=owner).exists()


@pytest.mark.django_db
def test_voting_create_post_invalid(client, owner):
    client.force_login(owner)
    response = client.post(
        reverse("voting:create"),
        {"name": "Test", "budget_goal": "0", "total_count": "3", "date": "2024-01-01"},
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
    voting.new_round()
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
    csv_content = b"10,10,20\n20,15,25\n"
    response = client.post(
        reverse("voting:import-bids", args=[voting.id]),
        {"bids": io.BytesIO(csv_content)},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert response["HX-Refresh"] == "true"
    assert voting.bids.count() == 4


# ---------------------------------------------------------------------------
# Voter registration view tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_voter_registration_invalid_token(client, voting):
    make_voter(300)
    response = client.get(
        reverse(
            "voting:voter-registration",
            kwargs={"voting_id": voting.id, "member_id": 300, "auth_token": "bad"},
        )
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_voter_registration_get(client, voting):
    voter = make_voter(301)
    token = compute_member_token(301)
    response = client.get(
        reverse(
            "voting:voter-registration",
            kwargs={"voting_id": voting.id, "member_id": 301, "auth_token": token},
        )
    )
    assert response.status_code == 200
    # Only calling get should not create a VotingVoter entry
    assert not VotingVoter.objects.filter(voting=voting, voter=voter).exists()


@pytest.mark.django_db
def test_voter_registration_post_attending(client, voting):
    voter = make_voter(302)
    token = compute_member_token(302)
    url = reverse(
        "voting:voter-registration",
        kwargs={"voting_id": voting.id, "member_id": 302, "auth_token": token},
    )
    response = client.post(url, {"attending": "on", "bid_round_1": "50", "bid_round_2": "60"})
    assert response.status_code == 302
    vv = VotingVoter.objects.get(voting=voting, voter=voter)
    assert vv.absent_from_round is None  # attending
    assert voting.bids.filter(member_id=302, round_number=1).first().amount == Decimal("50")
    assert voting.bids.filter(member_id=302, round_number=2).first().amount == Decimal("60")


@pytest.mark.django_db
def test_voter_registration_post_not_attending(client, voting):
    voter = make_voter(303)
    token = compute_member_token(303)
    url = reverse(
        "voting:voter-registration",
        kwargs={"voting_id": voting.id, "member_id": 303, "auth_token": token},
    )
    response = client.post(url, {"bid_round_1": "45"})
    assert response.status_code == 302
    vv = VotingVoter.objects.get(voting=voting, voter=voter)
    assert vv.absent_from_round == 1  # not attending
    assert voting.bids.filter(member_id=303, round_number=1).first().amount == Decimal("45")


@pytest.mark.parametrize(
    ("bid_amounts", "is_valid"),
    [(["-10"], False), (["20", "5"], False), (["30", "", "25"], False), (["30", "40"], True)],
)
@pytest.mark.django_db
def test_voter_registration_post_invalid_bids(client, voting, bid_amounts, is_valid):
    voter = make_voter(303)
    token = compute_member_token(303)
    url = reverse(
        "voting:voter-registration",
        kwargs={"voting_id": voting.id, "member_id": 303, "auth_token": token},
    )
    post_data = {}
    for i, amount in enumerate(bid_amounts, start=1):
        if amount:
            post_data[f"bid_round_{i}"] = amount
    response = client.post(url, post_data)
    if is_valid:
        assert response.status_code == 302
        vv = VotingVoter.objects.get(voting=voting, voter=voter)
        assert vv.absent_from_round == 1  # not attending
        assert voting.bids.filter(member_id=303, round_number=1).first().amount == Decimal(
            bid_amounts[0]
        )
    else:
        assert response.status_code == 200
        content = response.content.decode()
        assert (
            "Gebote dürfen nicht negativ sein" in content
            or "Gebote dürfen nicht niedriger sein als vorherige Runden" in content
            or "Es darf keine Lücken in den Geboten geben." in content
        )


# ---------------------------------------------------------------------------
# Voter management view tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_voters_list_htmx(client, owner, voting):
    client.force_login(owner)
    response = client.get(
        reverse("voting:voters", args=[voting.id]),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "Teilnehmer verwalten" in content


@pytest.mark.django_db
def test_voters_list_non_htmx_redirects(client, owner, voting):
    client.force_login(owner)
    response = client.get(reverse("voting:voters", args=[voting.id]))
    assert response.status_code == 302


@pytest.mark.django_db
def test_voter_add_htmx(client, owner, voting):
    client.force_login(owner)
    # Create a Voter that is not yet linked to this voting
    make_voter(999, "Pre-imported Voter")
    response = client.post(
        reverse("voting:voter-add", args=[voting.id]),
        {"member_id": "999", "absent_from_round": "2", "bid_round_1": "30"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "Teilnehmer verwalten" in content
    assert "Pre-imported Voter" in content
    vv = VotingVoter.objects.get(voting=voting, voter__member_id=999)
    assert vv.absent_from_round == 2
    assert Bid.objects.filter(
        voting=voting, member_id=999, round_number=1
    ).first().amount == Decimal("30")


@pytest.mark.django_db
def test_voter_add_nonexistent_member_shows_error(client, owner, voting):
    client.force_login(owner)
    response = client.post(
        reverse("voting:voter-add", args=[voting.id]),
        {"member_id": "9999"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "HX-Refresh" not in response
    assert "Kein Mitglied" in response.content.decode()


@pytest.mark.django_db
def test_voter_add_duplicate_shows_error(client, owner, voting):
    # Voter with member_id=1 already exists in the voting fixture
    client.force_login(owner)
    response = client.post(
        reverse("voting:voter-add", args=[voting.id]),
        {"member_id": "1"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "HX-Refresh" not in response
    assert "bereits" in response.content.decode()


@pytest.mark.django_db
def test_voter_quick_add_htmx(client, owner, voting):
    client.force_login(owner)
    make_voter(901, "Quick A")
    make_voter(902, "Quick B")
    response = client.post(
        reverse("voting:voter-quick-add", args=[voting.id]),
        {"member_ids": "901, 902"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "Teilnehmer verwalten" in content
    assert "Quick A" in content
    assert "Quick B" in content
    assert VotingVoter.objects.filter(voting=voting, voter__member_id=901).exists()
    assert VotingVoter.objects.filter(voting=voting, voter__member_id=902).exists()


@pytest.mark.django_db
def test_voter_quick_add_unknown_member(client, owner, voting):
    client.force_login(owner)
    response = client.post(
        reverse("voting:voter-quick-add", args=[voting.id]),
        {"member_ids": "8888"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "HX-Refresh" not in response
    assert "Unbekannte" in response.content.decode()


@pytest.mark.django_db
def test_voter_edit_htmx(client, owner, voting):
    client.force_login(owner)
    vv = VotingVoter.objects.filter(voting=voting).first()
    response = client.post(
        reverse("voting:voter-edit", args=[voting.id, vv.id]),
        {
            "name": "Updated Name",
            "absent_from_round": "1",
            "bid_round_1": "25",
            "bid_round_2": "35",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "Teilnehmer verwalten" in content
    assert "Updated Name" in content
    vv.refresh_from_db()
    assert vv.absent_from_round == 1
    vv.voter.refresh_from_db()
    assert vv.voter.name == "Updated Name"
    assert Bid.objects.get(
        voting=voting, member_id=vv.voter.member_id, round_number=1
    ).amount == Decimal("25")
    assert Bid.objects.get(
        voting=voting, member_id=vv.voter.member_id, round_number=2
    ).amount == Decimal("35")


@pytest.mark.django_db
def test_voter_management_owner_only(client, voting):
    other = User.objects.create_user("other_vm", password="pass")
    client.force_login(other)
    response = client.get(
        reverse("voting:voters", args=[voting.id]),
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("voting:index")


# ---------------------------------------------------------------------------
# Restrict voter additions once the first round has started
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_voting_rounds_started_property(voting):
    assert voting.rounds_started is False
    voting.new_round()
    assert voting.rounds_started is True


@pytest.mark.django_db
def test_voter_add_blocked_after_round_started(client, owner, voting):
    client.force_login(owner)
    voting.new_round()
    make_voter(999, "Too Late")
    response = client.post(
        reverse("voting:voter-add", args=[voting.id]),
        {"member_id": "999"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "erste Runde" in response.content.decode()
    assert not VotingVoter.objects.filter(voting=voting, voter__member_id=999).exists()


@pytest.mark.django_db
def test_voter_quick_add_blocked_after_round_started(client, owner, voting):
    client.force_login(owner)
    voting.new_round()
    make_voter(801, "Too Late A")
    make_voter(802, "Too Late B")
    response = client.post(
        reverse("voting:voter-quick-add", args=[voting.id]),
        {"member_ids": "801, 802"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "erste Runde" in response.content.decode()
    assert not VotingVoter.objects.filter(voting=voting, voter__member_id=801).exists()
    assert not VotingVoter.objects.filter(voting=voting, voter__member_id=802).exists()


@pytest.mark.django_db
def test_voter_registration_blocked_after_round_started(client, voting):
    voter = make_voter(310)
    voting.new_round()
    token = compute_member_token(310)
    response = client.get(
        reverse(
            "voting:voter-registration",
            kwargs={"voting_id": voting.id, "member_id": 310, "auth_token": token},
        )
    )
    assert response.status_code == 403
    assert not VotingVoter.objects.filter(voting=voting, voter=voter).exists()


@pytest.mark.django_db
def test_voter_registration_still_works_for_existing_voter(client, voting):
    # Voter with member_id=1 is already part of the fixture voting
    voter = Voter.objects.get(member_id=1)
    token = compute_member_token(1)
    voting.new_round()
    url = reverse(
        "voting:voter-registration",
        kwargs={"voting_id": voting.id, "member_id": 1, "auth_token": token},
    )
    response = client.post(url, {"attending": "on", "bid_round_1": "42"})
    assert response.status_code == 302
    vv = VotingVoter.objects.get(voting=voting, voter=voter)
    assert vv.absent_from_round is None
    assert voting.bids.filter(member_id=1, round_number=1).first().amount == Decimal("42")


@pytest.mark.django_db
def test_import_bids_csv_blocked_after_round_started(voting):
    voting.new_round()
    with pytest.raises(ValueError, match="erste Runde"):
        voting.import_bids_csv(["500,1,2"])


@pytest.mark.django_db
def test_voting_voter_model_clean_blocks_after_round_started(voting):
    voting.new_round()
    new_voter = make_voter(700, "Late Joiner")
    vv = VotingVoter(voting=voting, voter=new_voter)
    with pytest.raises(ValidationError):
        vv.full_clean()


@pytest.mark.django_db
def test_voting_voter_model_clean_allows_before_round_started(voting):
    new_voter = make_voter(701, "Early Bird")
    vv = VotingVoter(voting=voting, voter=new_voter)
    vv.full_clean()  # must not raise
