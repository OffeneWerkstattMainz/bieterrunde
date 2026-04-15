import random
import string
from csv import DictWriter
from http import HTTPStatus

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.formats import localize
from django.utils.text import slugify
from django_htmx.http import HttpResponseClientRefresh
from guest_user.decorators import allow_guest_user

from voting.forms import (
    VotingForm,
    VoteForm,
    BidImportForm,
    VoterRegistrationForm,
    VotingVoterAddForm,
    VotingVoterQuickAddForm,
    VotingVoterEditForm,
)
from voting.models import Bid, Voter, Voting, VotingRound, VotingVoter
from voting.utils.hmac_auth import verify_member_token


def get_voting_or_index(request, voting_id):
    voting = Voting.objects.get(pk=voting_id)
    if request.user != voting.owner:
        messages.error(request, "Du bist nicht der Besitzer dieses Votings")
        return redirect("voting:index")
    return voting


def index(request):
    votings = Voting.objects.filter(owner=request.user) if request.user.is_authenticated else []
    return render(request, "voting/index.html", dict(votings=votings))


@allow_guest_user()
def voting_create(request):
    if request.method == "POST":
        form = VotingForm(request.POST)
        if form.is_valid():
            voting = form.save(commit=False)
            voting.owner = request.user
            voting.save()
            return redirect("voting:manage", voting.id)
        else:
            return render(request, "voting/voting_create.html", dict(form=form))
    else:
        if (
            settings.CREATE_VOTING_ACCESS_CODE
            and request.GET.get("code") != settings.CREATE_VOTING_ACCESS_CODE
        ):
            messages.error(request, "Zugangscode benötigt.")
            return redirect("voting:index")
        return render(request, "voting/voting_create.html", dict(form=VotingForm()))


@allow_guest_user()
def voting_manage(request, voting_id):
    voting = get_voting_or_index(request, voting_id)
    if isinstance(voting, HttpResponse):
        return voting
    if request.htmx:
        return render(request, "voting/htmx/voting_manage.html", dict(voting=voting))
    return render(request, "voting/voting_manage.html", dict(voting=voting))


def voting_info(request, voting_id):
    voting = Voting.objects.get(pk=voting_id)
    if request.htmx:
        if request.htmx.trigger == "round-info":
            return render(request, "voting/tags/round_info.html", dict(voting=voting))
        else:
            raise ValueError("Unknown trigger")
    return render(
        request, "voting/voting_info.html", dict(voting=voting, host=request.META["HTTP_HOST"])
    )


@allow_guest_user()
def voting_import_bids(request, voting_id):
    if not request.htmx:
        return redirect("voting:manage", voting_id)

    voting = get_voting_or_index(request, voting_id)
    if isinstance(voting, HttpResponse):
        return voting
    if request.method == "POST":
        form = BidImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(
                request,
                "voting/htmx/manage_import_bids.html",
                dict(form=form, open=True, voting=voting),
            )
        # Not optimal, but should be fine for a small number of rows
        bids_lines = request.FILES["bids"].read().decode("utf-8").splitlines()
        try:
            voting.import_bids_csv(bids_lines)
        except (ValueError, IntegrityError) as e:
            messages.error(request, str(e))
            return render(request, "voting/htmx/manage_import_bids.html", {})
        return HttpResponseClientRefresh()
    return render(
        request,
        "voting/htmx/manage_import_bids.html",
        dict(form=BidImportForm(), voting=voting, open=True),
    )


@allow_guest_user()
def voting_new_round(request, voting_id):
    voting = get_voting_or_index(request, voting_id)
    if isinstance(voting, HttpResponse):
        return voting
    if request.method != "POST":
        return redirect("voting:manage", voting_id)
    try:
        voting.new_round()
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("voting:manage", voting.id)


def voting_vote(request, voting_id, voting_round_id=None):
    voting = Voting.objects.get(pk=voting_id)
    active_round = voting.active_round
    if request.method == "POST":
        form = VoteForm(request.POST)
        voting_round = VotingRound.objects.get(pk=voting_round_id)
        if not voting_round.is_complete:
            if form.is_valid():
                vote = form.save(commit=False)
                assert vote.voting_round == voting_round == active_round
                vote.save()
                if voting_round.is_complete:
                    voting_round.active = False
                    voting_round.save()
                messages.success(request, "Deine Stimme wurde gespeichert.")
                return redirect("voting:vote", voting.id)
        return render(request, "voting/voting_vote.html", dict(voting=voting, form=form))
    else:
        if request.htmx and active_round and active_round.id == voting_round_id:
            # If it's an htmx request with the same round id as the active one (meaning the user hasn't sent the form yet)
            # return 204 to prevent the form from being replaced (and potentially losing user input)
            return HttpResponse(status=HTTPStatus.NO_CONTENT)
        return render(
            request,
            "voting/voting_vote.html",
            dict(
                voting=voting,
                form=VoteForm(initial={"voting_round": active_round}),
                cb="".join(random.choices(string.ascii_letters + string.digits, k=10)),
            ),
        )


@allow_guest_user()
def voting_export(request, voting_id: str, round_id: int = None):
    voting = get_voting_or_index(request, voting_id)
    if isinstance(voting, HttpResponse):
        return voting
    if round_id:
        voting_round = voting.rounds.get(pk=round_id)
    else:
        voting_round = voting.active_or_last_round
    if not voting_round.is_complete:
        messages.error(request, "Die Runde ist nicht abgeschlossen.")
        return HttpResponse(status=HTTPStatus.NO_CONTENT)
    if voting_round.budget_result["result"] < voting.budget_goal:
        messages.warning(request, "Ziel-Budget nicht erreicht.")
    response = HttpResponse(
        content_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=bieterrunde-export"
                f"-{slugify(voting.name)}"
                f"-{timezone.now().isoformat(timespec='seconds')}.csv"
            )
        },
    )
    writer = DictWriter(response, fieldnames=["member_id", "amount"])
    writer.writeheader()
    for vote in voting_round.votes.all():
        writer.writerow({"member_id": vote.member_id, "amount": vote.amount})
    return response


def _render_voters_list(request, voting):
    voting_voters = (
        VotingVoter.objects.filter(voting=voting)
        .select_related("voter")
        .order_by("voter__member_id")
    )
    voter_list = []
    for vv in voting_voters:
        vv.bid_count = Bid.objects.filter(voting=voting, member_id=vv.voter.member_id).count()
        voter_list.append(vv)
    return render(
        request,
        "voting/htmx/manage_voters.html",
        dict(voting=voting, voting_voters=voter_list, open=True),
    )


@allow_guest_user()
def voting_voters(request, voting_id):
    if not request.htmx:
        return redirect("voting:manage", voting_id)
    voting = get_voting_or_index(request, voting_id)
    if isinstance(voting, HttpResponse):
        return voting
    return _render_voters_list(request, voting)


@allow_guest_user()
def voting_voter_add(request, voting_id):
    if not request.htmx:
        return redirect("voting:manage", voting_id)
    voting = get_voting_or_index(request, voting_id)
    if isinstance(voting, HttpResponse):
        return voting
    if request.method == "POST":
        form = VotingVoterAddForm(request.POST, voting=voting)
        if not form.is_valid():
            return render(
                request,
                "voting/htmx/manage_voter_add.html",
                dict(form=form, open=True, voting=voting),
            )
        member_id = form.cleaned_data["member_id"]
        absent_from_round = form.cleaned_data.get("absent_from_round")
        voter = Voter.objects.get(member_id=member_id)
        VotingVoter.objects.create(voting=voting, voter=voter, absent_from_round=absent_from_round)
        for round_number, amount in form.get_bids().items():
            Bid.objects.update_or_create(
                voting=voting,
                member_id=member_id,
                round_number=round_number,
                defaults={"amount": amount},
            )
        return _render_voters_list(request, voting)
    return render(
        request,
        "voting/htmx/manage_voter_add.html",
        dict(form=VotingVoterAddForm(voting=voting), voting=voting, open=True),
    )


@allow_guest_user()
def voting_voter_quick_add(request, voting_id):
    if not request.htmx:
        return redirect("voting:manage", voting_id)
    voting = get_voting_or_index(request, voting_id)
    if isinstance(voting, HttpResponse):
        return voting
    if request.method == "POST":
        quick_form = VotingVoterQuickAddForm(request.POST, voting=voting)
        if not quick_form.is_valid():
            return render(
                request,
                "voting/htmx/manage_voter_quick_add.html",
                dict(quick_form=quick_form, open=True, voting=voting),
            )
        member_ids = quick_form.cleaned_data["member_ids"]
        voters = Voter.objects.filter(member_id__in=member_ids)
        for voter in voters:
            VotingVoter.objects.create(voting=voting, voter=voter)
        return _render_voters_list(request, voting)
    return render(
        request,
        "voting/htmx/manage_voter_quick_add.html",
        dict(quick_form=VotingVoterQuickAddForm(voting=voting), voting=voting, open=True),
    )


@allow_guest_user()
def voting_voter_edit(request, voting_id, voting_voter_id):
    if not request.htmx:
        return redirect("voting:manage", voting_id)
    voting = get_voting_or_index(request, voting_id)
    if isinstance(voting, HttpResponse):
        return voting
    voting_voter = get_object_or_404(VotingVoter, pk=voting_voter_id, voting=voting)
    if request.method == "POST":
        form = VotingVoterEditForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "voting/htmx/manage_voter_edit.html",
                dict(form=form, open=True, voting=voting, voting_voter=voting_voter),
            )
        voting_voter.absent_from_round = form.cleaned_data.get("absent_from_round")
        voting_voter.save()
        voter = voting_voter.voter
        voter.name = form.cleaned_data["name"]
        voter.save()
        submitted_bids = form.get_bids()
        for round_number, amount in submitted_bids.items():
            Bid.objects.update_or_create(
                voting=voting,
                member_id=voter.member_id,
                round_number=round_number,
                defaults={"amount": amount},
            )
        Bid.objects.filter(voting=voting, member_id=voter.member_id).exclude(
            round_number__in=submitted_bids.keys()
        ).delete()
        return _render_voters_list(request, voting)
    existing_bids = dict(
        Bid.objects.filter(voting=voting, member_id=voting_voter.voter.member_id).values_list(
            "round_number", "amount"
        )
    )
    initial = {
        "name": voting_voter.voter.name,
        "absent_from_round": voting_voter.absent_from_round,
    }
    for round_number, amount in existing_bids.items():
        initial[f"bid_round_{round_number}"] = amount
    form = VotingVoterEditForm(initial=initial)
    return render(
        request,
        "voting/htmx/manage_voter_edit.html",
        dict(form=form, open=True, voting=voting, voting_voter=voting_voter),
    )


def voter_registration(request, voting_id, member_id, auth_token):
    if not verify_member_token(member_id, auth_token):
        return HttpResponseForbidden("Ungültiger Authentifizierungstoken.")

    voting = get_object_or_404(Voting, pk=voting_id)
    voter = get_object_or_404(Voter, member_id=member_id)
    voting_voter = VotingVoter.objects.filter(voting=voting, voter=voter).first()
    vv_missing = voting_voter is None
    if vv_missing:
        if voting.rounds_started:
            return HttpResponseForbidden(
                "Registrierung ist nicht mehr möglich, da die erste Runde bereits begonnen hat."
            )

    if request.method == "POST":
        if vv_missing:
            voting_voter = VotingVoter.objects.create(voting=voting, voter=voter)

        form = VoterRegistrationForm(request.POST)
        if form.is_valid():
            attending = form.cleaned_data["attending"]
            voting_voter.absent_from_round = None if attending else 1
            voting_voter.save()

            for round_number, amount in form.get_bids().items():
                Bid.objects.update_or_create(
                    voting=voting,
                    member_id=member_id,
                    round_number=round_number,
                    defaults={"amount": amount},
                )

            messages.success(request, "Deine Angaben wurden gespeichert.")
            return redirect(
                "voting:voter-registration",
                voting_id=voting_id,
                member_id=member_id,
                auth_token=auth_token,
            )
    else:
        existing_bids = dict(
            voting.bids.filter(member_id=member_id).values_list("round_number", "amount")
        )
        initial = {"attending": False if vv_missing else voting_voter.absent_from_round is None}
        for round_number, amount in existing_bids.items():
            initial[f"bid_round_{round_number}"] = amount
        form = VoterRegistrationForm(initial=initial)
        target_bid = localize(voting.average_contribution_target, use_l10n=True)
        form.fields["bid_round_1"].widget.attrs.update({"placeholder": f"Richtwert: {target_bid}"})

    return render(
        request,
        "voting/voter_registration.html",
        dict(voting=voting, voter=voter, voting_voter=voting_voter, form=form),
    )
