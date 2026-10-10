"""Read authoritative account status; never cache an allow decision across requests."""

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Reject before urllib can forward the client's Basic credentials.
        return None


class AccountStatusUnavailable(RuntimeError):
    pass


def read_account_status(issuer, client_id, client_secret, sub):
    parsed = urlsplit(issuer)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise AccountStatusUnavailable("Account status endpoint must use HTTPS")
    if not client_id or not client_secret or not sub:
        return {"active": False, "emailVerified": False}
    authorization = base64.b64encode(
        (client_id + ":" + client_secret).encode()
    ).decode()
    request = Request(
        issuer.rstrip("/") + "/api/client/account-status?" + urlencode({"sub": sub}),
        headers={
            "Authorization": "Basic " + authorization,
            "Accept": "application/json",
            "User-Agent": "NetHub-AccountStatus/1.0",
        },
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=3) as response:
            # Account service never redirects; do not accept a redirected success.
            if response.geturl() != request.full_url:
                raise AccountStatusUnavailable("Unexpected account status redirect")
            raw = response.read(4097)
            if len(raw) > 4096:
                raise ValueError("Response too large")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Invalid account status response")
            if (
                type(data.get("active")) is not bool
                or type(data.get("emailVerified")) is not bool
            ):
                raise ValueError("Invalid account status response")
            return {"active": data["active"], "emailVerified": data["emailVerified"]}
    except HTTPError as exc:
        if exc.code == 404:
            return {"active": False, "emailVerified": False}
        raise AccountStatusUnavailable("Account status unavailable") from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise AccountStatusUnavailable("Account status unavailable") from None
