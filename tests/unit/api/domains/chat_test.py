from __future__ import annotations

from io import BytesIO

import pytest

from app.api.v2.chat import _iter_log_lines_reverse


@pytest.mark.parametrize(
    "log_data",
    [
        b"first\nmiddle\nlast\n",
        b"x" * 9000 + b"\nlast\n",
    ],
)
def test_iter_log_lines_reverse_returns_lines_and_offsets(log_data: bytes) -> None:
    lines = list(_iter_log_lines_reverse(BytesIO(log_data)))

    assert [line for _, line in lines] == [
        line.decode()
        for line in reversed(log_data.splitlines())
    ]
    assert all(log_data[offset:].startswith(line.encode()) for offset, line in lines)
