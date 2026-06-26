from functools import partial

import djclick
from django.core.management import CommandError
from djclick.params import ModelInstance

from voting.models import VotingRound, Voter
from voting.utils.webling_api import WeblingAPI, PROP_MEMBER_ID, PROP_MISSING_VOTING_ROUNDS

_R = partial(djclick.style, fg="red")
_G = partial(djclick.style, fg="green")
_B = partial(djclick.style, fg="blue")
_Y = partial(djclick.style, fg="yellow")


@djclick.command()
@djclick.argument("voting-round-id", type=ModelInstance(VotingRound))
@djclick.option("--api-key", required=True, help="API key for Webling", envvar="WEBLING_API_KEY")
@djclick.option(
    "--missing-voting-key-name",
    required=True,
    help="Name of the key to set on members for missing voting rounds. e.g. '2026-06'",
)
@djclick.option(
    "--webling-group-id", type=int, help="Webling group ID to export to, if missing prompt user"
)
@djclick.option(
    "--use-voters",
    is_flag=True,
    help="Use locally known voters instead of fetching members from Webling",
)
@djclick.option(
    "--override-average-contribution", type=int, help="Override average contribution value"
)
@djclick.option("-n", "--dry-run", is_flag=True, help="Do not actually export anything")
def command(
    voting_round_id: VotingRound,
    api_key: str,
    dry_run: bool,
    use_voters: bool,
    missing_voting_key_name: str,
    webling_group_id: int | None,
    override_average_contribution: int | None,
):
    if dry_run:
        djclick.secho("DRY RUN - NO DATA WILL BE CHANGED", fg="red")
    djclick.confirm(
        f"{_Y('Are you sure you want to export the voting round')} '{_G(voting_round_id)}'?",
        abort=True,
    )
    api = WeblingAPI(api_key)
    with api:
        if not use_voters:
            membergroups = api.fetch_membergroups()

            if not webling_group_id:
                djclick.secho("Member groups found:", fg="green")
                for group_id, group in membergroups.items():
                    djclick.echo(
                        f"  - {_Y(group_id)}: {_G(group.title)} ({_B(len(group.members))} members)"
                    )
                group_id = djclick.prompt("Select the member group to export to", type=int)
            else:
                group_id = webling_group_id
                djclick.echo(
                    f"{_G('Using Webling group')} {_Y(group_id)} - {_G(membergroups[group_id].title)} ({_B(len(membergroups[group_id].members))} members)"
                )

            if group_id not in membergroups:
                djclick.secho("Invalid member group ID", fg="red")
                return

            group_members = api.fetch_members_by_group_id(group_id)
        else:
            voter_member_ids = ",".join(str(v.member_id) for v in Voter.objects.all())
            group_members = api.fetch_members_by_filter(f"`Mitglieder ID` IN ({voter_member_ids})")

        # The internal and "public" member IDs are different
        group_member_member_ids = set(
            member["properties"][PROP_MEMBER_ID] for member in group_members.values()
        )
        voting_members = set(voting_round_id.votes.values_list("member_id", flat=True))
        superfluous_members = voting_members - group_member_member_ids
        if superfluous_members:
            djclick.secho("Members in voting but not in Webling:", fg="red")
            for member_id in sorted(superfluous_members):
                djclick.secho(f"- {member_id}", fg="red")
            raise CommandError("Members in voting but not in Webling")
        average_contribution = round(voting_round_id.voting.average_contribution_target)
        if override_average_contribution:
            djclick.echo(
                _Y("Overriding average contribution to ")
                + _B(f"{override_average_contribution} €"),
            )
            average_contribution = override_average_contribution

        djclick.echo(
            _G("Pre-export summary:")
            + _B("\n  - Total users: ")
            + _Y(str(len(group_members)))
            + _B("\n  - Voting users: ")
            + _Y(str(len(voting_members)))
            + _B("\n  - Non voting users (auto assigning average value): ")
            + _Y(str(len(group_members) - len(voting_members)))
            + _B("\n  - Average value: ")
            + _Y(f"{average_contribution:.2f} €")
        )

        djclick.confirm("Do you want to continue?", abort=True)

        votes = {
            member_id: round(amount)
            for member_id, amount in voting_round_id.votes.values_list("member_id", "amount")
        }

        new_contribution_values = {
            member_api_id: votes.get(member["properties"][PROP_MEMBER_ID], average_contribution)
            for member_api_id, member in group_members.items()
        }

        with djclick.progressbar(
            new_contribution_values.items(), label=_Y("Exporting...")
        ) as new_contribution_values_progress:
            for member_api_id, amount in new_contribution_values_progress:
                if not dry_run:
                    api.update_member_contribution(member_api_id, amount)

        non_voting_member_api_ids = [
            member["id"]
            for member in group_members.values()
            if member["properties"][PROP_MEMBER_ID] not in voting_members
        ]

        if non_voting_member_api_ids:
            with djclick.progressbar(
                non_voting_member_api_ids, label=_Y("Updating non-voting members...")
            ) as non_voting_member_api_ids_progress:
                for member_api_id in non_voting_member_api_ids_progress:
                    not_voted_assemblies = group_members[member_api_id]["properties"].get(
                        PROP_MISSING_VOTING_ROUNDS
                    )
                    if not not_voted_assemblies:
                        not_voted_assemblies = [missing_voting_key_name]
                    else:
                        not_voted_assemblies = list(
                            set(not_voted_assemblies + [missing_voting_key_name])
                        )
                    if not dry_run:
                        api.set_member_non_voting(member_api_id, not_voted_assemblies)

    if dry_run:
        djclick.secho("DRY RUN - NO DATA HAS BEEN CHANGED", fg="red")
