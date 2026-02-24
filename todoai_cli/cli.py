#!/usr/bin/env python3
"""
TODOforAI CLI - Create and manage todos
Usage: todoai "prompt text" | echo "content" | todoai [options]
"""

import argparse
import asyncio
import json
import os
import sys
import uuid
import signal
from typing import Optional, List, Dict, Any

from todoforai_edge.utils import findBy, async_request
from todoforai_edge.types import ProjectListItem, AgentSettings
from todoforai_edge.edge import TODOforAIEdge
from todoforai_edge.config import Config as EdgeConfig

from .config_store import TODOCLIConfig
from .edge_client import init_edge
from .project_selectors import (
    select_project,
    select_agent,
    _get_display_name,
    _get_item_id,
    _get_terminal_input,
)
from .message_display import MessageDisplay
from .logo import print_logo
from .watch import watch_todo as _watch_todo
from .interactive import interactive_loop
from .cli_args import build_parser, handle_config_commands


def _exit_on_sigint(signum, frame):
    """Handle SIGINT (Ctrl+C) by exiting with a message and code 130."""
    print("\nCancelled by user (Ctrl+C)", file=sys.stderr)
    sys.exit(130)


def _get_agent_workspace_paths(agent: dict) -> list:
    """Extract all workspace paths from an agent's edge configs."""
    paths = []
    for edge_config in agent.get("edgesMcpConfigs", {}).values():
        todoai_config = edge_config.get("todoai_edge") or edge_config.get("todoai", {})
        paths.extend(todoai_config.get("workspacePaths", []))
    return paths


def _find_agent_by_path(agents: list, path: str):
    """Find agent whose workspacePaths contain the given path. Returns (agent, matched_workspace) or (None, None)."""
    resolved = os.path.realpath(path)
    for agent in agents:
        for wp in _get_agent_workspace_paths(agent):
            wp_resolved = os.path.realpath(wp)
            if resolved == wp_resolved:
                return agent, wp_resolved
    return None, None


class TODOCLITool:
    def __init__(self, config: TODOCLIConfig, message_display: MessageDisplay = None):
        self.config = config
        self.edge = None
        self.message_display = message_display or MessageDisplay()
        self._embedded_edge: Optional[TODOforAIEdge] = None
        self._embedded_edge_task: Optional[asyncio.Task] = None

    async def init_edge(
        self, api_url: Optional[str] = None, skip_validation: bool = False
    ):
        """Initialize TODOforAI Edge client"""
        self.edge = await init_edge(
            api_url,
            self.config.data.get("default_api_url"),
            self.config.data.get("default_api_key"),
            skip_validation=skip_validation,
        )

    async def start_embedded_edge(self, workspace_path: str = "/tmp/todoforai"):
        """Start an embedded edge runtime for local block execution."""
        cfg = EdgeConfig()
        cfg.api_url = self.edge.api_url
        cfg.api_key = self.edge.api_key

        self._embedded_edge = TODOforAIEdge(cfg)
        await self._embedded_edge.ensure_api_key(prompt_if_missing=False)

        # Add workspace path so the edge knows where to execute
        if workspace_path:
            self._embedded_edge.add_workspace_path = os.path.abspath(workspace_path)

        # Start the edge in the background (it runs a reconnect loop)
        self._embedded_edge_task = asyncio.create_task(self._embedded_edge.start())

        # Wait for the edge to connect and get its edge_id
        for _ in range(50):  # up to 5 seconds
            if self._embedded_edge.edge_id:
                print(
                    f"Embedded edge running (id: {self._embedded_edge.edge_id})",
                    file=sys.stderr,
                )
                return
            await asyncio.sleep(0.1)

        print("Warning: Embedded edge did not get an edge_id in time", file=sys.stderr)

    async def stop_embedded_edge(self):
        """Stop the embedded edge runtime."""
        if self._embedded_edge_task:
            self._embedded_edge_task.cancel()
            try:
                await self._embedded_edge_task
            except asyncio.CancelledError:
                pass
            self._embedded_edge_task = None
        self._embedded_edge = None

    def read_stdin(self) -> str:
        """Read content from stdin or prompt for interactive input"""
        if sys.stdin.isatty():
            # Interactive mode - single line, Enter sends
            try:
                content = _get_terminal_input("TODO> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled", file=sys.stderr)
                sys.exit(1)

            if not content:
                print("Error: Empty input", file=sys.stderr)
                sys.exit(1)

            return content
        else:
            # Piped input mode
            content = sys.stdin.read().strip()
            if not content:
                print("Error: Empty input", file=sys.stderr)
                sys.exit(1)

            return content

    async def get_projects(self) -> List[ProjectListItem]:
        """Get available projects"""
        try:
            return await self.edge.list_projects()
        except Exception as e:
            print(f"Error: Failed to fetch projects: {e}", file=sys.stderr)
            sys.exit(1)

    async def get_agents(self) -> List[AgentSettings]:
        """Get available agent settings"""
        try:
            return await self.edge.list_agent_settings()
        except Exception as e:
            print(f"Error: Failed to fetch agents: {e}", file=sys.stderr)
            sys.exit(1)

    async def create_todo(
        self, content: str, project_id: str, agent: AgentSettings
    ) -> Dict[str, Any]:
        try:
            return await self.edge.add_message(
                project_id=project_id, content=content, agent_settings=agent
            )
        except Exception as e:
            print(f"Error: Failed to create TODO: {e}", file=sys.stderr)
            sys.exit(1)

    async def watch_todo(
        self,
        todo_id: str,
        project_id: str,
        timeout: int,
        json_output: bool,
        agent_settings: dict = None,
        auto_approve: bool = False,
        interrupt_on_cancel: bool = True,
        suppress_cancel_notice: bool = False,
        activity_event=None,
    ) -> bool:
        """Watch todo execution. Delegates to watch module."""
        return await _watch_todo(
            self.edge,
            todo_id,
            project_id,
            timeout,
            json_output,
            agent_settings=agent_settings,
            auto_approve=auto_approve,
            embedded_edge=self._embedded_edge,
            interrupt_on_cancel=interrupt_on_cancel,
            suppress_cancel_notice=suppress_cancel_notice,
            activity_event=activity_event,
        )

    async def resume_todo(
        self, todo_id: str, timeout: int, json_output: bool, auto_approve: bool = False
    ):
        """Resume an existing todo - show history and enter interactive mode"""
        # Fetch existing todo with messages
        todo = await self.edge.get_todo(todo_id)
        project_id = todo.get("projectId")
        agent = todo.get("agentSettings") or {"name": "default"}

        # Display existing messages
        messages = todo.get("messages", [])
        self.message_display.display_messages(messages)

        print("\n" + "─" * 40, file=sys.stderr)
        print(f"Resumed todo: {todo_id}", file=sys.stderr)

        async def _watch(interrupt_on_cancel=True, suppress_cancel_notice=False, activity_event=None):
            return await self.watch_todo(
                todo_id, project_id, timeout, json_output, agent,
                auto_approve=auto_approve,
                interrupt_on_cancel=interrupt_on_cancel,
                suppress_cancel_notice=suppress_cancel_notice,
                activity_event=activity_event,
            )

        async def _send(content):
            await self.edge.add_message(
                project_id=project_id, content=content,
                agent_settings=agent, todo_id=todo_id,
            )

        await interactive_loop(_watch, _send)

    def _get_frontend_url(self, project_id: str, todo_id: str) -> str:
        api_url = self.edge.api_url

        # Map API URLs to frontend URLs
        if "localhost:4000" in api_url or "127.0.0.1:4000" in api_url:
            return f"http://localhost:3000/{project_id}/{todo_id}"
        else:
            # Production or other environments
            return f"https://todofor.ai/{project_id}/{todo_id}"

    async def _auto_create_agent(self, resolved_path: str, agents: list) -> dict:
        """Create a new agent with workspace path configured. Returns agent dict."""
        folder_name = os.path.basename(resolved_path) or "default"

        # 1. Create agent
        resp = (await async_request(self.edge, "post", "/api/v1/agents", {})).json()
        agent_id = resp.get("id") or resp.get("agentSettingsId")
        if not agent_id:
            raise RuntimeError(f"Failed to create agent: {resp}")
        agent_settings_id = resp.get("agentSettingsId", agent_id)

        # 2. Set name
        await async_request(
            self.edge,
            "put",
            f"/api/v1/agents/{agent_id}/settings",
            {"agentSettingsId": agent_settings_id, "updates": {"name": folder_name}},
        )

        # 3. Find edge ID: reuse from existing agents, or fetch /edges
        edge_id = None
        for a in agents:
            keys = list(a.get("edgesMcpConfigs", {}).keys())
            if keys:
                edge_id = keys[0]
                break
        if not edge_id:
            edges = (
                await async_request(self.edge, "get", "/api/v1/edges", None)
            ).json()
            if edges and isinstance(edges, list):
                edge_id = edges[0].get("id")
        if not edge_id:
            raise RuntimeError("No edge available to configure workspace path")

        # 4. Set workspace path
        await async_request(
            self.edge,
            "put",
            f"/api/v1/agents/{agent_id}/edge-mcp-config",
            {
                "agentSettingsId": agent_settings_id,
                "edgeId": edge_id,
                "mcpName": "todoai_edge",
                "config": {"workspacePaths": [resolved_path]},
            },
        )

        # 5. Re-fetch full agent from server (has ownerId etc.)
        all_agents = await self.get_agents()
        for a in all_agents:
            if _get_item_id(a) == agent_id:
                return a
        # Fallback: return create response merged with essentials
        resp["name"] = folder_name
        resp["edgesMcpConfigs"] = {
            edge_id: {
                "todoai_edge": {"workspacePaths": [resolved_path]}
            }
        }
        return resp

    async def run(self, args):
        """Main execution"""
        # Init edge with URL priority: --api-url > env (inside Edge Config) > config default > package default
        await self.init_edge(args.api_url, skip_validation=not args.safe)

        # Start embedded edge if --edge flag is set
        if args.edge is not None:
            await self.start_embedded_edge(workspace_path=os.path.abspath(args.edge))

        # Pre-resolve agent BEFORE prompting for input (by --agent name or workspace path)
        pre_matched_agent = None
        agents = None
        if args.agent:
            agents = await self.get_agents()
            pre_matched_agent = findBy(
                agents, lambda a: args.agent.lower() in _get_display_name(a).lower()
            )
            if not pre_matched_agent:
                print(f"Error: Agent '{args.agent}' not found", file=sys.stderr)
                print("Available agents:", file=sys.stderr)
                for a in agents:
                    print(f"  - {_get_display_name(a)}", file=sys.stderr)
                sys.exit(1)
            self.config.set_default_agent(_get_display_name(pre_matched_agent), pre_matched_agent)
        elif args.path:
            agents = await self.get_agents()
            agent, matched_wp = _find_agent_by_path(agents, args.path)
            if agent:
                self.config.set_default_agent(_get_display_name(agent), agent)
                pre_matched_agent = agent
            else:
                resolved = os.path.realpath(args.path)
                print(
                    f"No agent found for '{resolved}', creating one...", file=sys.stderr
                )
                try:
                    pre_matched_agent = await self._auto_create_agent(resolved, agents)
                    self.config.set_default_agent(
                        pre_matched_agent["name"], pre_matched_agent
                    )
                except Exception as e:
                    print(f"Error: Failed to auto-create agent: {e}", file=sys.stderr)
                    sys.exit(1)

        if pre_matched_agent:
            paths = _get_agent_workspace_paths(pre_matched_agent)
            path_label = "Path" if len(paths) == 1 else "Paths"
            path_str = paths[0] if len(paths) == 1 else str(paths)
            print(
                f"\033[90mAgent:\033[0m \033[38;2;249;110;46m{_get_display_name(pre_matched_agent)}\033[0m \033[90m│ {path_label}:\033[0m \033[36m{path_str}\033[0m",
                file=sys.stderr,
            )

        # Read content from positional prompt args, stdin, or interactive input
        if args.prompt:
            content = " ".join(args.prompt)
        else:
            content = self.read_stdin()

        # Check if we can skip fetching lists (have defaults or CLI args)
        has_project = args.project or self.config.data.get("default_project_id")
        # For agent, we need full settings with id - name alone isn't enough
        # If --agent flag provided, we must fetch to get full settings
        stored_agent = self.config.data.get("default_agent_settings")
        has_agent = pre_matched_agent or (
            (stored_agent and stored_agent.get("id")) and not args.agent
        )

        # Only fetch lists if needed for selection (or --safe mode)
        projects = None
        if not has_project or not has_agent or args.safe or args.debug:
            projects = await self.get_projects()
            if not agents:
                agents = await self.get_agents()

        # Remove DEBUG prints for cleaner output
        if args.debug and projects and agents:
            print("DEBUG - Projects structure:", file=sys.stderr)
            for i, project in enumerate(projects[:2]):  # Only first 2 to avoid spam
                print(f"Project {i}: {json.dumps(project, indent=2)}", file=sys.stderr)
            print("DEBUG - Agents structure:", file=sys.stderr)
            for i, agent in enumerate(agents[:2]):  # Only first 2 to avoid spam
                print(f"Agent {i}: {json.dumps(agent, indent=2)}", file=sys.stderr)
            print("=" * 50, file=sys.stderr)

        # Select project
        if args.project:
            if projects:
                project = findBy(projects, lambda p: _get_item_id(p) == args.project)
                if not project:
                    print(
                        f"Error: Project ID '{args.project}' not found", file=sys.stderr
                    )
                    sys.exit(1)
                project_id, project_name = (
                    _get_item_id(project),
                    _get_display_name(project),
                )
            else:
                project_id, project_name = args.project, args.project
        elif self.config.data.get("default_project_id") and not projects:
            # Fast path: use default without fetching list
            project_id = self.config.data.get("default_project_id")
            project_name = self.config.data.get("default_project_name") or project_id
        else:
            project_id, project_name = select_project(
                projects,
                default_project_id=self.config.data.get("default_project_id"),
                set_default=self.config.set_default_project,
            )

        # Select agent
        if pre_matched_agent:
            agent = pre_matched_agent
        elif stored_agent and stored_agent.get("id") and not agents:
            # Fast path: use stored settings with valid id
            agent = stored_agent
        else:
            agent = select_agent(
                agents,
                default_agent_name=self.config.data.get("default_agent_name"),
                set_default=self.config.set_default_agent,
            )

        # Generate TODO ID if not provided
        todo_id = args.todo_id or str(uuid.uuid4())

        # Register embedded edge with the agent settings on the server so the
        # server-side agent can discover it and generate blocks for execution.
        if self._embedded_edge and self._embedded_edge.edge_id:
            edge_id = self._embedded_edge.edge_id
            agent_id = agent.get("id", "")
            wp = os.path.abspath(args.edge) if args.edge else "."
            edge_mcp_config = {
                "workspacePaths": [wp],
            }
            # Update server-side agent settings
            try:
                await async_request(
                    self.edge,
                    "put",
                    f"/api/v1/agents/{agent_id}/edge-mcp-config",
                    {
                        "agentSettingsId": agent_id,
                        "edgeId": edge_id,
                        "mcpName": "todoai_edge",
                        "config": edge_mcp_config,
                    },
                )
                print(f"Registered edge {edge_id} with agent settings", file=sys.stderr)
            except Exception as e:
                print(
                    f"Warning: Failed to register edge with agent: {e}", file=sys.stderr
                )
            # Also update local dict for watch_todo
            configs = agent.get("edgesMcpConfigs") or {}
            configs[edge_id] = {"todoai_edge": edge_mcp_config}
            agent["edgesMcpConfigs"] = configs

        # Create TODO
        todo = await self.create_todo(content, project_id, agent)

        # Get the actual todo ID from response
        actual_todo_id = todo.get("id", todo_id)
        self.config.data["last_todo_id"] = actual_todo_id
        self.config.save_config()
        frontend_url = self._get_frontend_url(project_id, actual_todo_id)

        # Output result
        if args.json:
            todo_with_url = todo.copy()
            todo_with_url["frontend_url"] = frontend_url
            print(json.dumps(todo_with_url, indent=2))
        else:
            print(f"\033[90mTODO:\033[0m \033[36m{frontend_url}\033[0m", file=sys.stderr)

        # Watch for completion (default behavior)
        if not args.no_watch:
            auto_approve = args.edge is not None
            await self.watch_todo(
                actual_todo_id,
                project_id,
                args.timeout,
                args.json,
                agent,
                auto_approve=auto_approve,
            )

        # Interactive mode (default) - continue conversation
        if not args.print_mode and not args.no_watch:
            print("\n" + "─" * 40, file=sys.stderr)
            auto_approve = args.edge is not None

            async def _watch(interrupt_on_cancel=True, suppress_cancel_notice=False, activity_event=None):
                return await self.watch_todo(
                    actual_todo_id, project_id, args.timeout, args.json, agent,
                    auto_approve=auto_approve,
                    interrupt_on_cancel=interrupt_on_cancel,
                    suppress_cancel_notice=suppress_cancel_notice,
                    activity_event=activity_event,
                )

            async def _send(content):
                await self.edge.add_message(
                    project_id=project_id, content=content,
                    agent_settings=agent, todo_id=actual_todo_id,
                )

            await interactive_loop(_watch, _send)

        # Clean up embedded edge if running
        await self.edge.close_frontend_ws()
        await self.stop_embedded_edge()


def main():
    parser = build_parser()
    # Ensure first Ctrl+C exits immediately with a message (exit code 130 = SIGINT)
    signal.signal(signal.SIGINT, _exit_on_sigint)

    args = parser.parse_args()

    # Build config (with optional custom path)
    cfg = TODOCLIConfig(path_arg=args.config_path)

    # Handle config commands
    if handle_config_commands(cfg, args):
        return

    # Print logo on interactive startup
    if sys.stderr.isatty():
        print_logo()

    # Main async execution
    try:
        asyncio.run(_async_main(cfg, args))
    except KeyboardInterrupt:
        pass


async def _async_main(cfg: TODOCLIConfig, args: argparse.Namespace) -> None:
    """Async entry point for the main CLI workflow."""
    tool = TODOCLITool(cfg)

    if args.resume or args.continue_last:
        await tool.init_edge(args.api_url, skip_validation=not args.safe)
        if args.edge is not None:
            await tool.start_embedded_edge(workspace_path=os.path.abspath(args.edge))
        try:
            todo_id = (
                args.resume if (args.resume and args.resume != "__pick__") else None
            )
            if not todo_id:
                # -c or --resume without ID: resolve from current agent's todos
                # TODO: fetch todos for the agentSettings matched by path,
                #       for -c pick the most recent, for --resume show a picker
                last_todo_id = cfg.data.get("last_todo_id")
                if last_todo_id:
                    todo_id = last_todo_id
                else:
                    print("Error: No recent todo found for this agent", file=sys.stderr)
                    sys.exit(1)
            await tool.resume_todo(
                todo_id, args.timeout, args.json, auto_approve=args.edge is not None
            )
        finally:
            await tool.stop_embedded_edge()
    else:
        await tool.run(args)


if __name__ == "__main__":
    main()
