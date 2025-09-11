import asyncio
import concurrent.futures
import logging
from functools import wraps, partial
from typing import Any, Callable, TypeVar, Coroutine

T = TypeVar("T")

executor = concurrent.futures.ThreadPoolExecutor()


def safe_handler(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T | None]]:
    """Decorate an async handler to log exceptions instead of crashing."""

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> T | None:
        try:
            return await fn(*args, **kwargs)
        except Exception as e:  # pragma: no cover - defensive logging
            logging.error("Handler crash: %s", e)
            return None

    return wrapper


async def run_blocking(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Execute ``func`` in a thread to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(func, *args, **kwargs))
