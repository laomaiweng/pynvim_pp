from dataclasses import dataclass
from typing import AbstractSet, Optional

from .atomic import Atomic


@dataclass(frozen=True)
class HLgroup:
    name: str
    cterm: AbstractSet[str] = frozenset()
    ctermfg: Optional[int] = None
    ctermbg: Optional[int] = None
    guifg: Optional[str] = None
    guibg: Optional[str] = None


def highlight(*groups: HLgroup) -> Atomic:
    atomic = Atomic()
    for group in groups:
        name = group.name
        _cterm = ",".join(group.cterm) or "NONE"
        cterm = f"cterm={_cterm}"
        ctermfg = f"ctermfg={group.ctermfg}" if group.ctermfg else ""
        ctermbg = f"ctermbg={group.ctermbg}" if group.ctermbg else ""
        guifg = f"guifg={group.guifg}" if group.guifg else ""
        guibg = f"guibg={group.guibg}" if group.guibg else ""

        hl_line = f"highlight {name} {cterm} {ctermfg} {ctermbg} {guifg} {guibg}"
        atomic.command(hl_line)

    return atomic


def hl_link(**links: str) -> Atomic:
    atomic = Atomic()
    for src, dest in links.items():
        link = f"highlight link {src} {dest}"
        atomic.command(link)
    return atomic

