from functools import partial

import djclick
from django.core.management import CommandError
from djclick.params import ModelInstance

from voting.models import VotingRound
from voting.utils.webling_api import WeblingAPI


_R = partial(djclick.style, fg="red")
_G = partial(djclick.style, fg="green")
_B = partial(djclick.style, fg="blue")
_Y = partial(djclick.style, fg="yellow")


@djclick.command()
@djclick.argument("voting-round-id", type=ModelInstance(VotingRound))
@djclick.option("--api-key", required=True, help="API key for Webling", envvar="WEBLING_API_KEY")
@djclick.option(
    "--webling-group-id", type=int, help="Webling group ID to export to, if missing prompt user"
)
@djclick.option(
    "--override-average-contribution", type=int, help="Override average contribution value"
)
@djclick.option("-n", "--dry-run", is_flag=True, help="Do not actually export anything")
def command(
    voting_round_id: VotingRound,
    api_key: str,
    dry_run: bool,
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

        group_members = api.fetch_members(group_id)

        # The internal and "public" member IDs are different
        group_member_member_ids = set(
            member["properties"]["Mitglieder ID"] for member in group_members.values()
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
            member_api_id: votes.get(member["properties"]["Mitglieder ID"], average_contribution)
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
            if member["properties"]["Mitglieder ID"] not in voting_members
        ]
        if non_voting_member_api_ids:
            group_title = f"Kein Gebot - {voting_round_id.voting.name}"
            djclick.echo(
                f"{_Y('Creating new member group')} '{_G(group_title)}' {_Y('for non-voting users')}"
            )
            if not dry_run:
                api.create_member_group(
                    non_voting_member_api_ids, group_title, parent_group_id=group_id
                )

    if dry_run:
        djclick.secho("DRY RUN - NO DATA HAS BEEN CHANGED", fg="red")
