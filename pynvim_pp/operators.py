from string import whitespace
from typing import Literal, Optional, Tuple

from pynvim import Nvim
from pynvim.api import Buffer, Window

from .api import NvimPos, buf_get_mark, buf_get_option
from .atomic import Atomic

VisualMode = Literal["v", "V"]
VisualTypes = Optional[Literal["char", "line", "block"]]


def writable(nvim: Nvim, buf: Buffer) -> bool:
    is_modifiable: bool = buf_get_option(nvim, buf=buf, key="modifiable")
    return is_modifiable


def operator_marks(
    nvim: Nvim, buf: Buffer, visual_type: VisualTypes
) -> Tuple[NvimPos, NvimPos]:
    assert visual_type in {None, "char", "line", "block"}
    mark1, mark2 = ("[", "]") if visual_type else ("<", ">")
    m1 = buf_get_mark(nvim, buf=buf, mark=mark1)
    m2 = buf_get_mark(nvim, buf=buf, mark=mark2)
    assert m1 and m2
    (row1, col1), (row2, col2) = m1, m2
    return (row1, col1), (row2, col2 + 1)


def set_visual_selection(
    nvim: Nvim,
    win: Window,
    mode: VisualMode,
    mark1: NvimPos,
    mark2: NvimPos,
    reverse: bool = False,
) -> None:
    assert mode in {"v", "V"}
    (r1, c1), (r2, c2) = mark1, mark2
    atomic = Atomic()
    if reverse:
        atomic.win_set_cursor(win, (r2 + 1, max(0, c2 - 1)))
        atomic.command(f"norm! {mode}")
        atomic.win_set_cursor(win, (r1 + 1, c1))

    else:
        atomic.win_set_cursor(win, (r1 + 1, c1))
        atomic.command(f"norm! {mode}")
        atomic.win_set_cursor(win, (r2 + 1, max(0, c2 - 1)))
    atomic.commit(nvim)


def p_indent(line: str, tabsize: int) -> int:
    ws = {*whitespace}
    spaces = " " * tabsize
    for idx, char in enumerate(line.replace("\t", spaces), start=1):
        if char not in ws:
            return idx - 1
    else:
        return 0
