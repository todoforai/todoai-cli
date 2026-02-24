"""Shared interactive watch + input loop."""

import asyncio
import sys

from prompt_toolkit.patch_stdout import patch_stdout

from .prompt_input import create_session, get_interactive_input


async def _cancel_task(task):
    """Cancel a task and suppress CancelledError."""
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, EOFError, KeyboardInterrupt):
            pass


async def interactive_loop(watch_fn, send_fn):
    """
    Concurrent watch + input loop. Races todo streaming against user input.

    Uses an activity_event so that incoming server output (streaming text,
    approval requests, block status) cancels the prompt *before* anything
    tries to read from the terminal — avoiding /dev/tty contention between
    prompt_toolkit and the approval handler.

    watch_fn(interrupt_on_cancel, suppress_cancel_notice, activity_event) -> bool
    send_fn(content) -> None
    """
    session = create_session()
    watch_task = input_task = activity_task = None
    with patch_stdout(raw=True):
        while True:
            try:
                activity_event = asyncio.Event()
                watch_task = asyncio.create_task(
                    watch_fn(
                        interrupt_on_cancel=False,
                        suppress_cancel_notice=True,
                        activity_event=activity_event,
                    )
                )
                input_task = asyncio.create_task(get_interactive_input(session))
                activity_task = asyncio.create_task(activity_event.wait())

                done, _ = await asyncio.wait(
                    {watch_task, input_task, activity_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if input_task in done:
                    # User typed something — cancel watch, process input
                    follow_up = await input_task
                    await _cancel_task(activity_task)
                    await _cancel_task(watch_task)
                else:
                    # Server activity or watch completed — cancel prompt first
                    # so terminal is free for approval handler / streaming
                    await _cancel_task(input_task)
                    await _cancel_task(activity_task)
                    if not watch_task.done():
                        await watch_task
                    continue

                if not follow_up:
                    continue
                if follow_up in ("/help", "?"):
                    print("  /exit, /quit, /q  - quit", file=sys.stderr)
                    print("  /help, ?          - show this help", file=sys.stderr)
                    print("  Tab               - show completions", file=sys.stderr)
                    print("  Arrow Right       - accept suggestion", file=sys.stderr)
                    continue
                if follow_up in ("/exit", "/quit", "/q", "q", "exit"):
                    break

                print("─" * 40, file=sys.stderr)
                await send_fn(follow_up)
                await watch_fn(interrupt_on_cancel=True, suppress_cancel_notice=False)
            except (KeyboardInterrupt, EOFError):
                # Clean up any pending tasks from this iteration
                for t in [watch_task, input_task, activity_task]:
                    await _cancel_task(t)
                break
