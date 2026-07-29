"""Tests for logging setup (logconfig.py)."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

import logconfig
from logconfig import FORMAT, configure, get_logger


@pytest.fixture(autouse=True)
def _reset_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Undo global logging state so each test starts from a clean root."""
    monkeypatch.setattr(logconfig, "_configured", False)
    monkeypatch.delenv(logconfig.LEVEL_ENV_VAR, raising=False)
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    yield
    root.handlers[:] = saved_handlers
    root.level = saved_level


# ---------------------------------------------------------------------------
# Format string
# ---------------------------------------------------------------------------


def test_format_includes_filename_and_lineno() -> None:
    assert "%(filename)s" in FORMAT
    assert "%(lineno)d" in FORMAT


def test_rendered_record_carries_filename_and_lineno() -> None:
    record = logging.LogRecord(
        name="demo",
        level=logging.INFO,
        pathname="/abs/path/to/example.py",
        lineno=42,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    rendered = logging.Formatter(FORMAT, logconfig.DATE_FORMAT).format(record)
    assert "example.py:42" in rendered
    assert "hello world" in rendered
    # basename only -- the directory would bury the message
    assert "/abs/path/to" not in rendered


# ---------------------------------------------------------------------------
# Level resolution
# ---------------------------------------------------------------------------


def test_explicit_level_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(logconfig.LEVEL_ENV_VAR, "ERROR")
    assert configure("DEBUG").level == logging.DEBUG


def test_env_var_sets_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(logconfig.LEVEL_ENV_VAR, "warning")
    assert configure().level == logging.WARNING


def test_default_level_is_info() -> None:
    assert configure().level == logging.INFO


def test_int_level_accepted() -> None:
    assert configure(logging.ERROR).level == logging.ERROR


def test_unrecognized_level_falls_back_to_info(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(logconfig.LEVEL_ENV_VAR, "chatty")
    assert configure().level == logging.INFO
    # capsys, not caplog: configure() replaces the root handlers -- pytest's
    # capturing handler among them -- so the warning only reaches stderr.
    assert "unrecognized log level" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_repeat_configure_is_a_noop() -> None:
    configure("WARNING")
    handlers = logging.getLogger().handlers[:]
    configure("DEBUG")
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert root.handlers == handlers


def test_force_overrides_previous_configure() -> None:
    configure("WARNING")
    assert configure("DEBUG", force=True).level == logging.DEBUG


# ---------------------------------------------------------------------------
# uvicorn adoption
# ---------------------------------------------------------------------------


def test_uvicorn_handlers_are_dropped_and_propagate() -> None:
    noisy = logging.getLogger("uvicorn.access")
    noisy.addHandler(logging.StreamHandler())
    noisy.propagate = False

    configure("INFO")

    assert noisy.handlers == []
    assert noisy.propagate is True


def test_get_logger_returns_named_logger() -> None:
    assert get_logger("demo").name == "demo"
