from __future__ import annotations

import threading

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from local_clip_ai.sources.twitch_api import (
    DeviceAuthorization,
    KeyringCredentialStore,
    TwitchApiClient,
    poll_device_authorization,
    start_device_authorization,
)
from local_clip_ai.storage import JobDatabase


class TwitchController(QObject):
    changed = Signal()
    deviceReady = Signal(object)
    operationFinished = Signal(str, str)
    latestVodReady = Signal(str, str)

    def __init__(self, database: JobDatabase):
        super().__init__()
        self._database = database
        self._client_id = str(database.get_setting("twitch.client_id", ""))
        self._channel_login = str(database.get_setting("twitch.channel_login", ""))
        self._status = (
            "Client ID configured; connect or refresh the account."
            if self._client_id
            else "Add a public Twitch application Client ID to enable latest-VOD discovery."
        )
        self._user_code = ""
        self._verification_uri = ""
        self._connected_user = ""
        self._busy = False
        self._cancel_requested = False
        self.deviceReady.connect(self._device_ready)
        self.operationFinished.connect(self._operation_finished)

    @Property(str, notify=changed)
    def clientId(self) -> str:
        return self._client_id

    @Property(str, notify=changed)
    def channelLogin(self) -> str:
        return self._channel_login

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Property(str, notify=changed)
    def userCode(self) -> str:
        return self._user_code

    @Property(str, notify=changed)
    def verificationUri(self) -> str:
        return self._verification_uri

    @Property(str, notify=changed)
    def connectedUser(self) -> str:
        return self._connected_user

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    @Slot(str, str)
    def saveConfiguration(self, client_id: str, channel_login: str) -> None:
        self._client_id = client_id.strip()
        self._channel_login = channel_login.strip().lower()
        self._database.set_setting("twitch.client_id", self._client_id)
        self._database.set_setting("twitch.channel_login", self._channel_login)
        self._status = "Twitch configuration saved locally."
        self.changed.emit()

    @Slot()
    def connectTwitch(self) -> None:
        if self._busy:
            return
        if not self._client_id:
            self._status = "Save a Twitch Client ID first."
            self.changed.emit()
            return
        self._busy = True
        self._cancel_requested = False
        self._status = "Requesting a Twitch device code..."
        self.changed.emit()
        threading.Thread(
            target=self._connect_worker,
            name="twitch-device-auth",
            daemon=True,
        ).start()

    def _connect_worker(self) -> None:
        try:
            authorization = start_device_authorization(self._client_id)
            self.deviceReady.emit(authorization)
            token = poll_device_authorization(
                self._client_id,
                authorization,
                cancel_requested=lambda: self._cancel_requested,
            )
            client = TwitchApiClient(self._client_id)
            client.save_token(token)
            user = client.current_user()
            self.operationFinished.emit(
                user.display_name,
                f"Connected to Twitch as {user.display_name}.",
            )
        except Exception as error:
            self.operationFinished.emit("", f"Twitch connection failed: {error}")

    @Slot(object)
    def _device_ready(self, authorization: DeviceAuthorization) -> None:
        self._user_code = authorization.user_code
        self._verification_uri = authorization.verification_uri
        self._status = (
            f"Enter code {authorization.user_code} in Twitch. "
            "Waiting for authorization..."
        )
        self.changed.emit()
        QDesktopServices.openUrl(QUrl(authorization.verification_uri))

    @Slot(str, str)
    def _operation_finished(self, connected_user: str, status: str) -> None:
        self._busy = False
        self._connected_user = connected_user
        self._status = status
        self.changed.emit()

    @Slot()
    def cancelConnection(self) -> None:
        self._cancel_requested = True
        self._status = "Cancelling Twitch connection..."
        self.changed.emit()

    @Slot()
    def disconnect(self) -> None:
        if self._client_id:
            KeyringCredentialStore().delete(self._client_id)
        self._connected_user = ""
        self._user_code = ""
        self._verification_uri = ""
        self._status = "Twitch credentials were removed from Windows Credential Manager."
        self.changed.emit()

    @Slot()
    def openActivation(self) -> None:
        if self._verification_uri:
            QDesktopServices.openUrl(QUrl(self._verification_uri))

    @Slot()
    def openDeveloperConsole(self) -> None:
        QDesktopServices.openUrl(QUrl("https://dev.twitch.tv/console/apps"))

    @Slot()
    def findLatestVod(self) -> None:
        if self._busy:
            return
        if not self._client_id:
            self._status = "Configure and connect Twitch first."
            self.changed.emit()
            return
        self._busy = True
        self._status = "Looking up the latest archived VOD..."
        self.changed.emit()
        threading.Thread(
            target=self._latest_vod_worker,
            name="twitch-latest-vod",
            daemon=True,
        ).start()

    def _latest_vod_worker(self) -> None:
        try:
            client = TwitchApiClient(self._client_id)
            user = (
                client.user_by_login(self._channel_login)
                if self._channel_login
                else client.current_user()
            )
            video = client.latest_archived_vod(user.user_id)
            self.latestVodReady.emit(video.url, video.title)
            self.operationFinished.emit(
                user.display_name,
                f"Latest VOD found: {video.title}",
            )
        except Exception as error:
            self.operationFinished.emit("", f"Latest-VOD lookup failed: {error}")
