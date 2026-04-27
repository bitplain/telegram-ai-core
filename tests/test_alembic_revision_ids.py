"""Проверки совместимости Alembic revision ids с таблицей alembic_version."""

from __future__ import annotations

import re
from pathlib import Path


def test_alembic_revision_ids_fit_version_table() -> None:
    versions_dir = Path("alembic/versions")
    pattern = re.compile(r'^revision:\s*str\s*=\s*"([^"]+)"', re.MULTILINE)

    for path in versions_dir.glob("*.py"):
        match = pattern.search(path.read_text(encoding="utf-8"))
        assert match is not None, f"{path} has no revision id"
        revision = match.group(1)
        assert len(revision) <= 32, f"{path} revision id is too long: {revision}"
