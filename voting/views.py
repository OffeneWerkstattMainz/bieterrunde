import random
import string
from csv import DictWriter
from io import StringIO

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.text import slugify
from guest_user.decorators import allow_guest_user, guest_user_required

from voting.forms import VotingForm, VoteForm
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
        return render(request, "voting/voting_create.html", dict(form=VotingForm()))


@guest_user_required()
def voting_manage(request, voting_id):
    voting = get_voting_or_index(request, voting_id)
    if request.htmx:
        return render(request, "voting/frag_manage_round_info.html", dict(voting=voting))
    return render(request, "voting/voting_manage.html", dict(voting=voting))


def voting_info(request, voting_id):
    voting = Voting.objects.get(pk=voting_id)
    if request.htmx:
        if request.htmx.trigger == "round-info":
            return render(request, "voting/frag_round_info.html", dict(voting=voting))
        else:
            raise ValueError("Unknown trigger")
    return render(
        request, "voting/voting_info.html", dict(voting=voting, host=request.META["HTTP_HOST"])
    )


@guest_user_required()
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


def voting_export(request, voting_id):
    voting = Voting.objects.get(pk=voting_id)
    voting_round = voting.rounds.order_by("-round_number")[0]
    if not voting_round.is_complete:
        raise ValueError("Voting round is not complete")
    if voting_round.budget_result["result"] < voting.budget_goal:
        raise ValueError("Budget goal not reached")
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
