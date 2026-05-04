"""Regression checks for critical handler/runtime issues."""

import logging


def test_handlers_defines_logger():
    """Read-aloud error path uses logger.error; module must expose logger."""
    import handlers

    assert isinstance(getattr(handlers, "logger", None), logging.Logger)
