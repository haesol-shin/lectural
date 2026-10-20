"""Require installed URL runtime coverage when explicitly requested by CI."""

import os

import pytest


def pytest_collection_finish(session):
    if os.environ.get("LECTURAL_REQUIRE_URL_RUNTIME") == "1" and not any(
        item.get_closest_marker("url_runtime") for item in session.items
    ):
        raise pytest.UsageError("URL runtime gate collected no marked tests")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if (
        os.environ.get("LECTURAL_REQUIRE_URL_RUNTIME") == "1"
        and item.get_closest_marker("url_runtime")
        and report.skipped
    ):
        report.outcome = "failed"
        report.longrepr = f"URL runtime test must not skip: {item.nodeid}"
