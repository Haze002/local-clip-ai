from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from local_clip_ai.sources.twitch_api import (
    TwitchApiClient,
    TwitchToken,
    start_device_authorization,
)


class MemoryCredentials:
    def __init__(self, token: TwitchToken | None = None):
        self.token = token

    def load(self, client_id: str) -> TwitchToken | None:
        return self.token

    def save(self, client_id: str, token: TwitchToken) -> None:
        self.token = token

    def delete(self, client_id: str) -> None:
        self.token = None


class TwitchApiTests(unittest.TestCase):
    def test_device_authorization_response_is_normalized(self) -> None:
        with patch(
            "local_clip_ai.sources.twitch_api._post_form",
            return_value={
                "device_code": "device",
                "user_code": "ABCDEFGH",
                "verification_uri": "https://www.twitch.tv/activate",
                "expires_in": 1800,
                "interval": 5,
            },
        ):
            authorization = start_device_authorization("public-client-id")

        self.assertEqual(authorization.user_code, "ABCDEFGH")
        self.assertEqual(authorization.interval, 5)
        self.assertNotIn("device", authorization.verification_uri)

    def test_latest_archived_vod_uses_first_time_sorted_archive(self) -> None:
        credentials = MemoryCredentials(
            TwitchToken("access", "refresh", time.time() + 3600, ())
        )
        client = TwitchApiClient("public-client-id", credentials)
        with patch.object(
            client,
            "_get",
            return_value={
                "data": [
                    {
                        "id": "2823263031",
                        "url": "https://www.twitch.tv/videos/2823263031",
                        "title": "Minecraft Techopolis 3",
                        "user_login": "haise8k",
                        "duration": "1h58m33s",
                        "created_at": "2026-07-18T00:00:00Z",
                        "thumbnail_url": None,
                    }
                ]
            },
        ) as request:
            video = client.latest_archived_vod("123")

        self.assertEqual(video.video_id, "2823263031")
        request.assert_called_once_with(
            "videos",
            {
                "user_id": "123",
                "type": "archive",
                "sort": "time",
                "first": "1",
            },
        )
