"""Watch todo execution and handle block approvals."""

import asyncio
import json
import signal
import sys

from todoforai_edge.frontend_ws import TodoStreamError

from .project_selectors import _async_single_char_input


def _classify_block(block_info):
    """Classify block type from block_info."""
    btype = block_info.get("type", "")
    bp = block_info.get("payload", {})
    inner = bp.get("block_type", "").lower()
    if "createfile" in btype or inner in ("create", "createfile"):
        return "file"
    if "modifyfile" in btype or inner in ("modify", "modifyfile", "update"):
        return "file"
    if "catfile" in btype or inner in ("catfile", "read", "readfile"):
        return "read"
    if "mcp" in btype or inner == "mcp":
        return "mcp"
    if "shell" in btype or inner in ("shell", "bash") or bp.get("cmd"):
        return "shell"
    return "unknown"


def _block_display(block_info):
    """Return (type_label, display_text) for a block."""
    labels = {"file": "File", "read": "Read File", "mcp": "MCP", "shell": "Shell"}
    block_payload = block_info.get("payload", {})
    block_kind = _classify_block(block_info)
    inner = block_payload.get("block_type", "")
    type_label = labels.get(block_kind, inner or "Tool")
    skip_keys = {"userId", "messageId", "todoId", "blockId", "block_type", "edge_id", "timeout"}
    known_keys = {"path", "filePath", "content", "cmd", "name"}
    display = (
        block_payload.get("path")
        or block_payload.get("filePath")
        or block_payload.get("content")
        or block_payload.get("cmd")
        or block_payload.get("name")
        or ""
    )
    rest = {k: v for k, v in block_payload.items() if k not in skip_keys | known_keys and v}
    if rest:
        extra = " ".join(f"{k}={v}" for k, v in rest.items())
        display = f"{display} ({extra})" if display else extra
    if not display:
        display = "<pending>"
    if len(display) > 200:
        display = display[:200] + "..."
    return type_label, display


async def _approve_block(ws, block_id, message_id, todo_id):
    """Send BLOCK_APPROVAL_INTENT so backend handles the approval flow."""
    msg = {
        "type": "BLOCK_APPROVAL_INTENT",
        "payload": {
            "todoId": todo_id,
            "messageId": message_id,
            "blockId": block_id,
            "decision": "allow_once",
        },
    }
    await ws.ws.send(json.dumps(msg))


async def watch_todo(
    edge,
    todo_id,
    project_id,
    timeout,
    json_output,
    agent_settings=None,
    auto_approve=False,
    embedded_edge=None,
    interrupt_on_cancel=True,
    suppress_cancel_notice=False,
    activity_event=None,
) -> bool:
    """Watch todo execution. Returns True if completed normally, False if interrupted.

    activity_event: optional asyncio.Event set whenever visible output is produced.
    The interactive loop uses this to cancel the prompt before output lands.
    """
    ignore = {
        "todo:msg_start",
        "todo:msg_done",
        "todo:msg_stop_sequence",
        "todo:msg_meta_ai",
        "todo:status",
        "todo:new_message_created",
        "block:end",
        "block:start_shell",
        "block:start_createfile",
        "block:start_modifyfile",
        "block:start_mcp",
        "block:start_catfile",
    }

    def _signal_activity():
        if activity_event and not activity_event.is_set():
            activity_event.set()

    def on_message(msg_type, payload):
        if msg_type == "block:message":
            sys.stdout.write(payload.get("content", ""))
            sys.stdout.flush()
            _signal_activity()
        elif msg_type == "BLOCK_UPDATE":
            updates = payload.get("updates", {})
            status = updates.get("status")
            result = updates.get("result")
            if result:
                print(f"\n--- Block Result ---\n{result}", file=sys.stderr)
                _signal_activity()
            elif status == "AWAITING_APPROVAL":
                block_id = payload.get("blockId", "")
                suffix = f" ({block_id})" if block_id else ""
                print(
                    f"\n\033[33m⚠ Awaiting approval{suffix}\033[0m", file=sys.stderr
                )
                _signal_activity()
            elif status and status not in ("COMPLETED", "RUNNING"):
                print(f"\n[block:update] status={status}", file=sys.stderr)
                _signal_activity()
        elif msg_type == "block:start_universal":
            skip = {"userId", "messageId", "todoId", "blockId", "block_type", "edge_id", "timeout"}
            block_type = payload.get("block_type", "UNIVERSAL")
            info = {k: v for k, v in payload.items() if k not in skip}
            parts = [f"{k}={v}" for k, v in info.items()]
            extra = f" {' '.join(parts)}" if parts else ""
            print(f"\n\033[32m*\033[0m {block_type}{extra}", file=sys.stderr)
            _signal_activity()
        elif msg_type not in ignore:
            print(f"\n[{msg_type}]", file=sys.stderr)
            _signal_activity()

    # Get edge config for approvals
    edge_id = None
    root_path = ""
    if embedded_edge and embedded_edge.edge_id:
        edge_id = embedded_edge.edge_id
        wp = embedded_edge.edge_config.config.get("workspacepaths", [])
        root_path = wp[0] if wp else ""
    elif agent_settings:
        edges_mcp_configs = agent_settings.get("edgesMcpConfigs", {})
        edge_id = next(iter(edges_mcp_configs.keys()), None)
        if edge_id:
            edge_config = edges_mcp_configs.get(edge_id, {})
            todoai_config = edge_config.get("todoai_edge") or edge_config.get(
                "todoai", {}
            )
            workspace_paths = todoai_config.get("workspacePaths", [])
            root_path = workspace_paths[0] if workspace_paths else ""

    approve_all = auto_approve

    async def handle_approval(ws, blocks):
        nonlocal approve_all

        if approve_all:
            for bi in blocks:
                tl, disp = _block_display(bi)
                print(
                    f"\n\033[33m⚠ Auto-approving [{tl}]\033[0m {disp}",
                    file=sys.stderr,
                )
                await _approve_block(
                    ws, bi.get("blockId"), bi.get("messageId"), todo_id
                )
            return

        n = len(blocks)
        print(
            f"\n\033[33m⚠ {n} action(s) awaiting approval:\033[0m", file=sys.stderr
        )
        for bi in blocks:
            tl, disp = _block_display(bi)
            print(f"  [{tl}] {disp}", file=sys.stderr)
            ctx = bi.get("approvalContext") or {}
            tool_installs = ctx.get("toolInstalls", [])
            if tool_installs:
                print(f"  \033[36m↳ Install tools: {', '.join(tool_installs)}\033[0m", file=sys.stderr)

        try:
            response = await _async_single_char_input("  [Y]es / [n]o / [a]ll? ")
        except asyncio.CancelledError:
            print("\n  (approval prompt cancelled — skipping)", file=sys.stderr)
            return
        except (KeyboardInterrupt, EOFError):
            response = "n"

        if response.lower() == "a":
            approve_all = True
            response = "y"

        if response.lower() in ("y", ""):
            for bi in blocks:
                await _approve_block(
                    ws, bi.get("blockId"), bi.get("messageId"), todo_id
                )
        else:
            for bi in blocks:
                await ws.send_block_deny(
                    todo_id, bi.get("messageId"), bi.get("blockId")
                )
            print("  \033[31m✗ Denied\033[0m", file=sys.stderr)

    # Set up interrupt handling with double Ctrl+C to force exit
    watch_task = None
    interrupt_count = 0

    def handle_interrupt():
        nonlocal interrupt_count
        interrupt_count += 1
        if interrupt_count >= 2:
            print("\n\033[31mForce exit (double Ctrl+C)\033[0m", file=sys.stderr)
            sys.exit(130)
        print(
            "\n\033[33mInterrupting... (Ctrl+C again to force exit)\033[0m",
            file=sys.stderr,
        )
        if watch_task:
            watch_task.cancel()

    old_handler = signal.signal(signal.SIGINT, lambda s, f: handle_interrupt())

    try:
        watch_task = asyncio.create_task(
            edge.wait_for_todo_completion(
                todo_id,
                timeout,
                on_message,
                project_id if interrupt_on_cancel else None,
                approval_handler=handle_approval,
            )
        )
        result = await watch_task
        print()
        if not result.get("success"):
            msg_type = result.get("type", "unknown")
            print(f"Warning: Stopped: {msg_type}", file=sys.stderr)
        return True
    except asyncio.CancelledError:
        if not suppress_cancel_notice:
            print("\033[33mInterrupted\033[0m", file=sys.stderr)
        return False
    except TodoStreamError as e:
        print(f"Error: Stream error: {e}", file=sys.stderr)
        sys.exit(1)
    except asyncio.TimeoutError:
        print(f"\nTimeout after {timeout}s", file=sys.stderr)
        sys.exit(1)
    finally:
        signal.signal(signal.SIGINT, old_handler)
