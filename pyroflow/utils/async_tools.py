from typing import Union, List, Callable, Optional, Awaitable, Tuple, overload
from concurrent.futures import ThreadPoolExecutor

from .typings import NestedContainer, MaybeAwaitable, _True, _False, _P, _T
from .validate_tools import is_exception, iscoroutinefunction_wrapped
from .iter_tools import flat_cont

import asyncio
import functools
import logging
import contextvars
import inspect


log = logging.getLogger(__file__)


@overload
async def to_thread(
    func: Callable[_P, _T],
    *args: _P.args,
    executor: Optional[ThreadPoolExecutor] = None,
    log_exc: bool = True,
    **kwargs: _P.kwargs,
) -> _T: ...
@overload
async def to_thread(
    func: Callable[_P, _T],
    *args: _P.args,
    executor: Optional[ThreadPoolExecutor] = None,
    log_exc: bool = True,
    return_exc: _True,
    **kwargs: _P.kwargs,
) -> Union[_T, Exception]: ...

async def to_thread(
    func,
    *args,
    executor = None,
    log_exc = True, 
    return_exc = False, 
    **kwargs,
    ):
    
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    func = functools.partial(ctx.run, func, *args, **kwargs)
    
    
    try:
        return await loop.run_in_executor(executor, func)
    except Exception as e:
        if log_exc:
            log.exception("error in to_thread")
        
        if return_exc:
            return e
        
        raise


@overload
async def gather_helper(
    *coros: NestedContainer[Awaitable[_T]],
    log_exc: bool = True,
) -> Tuple[_T, ...]: ...
@overload
async def gather_helper(
    *coros: NestedContainer[Awaitable[_T]],
    return_exc: _True,
    log_exc: bool = True,
) -> Tuple[Union[_T, Exception], ...]: ...

async def gather_helper(
    *coros,
    return_exc = False,
    log_exc = True,
    ):

    results = await asyncio.gather(*flat_cont(coros), return_exceptions=return_exc)

    if log_exc:
        for r in results:
            if is_exception(r):
                log.error("error in gather_helper", exc_info=r)

    return results

@overload
async def safe_await(
    coro: Awaitable[_T],
    *,
    log_exc: bool = True,
) -> Union[_T, Exception]: ...
@overload
async def safe_await(
    coro: Awaitable[_T],
    *,
    return_exc: _False,
    log_exc: bool = True,
) -> _T: ...
@overload
async def safe_await(
    coro: NestedContainer[Awaitable[_T]],
    *,
    log_exc: bool = True,
) -> List[Union[_T, Exception]]: ...
@overload
async def safe_await(
    coro: NestedContainer[Awaitable[_T]],
    *,
    return_exc: _False,
    log_exc: bool = True,
) -> List[_T]: ...
@overload
async def safe_await(
    *coro: NestedContainer[Awaitable[_T]],
    log_exc: bool = True,
) -> List[Union[_T, Exception]]: ...
@overload
async def safe_await(
    *coro: NestedContainer[Awaitable[_T]],
    return_exc: _False,
    log_exc: bool = True,
) -> List[_T]: ...

async def safe_await(
    *coros,
    return_exc = True,
    log_exc = True,
    ):

    results = []

    for coro in flat_cont(coros):
        try:
            result = await coro
        except Exception as e:
            if log_exc:
                log.exception("Error in safe_await")
                
            result = e

        if is_exception(result):
            if not return_exc:
                raise result

        results.append(result)

    return results[0] if len(results) == 1 else results



@overload
async def maybe_awaitable(
    awaitable_or_callable: MaybeAwaitable[_P, _T],
    *args: _P.args,
    executor: Optional[ThreadPoolExecutor] = None,
    log_exc: bool = True,
    **kwargs: _P.kwargs,
) -> _T: ...
@overload
async def maybe_awaitable(
    awaitable_or_callable: MaybeAwaitable[_P, _T],
    *args: _P.args,
    executor: Optional[ThreadPoolExecutor] = None,
    return_exc: _True,
    log_exc: bool = True,
    **kwargs: _P.kwargs,
) -> Union[_T, Exception]: ...

async def maybe_awaitable(
    awaitable_or_callable,
    *args,
    executor = None, 
    return_exc = False, 
    log_exc = True,
    **kwargs,
):
    
    if inspect.isawaitable(awaitable_or_callable):
        if args or kwargs:
            raise TypeError(
                "Cannot pass args/kwargs to an already-created awaitable"
            )
        return await safe_await(
            awaitable_or_callable, 
            return_exc=return_exc, 
            log_exc=log_exc, 
        )
    elif iscoroutinefunction_wrapped(awaitable_or_callable):
        return await safe_await(
            awaitable_or_callable(*args, **kwargs),
            return_exc=return_exc,
            log_exc=log_exc,
        )
    elif callable(awaitable_or_callable):
        return await to_thread(
            awaitable_or_callable,
            *args,
            executor=executor,
            return_exc=return_exc,
            log_exc=log_exc,
            **kwargs,
        )
    else:
        raise TypeError(
            f"Expected an Awaitable or Callable, got {type(awaitable_or_callable).__name__!r}"
        )





__all__ = [
    "to_thread", 
    "gather_helper", 
    "safe_await", 
    "maybe_awaitable"
]