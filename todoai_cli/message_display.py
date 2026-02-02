"""Message display formatting for CLI output."""

import sys
from typing import Dict, Any, Callable, List, Optional

# ANSI color codes
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


# Block renderers - easy to extend without modifying existing code
BlockRenderer = Callable[[Dict[str, Any]], Optional[str]]


def render_text(block: Dict[str, Any]) -> Optional[str]:
    content = block.get("content", "")
    return content if content else None


def render_shell(block: Dict[str, Any]) -> Optional[str]:
    content = block.get("content", "")
    if not content:
        return None
    preview = content[:100] + "..." if len(content) > 100 else content
    return f"  {YELLOW}[Shell]{RESET} {preview}"


def render_file_op(block: Dict[str, Any], label: str) -> Optional[str]:
    content = block.get("content", "")
    file_path = block.get("file_path", "")
    if not content and not file_path:
        return None
    path_info = f" ({file_path})" if file_path else ""
    preview = content[:100] + "..." if len(content) > 100 else content
    return f"  {YELLOW}[{label}{path_info}]{RESET} {preview}"


def render_create(block: Dict[str, Any]) -> Optional[str]:
    return render_file_op(block, "Create")


def render_modify(block: Dict[str, Any]) -> Optional[str]:
    return render_file_op(block, "Modify")


def render_mcp(block: Dict[str, Any]) -> Optional[str]:
    content = block.get("content", "")
    tool_name = block.get("tool_name", "")
    if not content and not tool_name:
        return None
    tool_info = f" ({tool_name})" if tool_name else ""
    preview = content[:100] + "..." if len(content) > 100 else content
    return f"  {YELLOW}[MCP{tool_info}]{RESET} {preview}"


# Registry of block renderers - add new types here
BLOCK_RENDERERS: Dict[str, BlockRenderer] = {
    "TEXT": render_text,
    "SHELL": render_shell,
    "CREATE": render_create,
    "MODIFY": render_modify,
    "MCP": render_mcp,
}


class MessageDisplay:
    """Formats and displays todo messages."""

    def __init__(self, renderers: Dict[str, BlockRenderer] = None):
        self.renderers = renderers or BLOCK_RENDERERS

    def render_block(self, block: Dict[str, Any]) -> Optional[str]:
        """Render a single block using registered renderer."""
        block_type = block.get("type", "TEXT")
        renderer = self.renderers.get(block_type)
        if renderer:
            return renderer(block)
        return None

    def render_user_message(self, msg: Dict[str, Any]) -> str:
        """Render a user message."""
        content = msg.get("content", "")
        return f"\n{BLUE}* User:{RESET} {content}"

    def render_assistant_message(self, msg: Dict[str, Any]) -> List[str]:
        """Render an assistant message, returns list of lines."""
        lines = [f"\n{GREEN}* Assistant:{RESET}"]
        blocks = msg.get("blocks", [])

        for block in blocks:
            rendered = self.render_block(block)
            if rendered:
                lines.append(rendered)

        return lines

    def display_messages(self, messages: List[Dict[str, Any]], file=None):
        """Display a list of messages."""
        if file is None:
            file = sys.stderr

        if not messages:
            return

        print(f"\nPrevious messages ({len(messages)}):", file=file)
        print("─" * 40, file=file)

        for msg in messages:
            role = msg.get("role", "unknown")

            if role == "user":
                print(self.render_user_message(msg), file=file)
            else:
                lines = self.render_assistant_message(msg)
                for line in lines:
                    # TEXT blocks go to stdout, metadata to stderr
                    block_type = "TEXT" if not line.startswith("  ") else "other"
                    if line.startswith(f"\n{GREEN}") or line.startswith("  "):
                        print(line, file=file)
                    else:
                        print(line)  # TEXT content to stdout


# Default instance for convenience
default_display = MessageDisplay()


def display_messages(messages: List[Dict[str, Any]], file=None):
    """Convenience function using default display."""
    default_display.display_messages(messages, file)
