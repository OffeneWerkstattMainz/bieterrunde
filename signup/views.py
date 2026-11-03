from http import HTTPStatus

from django.conf import settings
from django.core import signing
from django.shortcuts import redirect, render

from core.webling_api import WeblingAPI
from signup.services import (
    PROP_FIRSTNAME,
    confirm_member,
    confirmed_group_id,
    member_email,
    pending_group_id,
    read_token,
)


def confirm(request, token):
    try:
        member_id, email = read_token(token)
    except signing.SignatureExpired:
        return render(
            request, "signup/confirm.html", dict(state="expired"), status=HTTPStatus.GONE
        )
    except signing.BadSignature:
        return render(
            request, "signup/confirm.html", dict(state="invalid"), status=HTTPStatus.NOT_FOUND
        )

    with WeblingAPI(settings.WEBLING_API_KEY) as api:
        member = api.fetch_member(member_id)
        parents = member.get("parents", []) if member else []
        if member is None or member_email(member) != email:
            # Deleted after expiry or e-mail address changed in the meantime
            state = "expired"
        elif confirmed_group_id() in parents:
            state = "done"
        elif pending_group_id() not in parents:
            state = "expired"
        elif request.method == "POST":
            confirm_member(api, member)
            return redirect("signup:confirm", token)
        else:
            state = "confirm"

    status = HTTPStatus.GONE if state == "expired" else HTTPStatus.OK
    firstname = (member["properties"].get(PROP_FIRSTNAME) or "").strip() if member else ""
    return render(
        request, "signup/confirm.html", dict(state=state, firstname=firstname), status=status
    )
