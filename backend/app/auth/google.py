"""Turning a Google sign-in into an identity we are prepared to believe.

The browser hands us an ID token from Google Identity Services. Everything the rest of the
system knows about who is signing in comes out of this module, so it does two separate jobs and
keeps them separate:

1. **Is this token genuine?** Signature against Google's published keys, audience is our client
   id, issuer is Google, not expired. google-auth does all of that; we do not hand-roll JWT
   checks for a token someone else signs.
2. **Is this person allowed to knock?** Verified address, on our domain, in our Workspace.

Passing both only earns an account in PENDING. Whether they get *in* is an admin's decision,
made in app/services/access.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)

GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleAuthError(Exception):
    """The token itself could not be trusted — forged, expired, meant for another app."""


class DomainNotAllowed(Exception):
    """A genuine Google account, but not one of ours."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str
    picture: str | None
    hosted_domain: str | None
    email_verified: bool


def verify_credential(credential: str) -> GoogleIdentity:
    """Check the token is genuine and return what it says. Says nothing yet about domain."""
    if not credential or len(credential) > 8192:
        raise GoogleAuthError("Missing or malformed credential")

    if settings.google_auth_backend.lower() == "stub":
        return _stub_identity(credential)

    # Imported here so the stub path, and the test suite, never need the network stack.
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=settings.google_client_id,
            clock_skew_in_seconds=10,
        )
    except ValueError as exc:      # google-auth raises ValueError for every rejection
        logger.info("rejected Google credential: %s", exc)
        raise GoogleAuthError("Google sign-in could not be verified") from exc

    # verify_oauth2_token already checks this; asserting it again costs nothing and means a
    # change in the library's defaults cannot quietly widen who we accept.
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleAuthError("Token was not issued by Google")

    return identity_from_claims(claims)


def identity_from_claims(claims: dict) -> GoogleIdentity:
    email = str(claims.get("email") or "").strip().lower()
    sub = str(claims.get("sub") or "")
    if not email or not sub:
        raise GoogleAuthError("Google did not return an email address for this account")
    return GoogleIdentity(
        sub=sub,
        email=email,
        name=str(claims.get("name") or email.split("@")[0]),
        picture=claims.get("picture"),
        hosted_domain=(claims.get("hd") or None),
        # Google sends a bool; older tokens sent the string "true".
        email_verified=claims.get("email_verified") in (True, "true"),
    )


def enforce_domain(identity: GoogleIdentity) -> None:
    """Only verified addresses on our domain, belonging to our Workspace.

    Three checks, each closing a different gap:

    - `email_verified` — Google has confirmed the person controls the address.
    - the address ends in @<domain> — the obvious one.
    - `hd` equals <domain> — set by Google from the Workspace the account lives in. It is what
      stops a consumer Google account that merely *uses* an @ecolinksolutions.in address as its
      login, which is possible for addresses outside Workspace. Ecolink's mail is on Workspace,
      so a real colleague always carries it.
    """
    domain = settings.allowed_email_domain.strip().lower()
    if not identity.email_verified:
        raise DomainNotAllowed("This Google account's email address is not verified.")
    if not identity.email.endswith("@" + domain):
        raise DomainNotAllowed(f"Only @{domain} Google accounts can sign in.")
    if (identity.hosted_domain or "").lower() != domain:
        raise DomainNotAllowed(
            f"Only accounts in the {domain} Google Workspace can sign in."
        )


def _stub_identity(credential: str) -> GoogleIdentity:
    """Local development only: `stub:<email>` or `stub:<email>|<name>`.

    It deliberately claims `hd` from the address it was given, so the domain rule still bites
    in development — typing a gmail.com address is refused exactly as it would be for real.
    check_sign_in_config() refuses to start with this backend outside a local environment.
    """
    if not settings.is_local:     # belt and braces; startup should already have refused
        raise GoogleAuthError("Stub sign-in is disabled outside local development")
    if not credential.startswith("stub:"):
        raise GoogleAuthError("Stub backend expects 'stub:<email>'")

    email, _, name = credential[len("stub:"):].partition("|")
    email = email.strip().lower()
    if "@" not in email:
        raise GoogleAuthError("Stub credential needs an email address")
    return GoogleIdentity(
        sub=f"stub-{email}",
        email=email,
        name=name.strip() or email.split("@")[0].replace(".", " ").title(),
        picture=None,
        hosted_domain=email.split("@", 1)[1],
        email_verified=True,
    )
