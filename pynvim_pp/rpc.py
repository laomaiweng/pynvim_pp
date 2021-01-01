from __future__ import annotations

from asyncio.coroutines import iscoroutinefunction
from os import linesep
from typing import (
    Any,
    Awaitable,
    Callable,
    Generic,
    MutableMapping,
    MutableSequence,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
    cast,
)
from uuid import uuid4

from pynvim import Nvim

from .atomic import Atomic
from .lib import async_call, go
from .logging import log

T = TypeVar("T")

RpcMsg = Tuple[str, Sequence[Any]]


class RpcCallable(Generic[T]):
    def __init__(
        self,
        name: Optional[str],
        blocking: bool,
        handler: Union[Callable[..., T], Callable[..., Awaitable[T]]],
    ) -> None:
        if iscoroutinefunction(handler) and blocking:
            raise ValueError()
        else:
            self.name = name if name else f"{handler.__module__}.{handler.__qualname__}"
            self.remote_name = f"{self.name}_{uuid4().hex}".replace(
                ".", "_"
            ).capitalize()
            self.blocking = blocking
            self._handler = handler

    def __call__(self, nvim: Nvim, *args: Any) -> Union[T, Awaitable[T]]:
        if iscoroutinefunction(self._handler):
            aw = cast(Awaitable[T], self._handler(nvim, *args))
            return go(aw)
        elif self.blocking:
            return cast(T, self._handler(nvim, *args))
        else:
            handler = cast(Callable[[Nvim, Any], T], self._handler)
            aw = async_call(nvim, handler, nvim, *args)
            return go(aw)


RpcSpec = Tuple[str, RpcCallable[T]]


def _new_lua_func(chan: int, handler: RpcCallable[T]) -> str:
    op = "request" if handler.blocking else "notify"
    invoke = f"return vim.rpc{op}({chan}, '{handler.name}', {{...}})"
    return f"{handler.remote_name} = function (...) {invoke} end"


def _new_viml_func(handler: RpcCallable[T]) -> str:
    head = f"function! {handler.remote_name}(...)"
    body = f"  call v:lua.{handler.remote_name}(a:000)"
    tail = f"endfunction"
    return linesep.join((head, body, tail))


class RPC:
    def __init__(self) -> None:
        self._handlers: MutableMapping[str, RpcCallable[Any]] = {}

    def __call__(
        self,
        blocking: bool,
        name: Optional[str] = None,
    ) -> Callable[[Callable[..., T]], RpcCallable[T]]:
        def decor(handler: Callable[..., T]) -> RpcCallable[T]:
            wraped = RpcCallable(name=name, blocking=blocking, handler=handler)
            self._handlers[wraped.name] = wraped
            return wraped

        return decor

    def drain(self, chan: int) -> Tuple[Atomic, Sequence[RpcSpec]]:
        atomic = Atomic()
        specs: MutableSequence[RpcSpec] = []
        while self._handlers:
            name, handler = self._handlers.popitem()
            atomic.exec_lua(_new_lua_func(chan, handler=handler), ())
            atomic.exec(_new_viml_func(handler=handler), False)
            specs.append((name, handler))

        return atomic, specs


def nil_handler(name: str) -> RpcCallable:
    def handler(nvim: Nvim, *args: Any) -> None:
        log.warn("MISSING RPC HANDLER FOR: %s - %s", name, args)

    return RpcCallable(name=name, blocking=True, handler=handler)
