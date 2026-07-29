"""logconfig.py — the one place stdlib logging is configured for this project.

Deliberately outside the formal model: no types, no instances, no rules. It is
an operational concern only, which is why nothing here is imported by `base.py`,
`rules.py`, `datalog.py`, or `serialize.py` — those stay import-side-effect free.

Call `configure()` once, as early in a process's life as possible, then take a
module-level logger everywhere else:

    from logconfig import configure, get_logger

    configure()
    log = get_logger(__name__)
    log.info("indexed %d instances", len(g.by_id))

Log level comes from `configure(level=...)`, else the `LOG_LEVEL` environment
variable, else INFO.
"""

from __future__ import annotations

import logging
import os

# filename:lineno leads the message so an editor's "jump to file:line" and a
# plain grep both hit the prefix. %(filename)s is the basename only; the package
# is flat, so that is already unambiguous and a full path would bury the message.
FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(filename)s:%(lineno)d %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

DEFAULT_LEVEL = "INFO"
LEVEL_ENV_VAR = "LOG_LEVEL"

# uvicorn installs its own handlers with its own format during startup. Left
# alone they would print every record twice, once in each format, so configure()
# strips them and lets the records propagate to the root handler instead.
_ADOPTED_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_configured = False


def _resolve_level(level: str | int | None) -> tuple[int, str | None]:
    """Return (level, unrecognized_name). Falls back to INFO on a bad name."""
    if isinstance(level, int):
        return level, None
    name = (level or os.environ.get(LEVEL_ENV_VAR) or DEFAULT_LEVEL).strip().upper()
    resolved = logging.getLevelNamesMapping().get(name)
    if resolved is None:
        return logging.INFO, name
    return resolved, None


def configure(level: str | int | None = None, *, force: bool = False) -> logging.Logger:
    """Install the root handler and return the root logger.

    Idempotent: repeat calls are no-ops unless `force=True`, so importing a
    module that configures logging cannot clobber a caller's own setup.

    Note that the first (non-no-op) call *replaces* any existing root handlers,
    which is the point -- it is how uvicorn's default format gets displaced. In
    tests that means pytest's `caplog` handler is torn down too, so assert on
    `capsys` stderr rather than `caplog` for records emitted through here.
    """
    global _configured
    root = logging.getLogger()
    if _configured and not force:
        return root

    resolved, bad_name = _resolve_level(level)
    # force=True here is about *this* call replacing whatever uvicorn or a
    # stray basicConfig() left behind; the guard above handles repeat calls.
    logging.basicConfig(level=resolved, format=FORMAT, datefmt=DATE_FORMAT, force=True)
    for name in _ADOPTED_LOGGERS:
        adopted = logging.getLogger(name)
        adopted.handlers.clear()
        adopted.propagate = True
        adopted.setLevel(resolved)

    _configured = True
    if bad_name is not None:
        # now that a handler exists, this is actually visible
        root.warning(
            "unrecognized log level %r (from %s); using %s",
            bad_name,
            LEVEL_ENV_VAR,
            DEFAULT_LEVEL,
        )
    return root


def get_logger(name: str) -> logging.Logger:
    """A named logger. Thin on purpose.

    No wrapper that logs on the caller's behalf: %(filename)s / %(lineno)d
    report the frame that made the call, so any indirection here would make
    every line in the log point back at this file.
    """
    return logging.getLogger(name)
