"""RTC-only adapter; the WS reducer and adapter are imported unchanged."""

import math

from ten_packages.extension.jev_turn_control_python.extension import (
    JevTurnControlExtension,
)


class JevRTCControl(JevTurnControlExtension):
    def handle_data(self, name, payload):
        if name == "jev_rtc_playback":
            cursor = payload.get("played_ms")
            if (
                not isinstance(payload.get("response_id"), str)
                or type(cursor) not in (int, float)
                or not math.isfinite(cursor)
                or cursor < 0
                or any(
                    type(payload.get(k, False)) is not bool
                    for k in ("stopped", "completed")
                )
            ):
                raise ValueError("invalid RTC progress")
            self.engine.playback(
                payload["response_id"],
                cursor,
                self.now(),
                stopped=payload.get("stopped", False),
                completed=payload.get("completed", False),
                confirmed=False,
            )
        elif name == "jev_playback":
            raise ValueError("browser PCM acknowledgments are not RTC progress")
        else:
            super().handle_data(name, payload)

    async def send_data(self, name, payload, destination):
        if name == "jev_event":
            payload = {**payload, "payload": {**payload.get("payload", {})}}
            detail = payload["payload"]
            detail["transport"] = "rtc"
            if payload["type"] == "state.snapshot":
                detail["playback_precision"] = "rtc_server_emission_estimate"
            if payload["type"].startswith("playback."):
                detail["precision"] = "rtc_server_emission_estimate"
                detail["confirmed"] = False
        await super().send_data(name, payload, destination)
