from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from labbrain.log import append

WHEN = datetime(2026, 10, 15, 9, 5)


def test_append_lines(tmp_path: Path) -> None:
    path = append(tmp_path, "exp-log: logged EXP-20261015-x", when=WHEN, author="claude")
    append(tmp_path, "idea:  multi\nline ", when=WHEN)
    assert path == tmp_path / "log" / "2026-10-15.md"
    assert path.read_text() == (
        "- 09:05 [claude] exp-log: logged EXP-20261015-x\n- 09:05 idea: multi line\n"
    )


def test_append_repairs_missing_trailing_newline(tmp_path: Path) -> None:
    (tmp_path / "log").mkdir()
    (tmp_path / "log" / "2026-10-15.md").write_text("- 08:00 earlier")
    path = append(tmp_path, "later", when=WHEN)
    assert path.read_text() == "- 08:00 earlier\n- 09:05 later\n"


def test_append_rejects_empty_text(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        append(tmp_path, "   ", when=WHEN)
