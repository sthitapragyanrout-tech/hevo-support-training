"""The engine must never depend on Django (or Celery, DRF, the database…): that is
what keeps a standalone service a realistic future."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
ENGINE = BACKEND / "simbot_engine"
FORBIDDEN = {"django", "celery", "rest_framework", "apps", "config", "psycopg", "kombu", "redis"}


def test_the_engine_imports_with_no_framework_loaded():
    code = (
        "import sys, importlib, pkgutil, simbot_engine\n"
        "for m in pkgutil.iter_modules(simbot_engine.__path__):\n"
        "    importlib.import_module('simbot_engine.' + m.name)\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {sorted(FORBIDDEN)!r})\n"
        "assert not bad, bad\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env={"PYTHONPATH": str(BACKEND), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr[-1500:]


@pytest.mark.parametrize("path", sorted(ENGINE.glob("*.py")), ids=lambda p: p.name)
def test_no_source_file_imports_a_framework(path):
    tree = ast.parse(path.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert not imported & FORBIDDEN, (path.name, imported & FORBIDDEN)


def test_it_reads_no_environment_variables():
    for path in ENGINE.glob("*.py"):
        text = path.read_text()
        assert "os.environ" not in text and "getenv" not in text, path.name
