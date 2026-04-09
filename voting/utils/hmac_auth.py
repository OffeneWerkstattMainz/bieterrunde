import base64
import hashlib
import hmac

from django.conf import settings


def compute_member_token(member_id: int) -> str:
    """Compute SHA256-HMAC of member_id using Django SECRET_KEY."""
    return base64.urlsafe_b64encode(
        hmac.new(
            settings.SECRET_KEY.encode(),
            str(member_id).encode(),
            hashlib.sha256,
        ).digest()
    ).decode()


def verify_member_token(member_id: int, token: str) -> bool:
    """Verify an HMAC token for a member_id (constant-time comparison)."""
    return hmac.compare_digest(compute_member_token(member_id), token)
