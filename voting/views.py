import codecs
import csv
import random
import string
from csv import DictWriter, DictReader
from http import HTTPStatus

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.text import slugify
from django_htmx.http import HttpResponseClientRefresh
from guest_user.decorators import allow_guest_user, guest_user_required

from voting.forms import VotingForm, VoteForm, BidImportForm
from voting.models import Voting, VotingRound


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
    if request.method != "POST":
        return redirect("voting:manage", voting_id)
    try:
        voting.new_round()
    except ValueError as e:
        messages.error(
            request,
            f"Neue Runde kann nicht angelegt werden, vorherige Runde ist nicht abgeschlossen.",
        )
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
