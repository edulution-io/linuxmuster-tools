"""
Writes must not be dropped when the old and the new file have the same size
and the same mtime.
"""

import filecmp
import stat

import pytest
from linuxmusterTools.lmnfile import LMNFile


@pytest.fixture
def same_tick(monkeypatch):
    """Make filecmp see every file with the same mtime."""
    filecmp.clear_cache()
    monkeypatch.setattr(
        filecmp, '_sig', lambda st: (stat.S_IFMT(st.st_mode), st.st_size, 0)
    )
    yield
    filecmp.clear_cache()


def test_write_after_an_equal_write_is_kept(tmp_path, same_tick):
    f = tmp_path / 'config.yml'
    f.write_text('room: room1\n', encoding='utf-8')
    for room in ('room1', 'room1', 'room2'):
        with LMNFile(str(f), 'w') as lmn:
            lmn.write({'room': room})
    assert f.read_text(encoding='utf-8') == 'room: room2\n'
