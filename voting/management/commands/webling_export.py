from functools import partial
from pprint import pprint

import click
import djclick
import httpx
from django.core.management import CommandError
from djclick.params import ModelInstance

from voting.models import VotingRound


API_BASE = "https://owm.webling.ch/api/1"


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

        def _always_yes(x):
            print()
            return "y"

        click.termui.visible_prompt_func = _always_yes

    djclick.confirm(
        f"{_Y('Are you sure you want to export the voting round')} '{_G(voting_round_id)}'?",
        abort=True,
    )
    api = WeblingAPI(api_key)
    with api:
        membergroups = api.fetch_membergroups()

        if not webling_group_id:
            djclick.secho("Member groups found:", fg="green")
            for group_id, (title, members) in membergroups.items():
                djclick.echo(f"  - {_Y(group_id)}: {_G(title)} ({_B(len(members))} members)")
            group_id = djclick.prompt("Select the member group to export to", type=int)
        else:
            group_id = webling_group_id
            djclick.echo(
                f"{_G('Using Webling group')} {_Y(group_id)} - {_G(membergroups[group_id][0])} ({_B(len(membergroups[group_id][1]))} members)"
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
            + _B("\n  - Average value users: ")
            + _Y(str(len(group_members) - len(voting_members)))
            + _B("\n  - Average value: ")
            + _Y(f"{average_contribution:.2f} €")
        )

        djclick.confirm("Do you want to continue?", abort=True)

        votes = dict(
            (member_id, round(amount))
            for member_id, amount in voting_round_id.votes.values_list("member_id", "amount")
        )

        new_contribution_values = {
            member_id: votes.get(member["properties"]["Mitglieder ID"], average_contribution)
            for member_id, member in group_members.items()
        }

        with djclick.progressbar(
            new_contribution_values.items(), label=_Y("Exporting...")
        ) as new_contribution_values_progress:
            for member_id, amount in new_contribution_values_progress:
                if not dry_run:
                    api.update_member_contribution(member_id, amount)


class WeblingAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def __enter__(self):
        self.client = httpx.Client()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    def fetch_membergroups(self) -> dict[int, tuple[str, list[int]]]:
        response = self.client.get(
            f"{API_BASE}/membergroup", headers={"apikey": self.api_key}, params={"format": "full"}
        )
        response.raise_for_status()

        return {
            group["id"]: (
                group["properties"]["title"],
                group.get("children", {}).get("member", []),
            )
            for group in response.json()
        }

    def fetch_members(self, parent_group: int) -> dict[int, dict]:
        response = self.client.get(
            f"{API_BASE}/member",
            headers={"apikey": self.api_key},
            params={"format": "full", "filter": f"$parents.$id={parent_group}"},
        )
        response.raise_for_status()

        return {member["id"]: member for member in response.json()}

    def update_member_contribution(self, member_id: int, contribution: int):
        response = self.client.put(
            f"{API_BASE}/member/{member_id}",
            headers={"apikey": self.api_key},
            json={"properties": {"Mitgliederbeitrag": contribution}},
        )
        response.raise_for_status()
