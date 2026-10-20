"""Offline tests for per-kind source handlers."""

from __future__ import annotations

import pytest

from lectural.source import InputSource, SourceKind
from lectural.sources import handler_for


@pytest.mark.parametrize("kind", list(SourceKind))
def test_every_source_kind_has_a_handler(kind):
    # A new kind must get an explicit handler rather than a generic fallback.
    source = InputSource(argument="input", kind=kind, locator="input", title_hint="input", video_id=None)
    assert handler_for(source) is not None
