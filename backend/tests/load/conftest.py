"""Load tests start real processes and take minutes, so they only run when asked:
`pytest -m load -s tests/load` (the figures are printed)."""

import pytest


def pytest_collection_modifyitems(config, items):
    if "load" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="load tests run only with -m load")
    for item in items:
        if "load" in item.keywords:
            item.add_marker(skip)
