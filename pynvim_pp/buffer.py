from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from string import ascii_lowercase
from typing import (
    Any,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    MutableMapping,
    MutableSequence,
    NewType,
    Optional,
    Sequence,
    Tuple,
    cast,
)

from msgpack import Packer

from .atomic import Atomic
from .lib import decode, encode
from .types import BufNamespace, Ext, ExtData, HasLocalCall, NoneType, NvimPos

ExtMarker = NewType("ExtMarker", int)
BufMarker = NewType("BufMarker", str)
BufNum = NewType("BufNum", int)


@dataclass(frozen=True)
class ExtMark:
    buf: Buffer
    marker: ExtMarker
    begin: NvimPos
    end: Optional[NvimPos]
    meta: Mapping[str, Any]

    async def text(self) -> Sequence[str]:
        if end := self.end:
            return await self.buf.get_text(self.begin, end=end)
        else:
            return ()


def linefeed(lf: str) -> Literal["\r\n", "\n", "\r"]:
    if lf == "dos":
        return "\r\n"
    elif lf == "unix":
        return "\n"
    elif lf == "mac":
        return "\r"
    else:
        raise ValueError(lf)


class Buffer(Ext, HasLocalCall):
    prefix = "nvim_buf"
    _packer = Packer()

    @classmethod
    def from_int(cls, num: int) -> Buffer:
        return Buffer(data=ExtData(cls._packer.pack(num)))

    @classmethod
    async def list(cls, listed: bool) -> Sequence[Buffer]:
        bufs = cast(
            Sequence[Buffer],
            await cls.api.list_bufs(NoneType, prefix=cls.base_prefix),
        )

        if listed:
            atomic = Atomic()
            for buf in bufs:
                atomic.buf_is_loaded(buf)
            loaded = await atomic.commit(bool)
            return tuple(buf for buf, listed in zip(bufs, loaded) if listed)
        else:
            return bufs

    @classmethod
    async def get_current(cls) -> Buffer:
        return await cls.api.get_current_buf(Buffer, prefix=cls.base_prefix)

    @classmethod
    async def set_current(cls, buf: Buffer) -> None:
        await cls.api.set_current_buf(NoneType, buf, prefix=cls.base_prefix)

    @classmethod
    async def create(
        cls, listed: bool, scratch: bool, wipe: bool, nofile: bool, noswap: bool
    ) -> Buffer:
        buf = await cls.api.create_buf(Buffer, listed, scratch, prefix=cls.base_prefix)
        atomic = Atomic()

        if wipe:
            atomic.buf_set_option(buf, "bufhidden", "wipe")
        if nofile:
            atomic.buf_set_option(buf, "buftype", "nofile")
        if noswap:
            atomic.buf_set_option(buf, "swapfile", False)

        await atomic.commit(NoneType)
        return buf

    @cached_property
    def number(self) -> BufNum:
        return BufNum(int.from_bytes(self.data, byteorder="big"))

    async def delete(self) -> None:
        if await self.api.has("nvim-0.5"):
            await self.api.delete(NoneType, self, {"force": True})
        else:
            await self.api.command(str, f"bwipeout! {self.number}", prefix="nvim")

    async def get_name(self) -> Optional[str]:
        return await self.api.get_name(str, self)

    async def linefeed(self) -> str:
        lf = await self.opts.get(str, "fileformat")
        return linefeed(lf)

    async def modifiable(self) -> bool:
        return await self.opts.get(bool, "modifiable")

    async def filetype(self) -> str:
        ft = await self.opts.get(str, "filetype")
        return ft

    async def commentstr(self) -> Optional[Tuple[str, str]]:
        if commentstr := await self.opts.get(str, "commentstring"):
            lhs, sep, rhs = commentstr.partition("%s")
            assert sep
            return lhs, rhs
        else:
            return None

    async def changed_tick(self) -> int:
        return await self.api.changedtick(int, self)

    async def line_count(self) -> int:
        return await self.api.line_count(int, self)

    async def get_lines(self, lo: int = 0, hi: int = -1) -> MutableSequence[str]:
        return cast(
            MutableSequence[str],
            await self.api.get_lines(NoneType, self, lo, hi, True),
        )

    async def set_lines(self, lines: Sequence[str], lo: int = 0, hi: int = -1) -> None:
        await self.api.set_lines(NoneType, self, lo, hi, True, lines)

    async def get_text(self, begin: NvimPos, end: NvimPos) -> Sequence[str]:
        (r1, c1), (r2, c2) = begin, end
        if await self.api.has("nvim-0.6"):
            return cast(
                Sequence[str],
                await self.api.get_text(NoneType, self, r1, c1, r2, c2, {}),
            )
        else:
            c2 = max(0, c2 - 1)
            lo, hi = min(r1, r2), max(r1, r2) + 1
            lines = await self.get_lines(lo=lo, hi=hi)

            def cont() -> Iterator[str]:
                for idx, line in enumerate(lines, start=lo):
                    if idx == r1 and idx == r2:
                        yield decode(encode(line)[c1:c2])
                    elif idx == r1:
                        yield decode(encode(line)[c1:])
                    elif idx == r2:
                        yield decode(encode(line)[:c2])
                    else:
                        yield line

            return tuple(cont())

    async def set_text(self, text: Sequence[str], begin: NvimPos, end: NvimPos) -> None:
        (r1, c1), (r2, c2) = begin, end
        await self.api.set_text(NoneType, self, r1, c1, r2, c2, text)

    async def clear_namespace(
        self, ns: BufNamespace, lo: int = 0, hi: int = -1
    ) -> None:
        await self.api.clear_namespace(NoneType, self, ns, lo, hi)

    async def get_extmarks(
        self, ns: BufNamespace, lo: int = 0, hi: int = -1
    ) -> Sequence[ExtMark]:
        marks = cast(
            Sequence[Tuple[int, int, int, Mapping[str, Any]]],
            await self.api.get_extmarks(
                NoneType,
                self,
                ns,
                lo,
                hi,
                {"details": True},
            ),
        )

        def cont() -> Iterator[ExtMark]:
            for idx, row, col, meta in marks:
                end = (
                    (end_row, end_col)
                    if (end_row := meta.get("end_row")) is not None
                    and (end_col := meta.get("end_col")) is not None
                    else None
                )
                mark = ExtMark(
                    buf=self,
                    marker=ExtMarker(idx),
                    begin=(row, col),
                    end=end,
                    meta=meta,
                )
                yield mark

        return tuple(cont())

    async def set_extmarks(self, ns: BufNamespace, extmarks: Iterable[ExtMark]) -> None:
        atomic = Atomic()
        for mark in extmarks:
            (r1, c1) = mark.begin
            opts: MutableMapping[str, Any] = {
                **mark.meta,
                "id": mark.marker,
            }
            if end := mark.end:
                r2, c2 = end
                opts.update(end_line=r2, end_col=c2)
            atomic.buf_set_extmark(self, ns, r1, c1, opts)

        await atomic.commit(NoneType)

    async def del_extmarks(
        self, ns: BufNamespace, markers: Iterable[ExtMarker]
    ) -> None:
        atomic = Atomic()
        for marker in markers:
            atomic.buf_del_extmark(self, ns, marker)
        await atomic.commit(NoneType)

    async def get_mark(self, marker: BufMarker) -> Optional[NvimPos]:
        row, col = cast(NvimPos, await self.api.get_mark(NoneType, self, marker))
        if (row, col) == (0, 0):
            return None
        else:
            return row - 1, col

    async def set_mark(self, mark: BufMarker, row: int, col: int) -> None:
        marked = f"'{mark}"
        lua = """
        return vim.api.nvim_call_function("setpos", argv)
        """
        await self.local_lua(NoneType, lua, marked, (self, row + 1, col + 1, 0))

    async def list_bookmarks(self) -> Mapping[BufMarker, NvimPos]:
        atomic = Atomic()
        for chr in ascii_lowercase:
            atomic.buf_get_mark(self, chr)
        marks = cast(Sequence[NvimPos], await atomic.commit(NoneType))

        bookmarks = {
            BufMarker(chr): (row - 1, col)
            for chr, (row, col) in zip(ascii_lowercase, marks)
            if (row, col) != (0, 0)
        }
        return bookmarks
