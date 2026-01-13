"""Rich input handling with prompt_toolkit."""

import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input import create_input

COMMANDS = ["/help", "/exit", "/quit", "/q"]


def create_session() -> PromptSession:
    """Create a prompt session with history and completions."""
    history_path = Path.home() / ".config" / "todoai-cli" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    completer = WordCompleter(COMMANDS, ignore_case=True)

    # Use /dev/tty for input when stdin is piped
    try:
        tty_input = create_input(stdin=open("/dev/tty", "r"))
    except (OSError, FileNotFoundError):
        tty_input = None

    return PromptSession(
        completer=completer,
        auto_suggest=AutoSuggestFromHistory(),
        history=FileHistory(str(history_path)),
        input=tty_input,
    )


async def get_interactive_input(session: PromptSession, prompt: str = "\u276f ") -> str:
    """Get input with completions and history (async)."""
    return (await session.prompt_async(prompt)).strip()
