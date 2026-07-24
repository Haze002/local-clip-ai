from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from typing import Any

_NULL_STREAMS = ExitStack()
GUI_STDIO_SMOKE_ARGUMENT = "--frozen-gui-stdio-smoke"
MEDIA_SMOKE_ARGUMENT = "--frozen-media-smoke"


def _utf8_stream(stream: Any) -> Any:
    if stream is None:
        return _NULL_STREAMS.enter_context(
            open(  # noqa: SIM115
                os.devnull,
                "w",
                encoding="utf-8",
                errors="backslashreplace",
            )
        )
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="backslashreplace")
    return stream


def configure_utf8_standard_streams() -> None:
    """Make arbitrary transcript text safe on Windows legacy-code-page systems."""
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
    sys.stdout = _utf8_stream(sys.stdout)
    sys.stderr = _utf8_stream(sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    configure_utf8_standard_streams()
    if GUI_STDIO_SMOKE_ARGUMENT in arguments:
        sys.stdout.write("Local Clip AI GUI stdout ready.\n")
        sys.stderr.write("Local Clip AI GUI stderr ready.\n")
        sys.stdout.flush()
        sys.stderr.flush()
        return 0
    if MEDIA_SMOKE_ARGUMENT in arguments:
        argument_index = arguments.index(MEDIA_SMOKE_ARGUMENT)
        try:
            media_path = arguments[argument_index + 1]
        except IndexError:
            return 2
        from local_clip_ai.app.media_smoke import run_media_smoke

        return run_media_smoke(media_path)
    if "--worker-cli" in arguments:
        arguments.remove("--worker-cli")
        from local_clip_ai.cli import main as cli_main

        return cli_main(arguments)
    from local_clip_ai.app.main import main as gui_main

    return gui_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
