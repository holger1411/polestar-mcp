"""
Polestar OIDC/PKCE Authentication.

Handles the full OAuth2 flow against Polestar's PingFederate-based OIDC provider:
1. Discover OIDC endpoints via .well-known
2. Generate PKCE code verifier/challenge
3. GET authorization endpoint → receive login page with resume path
4. POST username to resume path
5. POST password to resume path
6. Follow redirects to capture authorization code
7. Exchange code for tokens
8. Auto-refresh tokens before expiry
"""

import base64
import hashlib
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

# Polestar OAuth endpoints (EU region)
OIDC_PROVIDER_BASE = "https://polestarid.eu.polestar.com"
OIDC_DISCOVERY_PATH = "/.well-known/openid-configuration"
OIDC_REDIRECT_URI = "https://www.polestar.com/sign-in-callback"
OIDC_CLIENT_ID = "l3oopkc_10"

# Token refresh: refresh when less than this many seconds remain
TOKEN_REFRESH_WINDOW_SECONDS = 300  # 5 minutes


@dataclass
class TokenData:
    """Holds OAuth token state."""
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    expires_at: float = 0.0
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def should_refresh(self) -> bool:
        return time.time() >= (self.expires_at - TOKEN_REFRESH_WINDOW_SECONDS)


@dataclass
class OIDCEndpoints:
    """Cached OIDC endpoint URLs."""
    authorization_endpoint: str = ""
    token_endpoint: str = ""


class PolestarAuth:
    """
    Manages Polestar OIDC authentication with PKCE.

    Polestar uses PingFederate as their OIDC provider. The login flow is:
    1. GET /as/authorization.oauth2 → returns HTML with React login app
    2. Parse `window.globalContext.action` from the HTML → resume path
    3. POST username to resume path → returns HTML with password form
    4. POST password to resume path → redirects with authorization code
    5. Exchange code at /as/token.oauth2

    Usage:
        auth = PolestarAuth(username="...", password="...")
        await auth.async_init()
        headers = await auth.get_auth_headers()
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.username = username or os.environ.get("POLESTAR_USERNAME", "")
        self.password = password or os.environ.get("POLESTAR_PASSWORD", "")

        if not self.username or not self.password:
            raise ValueError(
                "Polestar credentials required. Set POLESTAR_USERNAME and "
                "POLESTAR_PASSWORD environment variables or pass them directly."
            )

        self._tokens = TokenData()
        self._endpoints = OIDCEndpoints()
        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def async_init(self) -> None:
        """Initialize: discover endpoints and perform initial login."""
        self._http = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
        )
        await self._discover_endpoints()
        await self._authenticate()
        logger.info("Polestar authentication successful")

    async def get_auth_headers(self) -> dict[str, str]:
        """Return Authorization headers, refreshing token if needed."""
        if self._tokens.should_refresh:
            await self._refresh_or_reauthenticate()
        return {
            "Authorization": f"{self._tokens.token_type} {self._tokens.access_token}",
        }

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # OIDC Discovery
    # ------------------------------------------------------------------

    async def _discover_endpoints(self) -> None:
        """Fetch OIDC configuration from .well-known endpoint."""
        url = f"{OIDC_PROVIDER_BASE}{OIDC_DISCOVERY_PATH}"
        logger.debug("Discovering OIDC endpoints from %s", url)

        resp = await self._http.get(url)
        resp.raise_for_status()
        config = resp.json()

        self._endpoints.authorization_endpoint = config["authorization_endpoint"]
        self._endpoints.token_endpoint = config["token_endpoint"]
        logger.debug("Token endpoint: %s", self._endpoints.token_endpoint)

    # ------------------------------------------------------------------
    # PKCE helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_pkce() -> tuple[str, str]:
        """Generate PKCE code_verifier and code_challenge (S256)."""
        code_verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return code_verifier, code_challenge

    # ------------------------------------------------------------------
    # Full authentication flow
    # ------------------------------------------------------------------

    async def _authenticate(self) -> None:
        """Run the full OIDC auth flow with PingFederate."""
        code_verifier, code_challenge = self._generate_pkce()

        # Step 1: GET authorization endpoint → login page HTML
        auth_params = {
            "response_type": "code",
            "client_id": OIDC_CLIENT_ID,
            "redirect_uri": OIDC_REDIRECT_URI,
            "scope": "openid profile email customer:attributes",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(32),
        }

        logger.debug("Starting authorization request")
        resp = await self._http.get(
            self._endpoints.authorization_endpoint,
            params=auth_params,
        )

        # Follow redirects to reach the login page
        resp = await self._follow_redirects(resp)

        # Step 2: Extract the resume path from the login page HTML
        resume_path = self._extract_resume_path(resp.text)
        if not resume_path:
            raise RuntimeError(
                "Could not find login form action (resume path) in Polestar login page. "
                "The login page structure may have changed."
            )
        logger.debug("Found resume path: %s", resume_path)

        # Step 3: POST username + password together
        # PingFederate accepts both fields in a single POST
        resume_url = f"{OIDC_PROVIDER_BASE}{resume_path}"
        logger.debug("Posting credentials to %s", resume_url)

        resp = await self._http.post(
            resume_url,
            data={
                "pf.username": self.username,
                "pf.pass": self.password,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # Step 5: Follow redirects to capture the authorization code
        code = await self._extract_code_from_redirects(resp)
        if not code:
            raise RuntimeError(
                "Failed to obtain authorization code. "
                "Check your username and password. "
                f"Last status: {resp.status_code}"
            )

        logger.debug("Received authorization code")

        # Step 6: Exchange authorization code for tokens
        await self._exchange_code(code, code_verifier)

    # ------------------------------------------------------------------
    # Helpers for the auth flow
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_resume_path(html: str) -> Optional[str]:
        """
        Extract the resume/action path from Polestar's login page.

        Polestar uses PingFederate which sets the form action in
        window.globalContext.action as a JavaScript variable.
        """
        # Pattern 1: action: "/as/xxxxx/resume/as/authorization.ping" (no quotes on key)
        # This is how PingFederate embeds it in window.globalContext
        match = re.search(
            r'\baction:\s*"([^"]+)"',
            html,
        )
        if match:
            return match.group(1)

        # Pattern 1b: with quotes on key — "action": "/as/..."
        match = re.search(
            r'["\']action["\']\s*:\s*["\']([^"\']+)["\']',
            html,
        )
        if match:
            return match.group(1)

        # Pattern 2: HTML form action attribute
        match = re.search(r'action="([^"]*)"', html)
        if match:
            path = match.group(1)
            if path.startswith("/"):
                return path

        # Pattern 3: data-action or other common patterns
        match = re.search(r'data-action="([^"]*)"', html)
        if match:
            return match.group(1)

        return None

    async def _follow_redirects(self, resp: httpx.Response, max_hops: int = 5) -> httpx.Response:
        """Follow HTTP redirects manually (we need to inspect each hop)."""
        for _ in range(max_hops):
            if resp.status_code not in (301, 302, 303, 307, 308):
                return resp

            location = resp.headers.get("location", "")
            if not location:
                return resp

            if not location.startswith("http"):
                location = f"{OIDC_PROVIDER_BASE}{location}"

            resp = await self._http.get(location)

        return resp

    async def _extract_code_from_redirects(self, resp: httpx.Response) -> Optional[str]:
        """Follow redirect chain and extract the authorization code from the callback URL."""
        for _ in range(10):
            if resp.status_code not in (301, 302, 303, 307, 308):
                break

            location = resp.headers.get("location", "")
            if not location:
                break

            # Check if this redirect contains the auth code (callback URL)
            parsed = urlparse(location)
            query_params = parse_qs(parsed.query)

            if "code" in query_params:
                return query_params["code"][0]

            # Check for error in redirect
            if "error" in query_params:
                error = query_params.get("error", ["unknown"])[0]
                error_desc = query_params.get("error_description", [""])[0]
                raise RuntimeError(
                    f"OAuth error: {error} — {error_desc}"
                )

            # Don't actually follow redirects to the Polestar website (we just need the code)
            if parsed.netloc and "polestar.com" in parsed.netloc and "polestarid" not in parsed.netloc:
                # This is the final redirect to polestar.com — code should be in the URL
                if "code" in query_params:
                    return query_params["code"][0]
                break

            # Follow the redirect within polestarid
            if not location.startswith("http"):
                location = f"{OIDC_PROVIDER_BASE}{location}"

            resp = await self._http.get(location)

        return None

    async def _exchange_code(self, code: str, code_verifier: str) -> None:
        """Exchange authorization code for access/refresh tokens."""
        logger.debug("Exchanging authorization code for tokens")

        resp = await self._http.post(
            self._endpoints.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OIDC_REDIRECT_URI,
                "client_id": OIDC_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        self._store_tokens(resp.json())

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    async def _refresh_or_reauthenticate(self) -> None:
        """Try to refresh the token; fall back to full re-auth."""
        if self._tokens.refresh_token:
            try:
                await self._refresh_token()
                return
            except Exception as exc:
                logger.warning("Token refresh failed (%s), re-authenticating", exc)

        await self._authenticate()

    async def _refresh_token(self) -> None:
        """Use refresh_token to get new access token."""
        logger.debug("Refreshing access token")

        resp = await self._http.post(
            self._endpoints.token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._tokens.refresh_token,
                "client_id": OIDC_CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        self._store_tokens(resp.json())
        logger.info("Token refreshed successfully")

    # ------------------------------------------------------------------
    # Token storage
    # ------------------------------------------------------------------

    def _store_tokens(self, token_response: dict) -> None:
        """Parse and store token response."""
        expires_in = token_response.get("expires_in", 3600)

        self._tokens = TokenData(
            access_token=token_response["access_token"],
            refresh_token=token_response.get("refresh_token", self._tokens.refresh_token),
            id_token=token_response.get("id_token", ""),
            expires_at=time.time() + expires_in,
            token_type=token_response.get("token_type", "Bearer"),
        )
        logger.debug(
            "Tokens stored, expires in %d seconds",
            expires_in,
        )
