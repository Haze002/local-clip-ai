from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from contextlib import ExitStack

_NULL_STREAMS = ExitStack()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    if "--worker-cli" in arguments:
        arguments.remove("--worker-cli")
        if sys.stdout is None:
            sys.stdout = _NULL_STREAMS.enter_context(
                open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
            )
        if sys.stderr is None:
            sys.stderr = _NULL_STREAMS.enter_context(
                open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
            )
        from local_clip_ai.cli import main as cli_main

        return cli_main(arguments)
    from local_clip_ai.app.main import main as gui_main

    return gui_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
