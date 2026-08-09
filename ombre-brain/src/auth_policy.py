"""Authentication policy helpers for the public MCP endpoint.

OAuth remains the primary authentication mechanism for interactive clients.
An optional, high-entropy service token is accepted for trusted sidecars such
as Xinchao, which cannot complete an interactive OAuth authorization flow.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable


MIN_SERVICE_TOKEN_LENGTH = 32


def build_mcp_token_validator(
    oauth_validator: Callable[[str, str], bool],
    *,
    service_token: str | None = None,
) -> Callable[[str, str], bool]:
    """Return a validator that accepts OAuth or a strong sidecar token.

    A missing or short service token is deliberately ignored. This keeps an
    accidental empty/default value from becoming an authentication bypass.
    """

    configured = (
        os.environ.get("OMBRE_MCP_SERVICE_TOKEN", "")
        if service_token is None
        else service_token
    ).strip()
    service_token_enabled = len(configured) >= MIN_SERVICE_TOKEN_LENGTH

    def validate(token: str, resource: str = "") -> bool:
        candidate = (token or "").strip()
        if (
            service_token_enabled
            and len(candidate) == len(configured)
            and hmac.compare_digest(candidate, configured)
        ):
            return True
        return bool(oauth_validator(candidate, resource))

    return validate
