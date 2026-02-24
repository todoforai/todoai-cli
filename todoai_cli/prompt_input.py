"""Rich input handling with prompt_toolkit."""

import atexit
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input import create_input
from prompt_toolkit.input.base import Input
from prompt_toolkit.key_binding import KeyBindings

COMMANDS = ["/help", "/exit", "/quit", "/q"]

# Module-level tracking for cleanup
_tty_file = None
_tty_input: Optional[Input] = None


def _cleanup_tty() -> None:
    """Close the tty file handle on exit."""
    global _tty_file
    if _tty_file is not None:
        try:
            _tty_file.close()
        except Exception:
            pass
        _tty_file = None


# Register cleanup at module load
atexit.register(_cleanup_tty)


def _get_tty_input() -> Optional[Input]:
    """Get or create the tty input, reusing if already open."""
    global _tty_file, _tty_input

    if _tty_input is not None:
        return _tty_input

    try:
        _tty_file = open("/dev/tty", "r")
        _tty_input = create_input(stdin=_tty_file)
        return _tty_input
    except (OSError, FileNotFoundError):
        return None


def create_session() -> PromptSession:
    """Create a prompt session with history and completions."""
    history_path = Path.home() / ".config" / "todoai-cli" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    completer = WordCompleter(COMMANDS, ignore_case=True, sentence=True)
    tty_input = _get_tty_input()

    # In multiline mode, Enter inserts newline by default — rebind it to submit.
    # This lets pasted multiline text arrive as one string while Enter still submits.
    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        event.current_buffer.validate_and_handle()

    return PromptSession(
        completer=completer,
        auto_suggest=AutoSuggestFromHistory(),
        history=FileHistory(str(history_path)),
        input=tty_input,
        multiline=True,
        key_bindings=kb,
    )


def close_session() -> None:
    """Explicitly close tty resources. Called automatically on exit."""
    _cleanup_tty()


async def get_interactive_input(session: PromptSession, prompt: str = "\u276f ") -> str:
    """Get input with completions and history (async)."""
    try:
        return (await session.prompt_async(prompt)).strip()
    except KeyboardInterrupt:
        raise EOFError()
