"""Settings, read from the environment once at startup.

Nothing secret has a default. On the server the unit sets the public values
and `/etc/mealplan.env` supplies the client secrets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    db_path: str
    public_url: str
    # Browser login, as Recipie's: a confidential OIDC client, the session
    # kept server-side, the PWA holding only an HttpOnly cookie.
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    # Local development only: every request is this user and login is
    # skipped. Refused when the public URL is https.
    dev_user: str
    session_days: int
    # Friday's one sign-in (friday_sso.py). Empty: the endpoint is off.
    friday_issuer: str
    friday_client_id: str
    # Where the recipes come from (recipes.py). Either Recipie's service
    # endpoint, with a client-credentials token from Kanidm, or a JSON file
    # in development and the tests.
    recipie_url: str
    recipie_token_url: str
    recipie_client_id: str
    recipie_client_secret: str
    recipes_file: str
    recipes_refresh_seconds: int

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"MEALPLAN_{name}", default)


@lru_cache(maxsize=1)
def settings() -> Settings:
    s = Settings(
        db_path=_env("DB", "mealplan.db"),
        public_url=_env("PUBLIC_URL", "http://localhost:5173").rstrip("/"),
        oidc_issuer=_env("OIDC_ISSUER").rstrip("/"),
        oidc_client_id=_env("OIDC_CLIENT_ID"),
        oidc_client_secret=_env("OIDC_CLIENT_SECRET"),
        dev_user=_env("DEV_USER"),
        session_days=int(_env("SESSION_DAYS", "30")),
        friday_issuer=_env("FRIDAY_ISSUER").rstrip("/"),
        friday_client_id=_env("FRIDAY_CLIENT_ID"),
        recipie_url=_env("RECIPIE_URL").rstrip("/"),
        recipie_token_url=_env("RECIPIE_TOKEN_URL"),
        recipie_client_id=_env("RECIPIE_CLIENT_ID"),
        recipie_client_secret=_env("RECIPIE_CLIENT_SECRET"),
        recipes_file=_env("RECIPES_FILE"),
        # The safety net under the recipes.changed ping.
        recipes_refresh_seconds=int(_env("RECIPES_REFRESH", "600")),
    )
    if s.dev_user and s.secure_cookies:
        raise RuntimeError("MEALPLAN_DEV_USER skips login; it cannot be used with an https public URL.")
    return s
