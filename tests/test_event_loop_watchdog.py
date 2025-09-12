import asyncio
import logging
import time
import contextlib

from async_utils import event_loop_watchdog


def test_event_loop_watchdog_logs_on_delay(caplog):
    caplog.set_level(logging.ERROR)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(
            event_loop_watchdog(
                loop, interval=0.05, threshold=0.05, logger=logging.getLogger("spectre")
            )
        )
        await asyncio.sleep(0)  # allow watchdog to start
        time.sleep(0.2)  # block the event loop
        await asyncio.sleep(0.1)  # give watchdog time to log
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(run())
    asyncio.set_event_loop(asyncio.new_event_loop())

    assert any("behind schedule" in record.message for record in caplog.records)
