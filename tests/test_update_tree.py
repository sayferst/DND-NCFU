"""No real modifications may hide behind an anomalous Git fixture status."""

import pytest

from scripts import check_update_tree as tree


@pytest.mark.parametrize(
    "status,working,index,expected",
    [
        (b"", b"original", b"original", True),
        (b" M tests/fixtures/save-v15.json\0", b"original", b"original", True),
        (b" M tests/fixtures/save-v15.json\0", b"changed", b"original", False),
        (b" M tests/fixtures/save-v15.json\0", b"original", b"changed", False),
        (b"M  tests/fixtures/save-v15.json\0", b"original", b"changed", False),
        (b"?? private.txt\0", b"original", b"original", False),
        (b" M tests/fixtures/save-v15.json\0?? extra\0", b"original", b"original", False),
    ],
)
def test_cleanliness(tmp_path, monkeypatch, status, working, index, expected):
    fixture = tmp_path / tree.FIXTURE
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(working)
    monkeypatch.setattr(tree, "reference_bytes", lambda root: b"original")
    monkeypatch.setattr(tree, "git", lambda root, *args: status if args[0] == "status" else index)
    assert tree.check(tmp_path) is expected
