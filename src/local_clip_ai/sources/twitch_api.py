from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import Any, Protocol

TWITCH_ID_ROOT = "https://id.twitch.tv/oauth2"
TWITCH_API_ROOT = "https://api.twitch.tv/helix"
DEFAULT_SCOPES = "user:read:broadcast"
USER_AGENT = "Local-Clip-AI/0.1 (+https://github.com/Haze002/local-clip-ai)"


class AuthenticationCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    requested_at: float
    scopes: str


@dataclass(frozen=True, slots=True)
class TwitchToken:
    access_token: str
    refresh_token: str
    expires_at: float
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HelixUser:
    user_id: str
    login: str
    display_name: str
    profile_image_url: str | None


@dataclass(frozen=True, slots=True)
class HelixVideo:
    video_id: str
    url: str
    title: str
    user_login: str
    duration: str
    created_at: str
    thumbnail_url: str | None


class CredentialStore(Protocol):
    def load(self, client_id: str) -> TwitchToken | None: ...

    def save(self, client_id: str, token: TwitchToken) -> None: ...

    def delete(self, client_id: str) -> None: ...


class KeyringCredentialStore:
    SERVICE_NAME = "Local Clip AI Twitch"

    def load(self, client_id: str) -> TwitchToken | None:
        import keyring

        value = keyring.get_password(self.SERVICE_NAME, client_id)
        if not value:
            return None
        data = json.loads(value)
        data["scopes"] = tuple(data.get("scopes", ()))
        return TwitchToken(**data)

    def save(self, client_id: str, token: TwitchToken) -> None:
        import keyring

        keyring.set_password(
            self.SERVICE_NAME,
            client_id,
            json.dumps(asdict(token), sort_keys=True),
        )

    def delete(self, client_id: str) -> None:
        import keyring

        with suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(self.SERVICE_NAME, client_id)


def _post_form(url: str, values: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _token_from_response(values: dict[str, Any]) -> TwitchToken:
    return TwitchToken(
        access_token=str(values["access_token"]),
        refresh_token=str(values["refresh_token"]),
        expires_at=time.time() + int(values["expires_in"]),
        scopes=tuple(values.get("scope", ())),
    )


def start_device_authorization(
    client_id: str,
    *,
    scopes: str = DEFAULT_SCOPES,
) -> DeviceAuthorization:
    if not client_id.strip():
        raise ValueError("A Twitch application Client ID is required")
    values = _post_form(
        f"{TWITCH_ID_ROOT}/device",
        {"client_id": client_id.strip(), "scopes": scopes},
    )
    return DeviceAuthorization(
        device_code=str(values["device_code"]),
        user_code=str(values["user_code"]),
        verification_uri=str(values["verification_uri"]),
        expires_in=int(values["expires_in"]),
        interval=max(1, int(values["interval"])),
        requested_at=time.time(),
        scopes=scopes,
    )


def poll_device_authorization(
    client_id: str,
    authorization: DeviceAuthorization,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> TwitchToken:
    deadline = authorization.requested_at + authorization.expires_in
    interval = authorization.interval
    while time.time() < deadline:
        if cancel_requested and cancel_requested():
            raise AuthenticationCancelled("Twitch connection cancelled")
        try:
            values = _post_form(
                f"{TWITCH_ID_ROOT}/token",
                {
                    "client_id": client_id,
                    "scopes": authorization.scopes,
                    "device_code": authorization.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            return _token_from_response(values)
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")
            try:
                message = str(json.loads(body).get("message", ""))
            except json.JSONDecodeError:
                message = body
            normalized = message.lower().replace(" ", "_")
            if "authorization_pending" in normalized:
                time.sleep(interval)
                continue
            if "slow_down" in normalized:
                interval += 5
                time.sleep(interval)
                continue
            raise RuntimeError(f"Twitch device authorization failed: {message}") from error
    raise TimeoutError("The Twitch device code expired before authorization completed")


class TwitchApiClient:
    def __init__(
        self,
        client_id: str,
        credential_store: CredentialStore | None = None,
    ):
        if not client_id.strip():
            raise ValueError("A Twitch application Client ID is required")
        self.client_id = client_id.strip()
        self.credentials = credential_store or KeyringCredentialStore()

    def save_token(self, token: TwitchToken) -> None:
        self.credentials.save(self.client_id, token)

    def _refresh(self, token: TwitchToken) -> TwitchToken:
        values = _post_form(
            f"{TWITCH_ID_ROOT}/token",
            {
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
            },
        )
        refreshed = _token_from_response(values)
        self.credentials.save(self.client_id, refreshed)
        return refreshed

    def _token(self) -> TwitchToken:
        token = self.credentials.load(self.client_id)
        if token is None:
            raise RuntimeError("Twitch is not connected")
        if token.expires_at <= time.time() + 60:
            token = self._refresh(token)
        return token

    def _get(self, path: str, parameters: dict[str, str] | None = None) -> dict[str, Any]:
        token = self._token()
        query = urllib.parse.urlencode(parameters or {})
        url = f"{TWITCH_API_ROOT}/{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token.access_token}",
                "Client-Id": self.client_id,
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
            token = self._refresh(token)
            request.add_header("Authorization", f"Bearer {token.access_token}")
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)

    @staticmethod
    def _user(values: dict[str, Any]) -> HelixUser:
        return HelixUser(
            user_id=str(values["id"]),
            login=str(values["login"]),
            display_name=str(values["display_name"]),
            profile_image_url=values.get("profile_image_url"),
        )

    def current_user(self) -> HelixUser:
        users = self._get("users").get("data", [])
        if not users:
            raise RuntimeError("Twitch did not return the connected user")
        return self._user(users[0])

    def user_by_login(self, login: str) -> HelixUser:
        users = self._get("users", {"login": login.strip().lower()}).get("data", [])
        if not users:
            raise RuntimeError(f"Twitch channel was not found: {login}")
        return self._user(users[0])

    def latest_archived_vod(self, user_id: str) -> HelixVideo:
        videos = self._get(
            "videos",
            {
                "user_id": user_id,
                "type": "archive",
                "sort": "time",
                "first": "1",
            },
        ).get("data", [])
        if not videos:
            raise RuntimeError("No published archived VODs were found for this channel")
        value = videos[0]
        return HelixVideo(
            video_id=str(value["id"]),
            url=str(value["url"]),
            title=str(value["title"]),
            user_login=str(value["user_login"]),
            duration=str(value["duration"]),
            created_at=str(value["created_at"]),
            thumbnail_url=value.get("thumbnail_url"),
        )
