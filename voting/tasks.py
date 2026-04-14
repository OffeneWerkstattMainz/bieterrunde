from django.conf import settings
from django_tasks import task

from voting.models import VotingVoter
from logging import getLogger

from voting.utils.webling_api import WeblingAPI

log = getLogger(__name__)


@task()
def update_member_assembly_participation(voting_voter_id: int) -> None:
    vv = VotingVoter.objects.get(id=voting_voter_id)
    with WeblingAPI(settings.WEBLING_API_KEY) as api:
        member_id = api.get_member_id_by_mitglieder_id(vv.voter.member_id)
        is_participating = vv.absent_from_round is None
        api.update_member_assembly_participation(member_id, is_participating)
        log.info(
            f"Updated member assembly participation {vv.voter.member_id} ({member_id}) -> {is_participating}"
        )
