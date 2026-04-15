import sys
from functools import partial

import djclick
from django.core.management import CommandError

from django.conf import settings
from voting.models import Voter
from voting.utils.hmac_auth import compute_member_token
from voting.utils.webling_api import WeblingAPI


_R = partial(djclick.style, fg="red")
_G = partial(djclick.style, fg="green")
_B = partial(djclick.style, fg="blue")
_Y = partial(djclick.style, fg="yellow")


@djclick.command()
@djclick.option(
    "--api-key",
    help="Webling API, by default will be tried to be loaded from settings.",
    envvar="WEBLING_API_KEY",
)
@djclick.option(
    "--webling-group-id",
    type=int,
    help="Webling group ID to import from, if missing prompt user (unless --webling-filter is specified)",
)
@djclick.option(
    "--webling-filter",
    type=str,
    help="Webling user filter expression, used instead of --webling-group-id",
)
@djclick.option("-n", "--dry-run", is_flag=True, help="Do not actually write anything")
def command(
    api_key: str | None, webling_group_id: int | None, webling_filter: str | None, dry_run: bool
):
    """Import Voter objects from Webling and write HMAC auth tokens back."""
    if webling_group_id and webling_filter:
        raise CommandError(
            "The options '--webling-group-id' and '--webling-filter' are mutually exclusive."
        )
    if dry_run:
        djclick.secho("DRY RUN - NO DATA WILL BE CHANGED", fg="red")

    if not api_key:
        api_key = settings.WEBLING_API_KEY

    if not api_key:
        raise CommandError("Webling API key is required (either via settings or CLI parameter)")

    api = WeblingAPI(api_key)
    with api:
        if not webling_group_id and not webling_filter:
            membergroups = api.fetch_membergroups()
            djclick.secho("Member groups found:", fg="green")
            for group_id, group in membergroups.items():
                djclick.echo(
                    f"  - {_Y(group_id)}: {_G(group.title)} ({_B(len(group.members))} members)"
                )
            webling_group_id = djclick.prompt("Select the member group to import from", type=int)
            members = api.fetch_members_by_group_id(webling_group_id)
        elif webling_filter:
            members = api.fetch_members_by_filter(webling_filter)

        if not members:
            djclick.secho("No members found", fg="red")
            sys.exit(1)

        djclick.echo(f"{_G('Importing')} {_B(len(members))} {_G('members...')}")

        created = 0
        updated = 0

        with djclick.progressbar(members.items(), label=_Y("Importing...")) as progress:
            for api_id, member in progress:
                props = member["properties"]
                member_id = props["Mitglieder ID"]
                name_parts = [props.get("Vorname", ""), props.get("Name", "")]
                name = " ".join(p for p in name_parts if p) or f"Mitglied {member_id}"

                if not dry_run:
                    _, was_created = Voter.objects.update_or_create(
                        member_id=member_id,
                        defaults={"name": name},
                    )
                    if was_created:
                        created += 1
                    else:
                        updated += 1

                    # Compute and write auth token to Webling
                    token = compute_member_token(member_id)
                    api.update_member_auth_token(api_id, token)

        djclick.echo(
            f"\n{_G('Done.')} {_B(created)} {_G('created,')} {_B(updated)} {_G('updated.')}"
        )

    if dry_run:
        djclick.secho("DRY RUN - NO DATA HAS BEEN CHANGED", fg="red")
