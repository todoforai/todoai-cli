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
from todoforai_edge.frontend_ws import TodoStreamError
from todoforai_edge.edge import TODOforAIEdge
from todoforai_edge.config import Config as EdgeConfig

from .config_store import TODOCLIConfig
from .edge_client import init_edge
from .project_selectors import select_project, select_agent, _get_display_name, _get_item_id, _get_terminal_input, _get_single_char_input
from .prompt_input import create_session, get_interactive_input
from .message_display import MessageDisplay

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
            if resolved == wp_resolved or resolved.startswith(wp_resolved + os.sep):
                return agent, wp_resolved
    return None, None


class TODOCLITool:
    def __init__(self, config: TODOCLIConfig, message_display: MessageDisplay = None):
        self.config = config
        self.edge = None
        self.message_display = message_display or MessageDisplay()
        self._embedded_edge: Optional[TODOforAIEdge] = None
        self._embedded_edge_task: Optional[asyncio.Task] = None

    async def init_edge(self, api_url: Optional[str] = None, skip_validation: bool = False):
        """Initialize TODOforAI Edge client"""
        self.edge = await init_edge(
            api_url,
            self.config.data.get("default_api_url"),
            self.config.data.get("default_api_key"),
            skip_validation=skip_validation
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
                print(f"Embedded edge running (id: {self._embedded_edge.edge_id})", file=sys.stderr)
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
    
    async def create_todo(self, content: str, project_id: str, agent: AgentSettings) -> Dict[str, Any]:
        try:
            return await self.edge.add_message(
                project_id=project_id,
                content=content,
                agent_settings=agent
            )
        except Exception as e:
            print(f"Error: Failed to create TODO: {e}", file=sys.stderr)
            sys.exit(1)

    async def watch_todo(self, todo_id: str, project_id: str, timeout: int, json_output: bool, agent_settings: dict = None, auto_approve: bool = False) -> bool:
        """Watch todo execution. Returns True if completed normally, False if interrupted."""
        ignore = {
            "todo:msg_start", "todo:msg_done", "todo:msg_error", "todo:msg_stop_sequence",
            "todo:msg_meta_ai", "todo:status", "block:end",
            "block:start_text", "block:start_shell", "block:start_createfile",
            "block:start_modifyfile", "block:start_mcp", "block:start_catfile",
        }

        def on_message(msg_type: str, payload: Dict[str, Any]):
            if msg_type == "block:message":
                sys.stdout.write(payload.get("content", ""))
                sys.stdout.flush()
            elif msg_type == "BLOCK_UPDATE":
                updates = payload.get("updates", {})
                result = updates.get("result")
                if result:
                    print(f"\n--- Block Result ---\n{result}", file=sys.stderr)
            elif msg_type == "block:start_universal":
                skip = {"userId", "messageId", "todoId", "blockId", "block_type"}
                block_type = payload.get("block_type", "UNIVERSAL")
                info = {k: v for k, v in payload.items() if k not in skip}
                parts = [f"{k}={v}" for k, v in info.items()]
                extra = f" {' '.join(parts)}" if parts else ""
                print(f"\n\033[32m*\033[0m {block_type}{extra}", file=sys.stderr)
            elif msg_type not in ignore:
                print(f"[{msg_type}]", file=sys.stderr)

        # Get edge config for approvals
        edge_id = None
        root_path = ""
        # Prefer embedded edge if running (--edge mode)
        if self._embedded_edge and self._embedded_edge.edge_id:
            edge_id = self._embedded_edge.edge_id
            # Use the embedded edge's workspace path
            wp = self._embedded_edge.edge_config.config.get("workspacepaths", [])
            root_path = wp[0] if wp else ""
        elif agent_settings:
            edges_mcp_configs = agent_settings.get("edgesMcpConfigs", {})
            edge_id = next(iter(edges_mcp_configs.keys()), None)
            if edge_id:
                edge_config = edges_mcp_configs.get(edge_id, {})
                todoai_config = edge_config.get("todoai_edge") or edge_config.get("todoai", {})
                workspace_paths = todoai_config.get("workspacePaths", [])
                root_path = workspace_paths[0] if workspace_paths else ""

        # Track approve-all state
        approve_all = auto_approve

        def _classify_block(block_info):
            """Classify block type from block_info."""
            btype = block_info.get("type", "")
            bp = block_info.get("payload", {})
            # Universal blocks have block_type in payload
            inner = bp.get("block_type", "").lower()
            if "createfile" in btype or inner in ("create", "createfile"):
                return "file"
            if "modifyfile" in btype or inner in ("modify", "modifyfile", "update"):
                return "file"
            if "catfile" in btype or inner in ("catfile", "read", "readfile"):
                return "read"
            if "mcp" in btype or inner == "mcp":
                return "mcp"
            return "shell"

        async def _approve_block(ws, block_id, message_id, block_payload, block_kind):
            """Send BLOCK_APPROVAL_INTENT so backend handles the approval flow."""
            msg = {
                "type": "BLOCK_APPROVAL_INTENT",
                "payload": {
                    "todoId": todo_id,
                    "messageId": message_id,
                    "blockId": block_id,
                    "decision": "allow_once",
                }
            }
            await ws.ws.send(json.dumps(msg))

        async def handle_approval(ws, block_info):
            nonlocal approve_all
            block_id = block_info.get("blockId")
            message_id = block_info.get("messageId")
            block_payload = block_info.get("payload", {})
            block_kind = _classify_block(block_info)

            # Label for display
            labels = {"file": "File", "read": "Read File", "mcp": "MCP", "shell": "Shell"}
            type_label = labels.get(block_kind, "Shell")

            # Get content to display - try various payload fields
            display = (
                block_payload.get("path") or
                block_payload.get("filePath") or
                block_payload.get("content") or
                block_payload.get("command") or
                block_payload.get("name") or
                ""
            )
            if not display:
                skip_keys = {"userId", "messageId", "todoId", "blockId", "block_type"}
                useful = {k: v for k, v in block_payload.items() if k not in skip_keys and v}
                display = str(useful) if useful else "<pending>"
            if len(display) > 200:
                display = display[:200] + "..."

            # Auto-approve if user chose 'a' or --edge mode
            if approve_all:
                print(f"\n\033[33m⚠ Auto-approving [{type_label}]\033[0m {display}", file=sys.stderr)
                await _approve_block(ws, block_id, message_id, block_payload, block_kind)
                return

            # Prompt user
            print(f"\n\033[33m⚠ Action awaiting approval:\033[0m", file=sys.stderr)
            print(f"  [{type_label}] {display}", file=sys.stderr)

            try:
                response = _get_single_char_input("  [Y]es / [n]o / [a]ll? ")
            except (KeyboardInterrupt, EOFError):
                response = "n"

            if response.lower() == "a":
                approve_all = True
                response = "y"

            if response.lower() in ("y", ""):
                await _approve_block(ws, block_id, message_id, block_payload, block_kind)
            else:
                await ws.send_block_deny(todo_id, message_id, block_id)
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
            print("\n\033[33mInterrupting... (Ctrl+C again to force exit)\033[0m", file=sys.stderr)
            if watch_task:
                watch_task.cancel()

        old_handler = signal.signal(signal.SIGINT, lambda s, f: handle_interrupt())

        try:
            watch_task = asyncio.create_task(
                self.edge.wait_for_todo_completion(
                    todo_id, timeout, on_message, project_id,
                    approval_handler=handle_approval if edge_id else None
                )
            )
            result = await watch_task
            print()  # newline after streaming
            if not result.get("success"):
                msg_type = result.get("type", "unknown")
                if msg_type == "todo:msg_error":
                    print(f"Error: {result.get('payload', {}).get('error', 'unknown')}", file=sys.stderr)
                else:
                    print(f"Warning: Stopped: {msg_type}", file=sys.stderr)
            return True
        except asyncio.CancelledError:
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
    
    async def resume_todo(self, todo_id: str, timeout: int, json_output: bool, auto_approve: bool = False):
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

        # Interactive loop with prompt_toolkit
        session = create_session()
        while True:
            try:
                follow_up = await get_interactive_input(session)
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
                await self.edge.add_message(
                    project_id=project_id,
                    content=follow_up,
                    agent_settings=agent,
                    todo_id=todo_id,
                    allow_queue=True
                )
                await self.watch_todo(todo_id, project_id, timeout, json_output, agent, auto_approve=auto_approve)
            except (KeyboardInterrupt, EOFError):
                break

    def _get_frontend_url(self, project_id: str, todo_id: str) -> str:
        api_url = self.edge.api_url
        
        # Map API URLs to frontend URLs
        if "localhost:4000" in api_url or "127.0.0.1:4000" in api_url:
            return f"http://localhost:3000/{project_id}/{todo_id}"
        else:
            # Production or other environments
            return f"https://todofor.ai/{project_id}/{todo_id}"
    
    async def interactive_set_defaults(self):
        """Interactive defaults configuration"""
        # Initialize edge for project/agent listing
        try:
            await self.init_edge()
        except SystemExit:
            # If API key validation fails, we can still set API key/URL
            pass
        
        config_options = [
            {"key": "default_project_id", "name": "Default Project", "type": "project"},
            {"key": "default_agent_name", "name": "Default Agent", "type": "agent"},
            {"key": "default_api_url", "name": "Default API URL", "type": "text"},
            {"key": "default_api_key", "name": "Default API Key", "type": "password"},
        ]
        
        while True:
            print("\nConfigure Default Settings", file=sys.stderr)
            print("="*40, file=sys.stderr)
            print("Which default config values would you like to change?", file=sys.stderr)
            print("", file=sys.stderr)
            
            # Show current values
            for i, option in enumerate(config_options, 1):
                current = self.config.data.get(option["key"])
                if option["type"] == "password" and current:
                    # Show first4***last4 for API key
                    if len(current) > 8:
                        current = f"{current[:4]}***{current[-4:]}"
                    else:
                        current = "***set***"
                elif option["type"] == "project" and current:
                    # Show project name only (no ID)
                    project_name = None
                    for recent in self.config.data.get("recent_projects", []):
                        if recent.get("id") == current:
                            project_name = recent.get("name")
                            break
                    current = project_name or current
                elif not current:
                    current = "not set"
                print(f" [{i}] {option['name']}: {current}", file=sys.stderr)
            
            print("\n [0] Exit configuration", file=sys.stderr)
            print("", file=sys.stderr)
            
            try:
                choice = _get_terminal_input("Select option to configure: ").strip()
                if choice == "0" or not choice:
                    print("Exiting configuration", file=sys.stderr)
                    return
                
                idx = int(choice) - 1
                if 0 <= idx < len(config_options):
                    option = config_options[idx]
                    await self._configure_option(option)
                else:
                    print(f"Please enter a number between 0 and {len(config_options)}", file=sys.stderr)
                    
            except ValueError:
                print("Please enter a valid number", file=sys.stderr)
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled", file=sys.stderr)
                return
    
    async def _configure_option(self, option: Dict[str, str]):
        """Configure a specific option"""
        print(f"\nConfiguring: {option['name']}", file=sys.stderr)
        
        if option["type"] == "project":
            await self._configure_project()
        elif option["type"] == "agent":
            await self._configure_agent()
        elif option["type"] == "text":
            self._configure_text_option(option)
        elif option["type"] == "password":
            self._configure_password_option(option)
    
    async def _configure_project(self):
        """Configure default project"""
        try:
            if not self.edge:
                print("Error: Need valid API key to list projects", file=sys.stderr)
                return
                
            projects = await self.get_projects()
            
            print("\nAvailable Projects:", file=sys.stderr)
            for i, project in enumerate(projects, 1):
                project_name = _get_display_name(project)
                project_id = _get_item_id(project)
                print(f" [{i}] {project_name}", file=sys.stderr)
                if project_id != project_name:
                    print(f"     {project_id}", file=sys.stderr)
            
            print(" [0] Enter custom project ID", file=sys.stderr)
            print("", file=sys.stderr)
            
            while True:
                choice = _get_terminal_input("Select project: ").strip()
                if choice == "0":
                    project_id = _get_terminal_input("Enter project ID: ").strip()
                    if project_id:
                        self.config.set_default_project(project_id)
                        print(f"Default project set to: {project_id}", file=sys.stderr)
                    break
                elif choice:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(projects):
                            project = projects[idx]
                            project_id = _get_item_id(project)
                            project_name = _get_display_name(project)
                            self.config.set_default_project(project_id, project_name)
                            print(f"Default project set to: {project_name}", file=sys.stderr)
                            break
                        else:
                            print(f"Please enter a number between 0 and {len(projects)}", file=sys.stderr)
                    except ValueError:
                        print("Please enter a valid number", file=sys.stderr)
                        
        except Exception as e:
            print(f"Error: Failed to configure project: {e}", file=sys.stderr)
    
    async def _configure_agent(self):
        """Configure default agent"""
        try:
            if not self.edge:
                print("Error: Need valid API key to list agents", file=sys.stderr)
                return
                
            agents = await self.get_agents()
            
            print("\nAvailable Agents:", file=sys.stderr)
            for i, agent in enumerate(agents, 1):
                agent_name = _get_display_name(agent)
                print(f" [{i}] {agent_name}", file=sys.stderr)
            
            print(" [0] Enter custom agent name", file=sys.stderr)
            print("", file=sys.stderr)
            
            while True:
                choice = _get_terminal_input("Select agent: ").strip()
                if choice == "0":
                    agent_name = _get_terminal_input("Enter agent name: ").strip()
                    if agent_name:
                        self.config.set_default_agent(agent_name)
                        print(f"Default agent set to: {agent_name}", file=sys.stderr)
                    break
                elif choice:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(agents):
                            agent = agents[idx]
                            agent_name = _get_display_name(agent)
                            self.config.set_default_agent(agent_name, agent)
                            print(f"Default agent set to: {agent_name}", file=sys.stderr)
                            break
                        else:
                            print(f"Please enter a number between 0 and {len(agents)}", file=sys.stderr)
                    except ValueError:
                        print("Please enter a valid number", file=sys.stderr)
                        
        except Exception as e:
            print(f"Error: Failed to configure agent: {e}", file=sys.stderr)
    
    def _configure_text_option(self, option: Dict[str, str]):
        """Configure a text option"""
        current = self.config.data.get(option["key"])
        if current:
            print(f"Current value: {current}", file=sys.stderr)
        
        value = _get_terminal_input(f"Enter {option['name'].lower()}: ").strip()
        if value:
            getattr(self.config, f"set_{option['key']}")(value)
            print(f"{option['name']} set to: {value}", file=sys.stderr)
    
    def _configure_password_option(self, option: Dict[str, str]):
        """Configure a password option"""
        import getpass
        
        current = self.config.data.get(option["key"])
        if current:
            print("Current value: ***set***", file=sys.stderr)
        
        try:
            value = getpass.getpass(f"Enter {option['name'].lower()}: ")
            if value:
                getattr(self.config, f"set_{option['key']}")(value)
                print(f"{option['name']} set", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nCancelled", file=sys.stderr)
    
    async def _auto_create_agent(self, resolved_path: str, agents: list) -> dict:
        """Create a new agent with workspace path configured. Returns agent dict."""
        folder_name = os.path.basename(resolved_path) or "default"

        # 1. Create agent
        resp = (await async_request(self.edge, 'post', '/api/v1/agents', {})).json()
        agent_id = resp.get("id") or resp.get("agentSettingsId")
        if not agent_id:
            raise RuntimeError(f"Failed to create agent: {resp}")
        agent_settings_id = resp.get("agentSettingsId", agent_id)

        # 2. Set name
        await async_request(self.edge, 'put', f'/api/v1/agents/{agent_id}/settings', {
            "agentSettingsId": agent_settings_id,
            "updates": {"name": folder_name}
        })

        # 3. Find edge ID: reuse from existing agents, or fetch /edges
        edge_id = None
        for a in agents:
            keys = list(a.get("edgesMcpConfigs", {}).keys())
            if keys:
                edge_id = keys[0]
                break
        if not edge_id:
            edges = (await async_request(self.edge, 'get', '/api/v1/edges', None)).json()
            if edges and isinstance(edges, list):
                edge_id = edges[0].get("id")
        if not edge_id:
            raise RuntimeError("No edge available to configure workspace path")

        # 4. Set workspace path
        await async_request(self.edge, 'put', f'/api/v1/agents/{agent_id}/edge-mcp-config', {
            "agentSettingsId": agent_settings_id,
            "edgeId": edge_id,
            "mcpName": "todoai_edge",
            "config": {"workspacePaths": [resolved_path]}
        })

        # 5. Re-fetch full agent from server (has ownerId etc.)
        all_agents = await self.get_agents()
        for a in all_agents:
            if _get_item_id(a) == agent_id:
                return a
        # Fallback: return create response merged with essentials
        resp["name"] = folder_name
        resp["edgesMcpConfigs"] = {
            edge_id: {"todoai_edge": {"workspacePaths": [resolved_path]}}
        }
        return resp

    async def run(self, args):
        """Main execution"""
        # Init edge with URL priority: --api-url > env (inside Edge Config) > config default > package default
        await self.init_edge(args.api_url, skip_validation=not args.safe)

        # Start embedded edge if --edge flag is set
        if args.edge is not None:
            await self.start_embedded_edge(workspace_path=os.path.abspath(args.edge))

        # Pre-resolve agent by workspace path BEFORE prompting for input
        pre_matched_agent = None
        if args.path:
            agents = await self.get_agents()
            agent, matched_wp = _find_agent_by_path(agents, args.path)
            if agent:
                print(f"AgentSettings: {_get_display_name(agent)} Paths: {_get_agent_workspace_paths(agent)}", file=sys.stderr)
                self.config.set_default_agent(_get_display_name(agent), agent)
                pre_matched_agent = agent
            else:
                resolved = os.path.realpath(args.path)
                print(f"No agent found for '{resolved}', creating one...", file=sys.stderr)
                try:
                    pre_matched_agent = await self._auto_create_agent(resolved, agents)
                    print(f"AgentSettings: {pre_matched_agent['name']} Paths: {_get_agent_workspace_paths(pre_matched_agent)}", file=sys.stderr)
                    self.config.set_default_agent(pre_matched_agent['name'], pre_matched_agent)
                except Exception as e:
                    print(f"Error: Failed to auto-create agent: {e}", file=sys.stderr)
                    sys.exit(1)

        # Read content from positional prompt args, stdin, or interactive input
        if args.prompt:
            content = ' '.join(args.prompt)
        else:
            content = self.read_stdin()

        # Check if we can skip fetching lists (have defaults or CLI args)
        has_project = args.project or self.config.data.get("default_project_id")
        # For agent, we need full settings with id - name alone isn't enough
        # If --agent flag provided, we must fetch to get full settings
        stored_agent = self.config.data.get("default_agent_settings")
        has_agent = pre_matched_agent or ((stored_agent and stored_agent.get("id")) and not args.agent)

        # Only fetch lists if needed for selection (or --safe mode)
        projects = None
        agents = agents if args.path else None
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
            print("="*50, file=sys.stderr)

        # Select project
        if args.project:
            if projects:
                project = findBy(projects, lambda p: _get_item_id(p) == args.project)
                if not project:
                    print(f"Error: Project ID '{args.project}' not found", file=sys.stderr)
                    sys.exit(1)
                project_id, project_name = _get_item_id(project), _get_display_name(project)
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
                set_default=self.config.set_default_project
            )

        # Select agent
        if pre_matched_agent:
            agent = pre_matched_agent
        elif args.agent:
            # --agent flag requires fetching list to get full settings with id
            agent = findBy(agents, lambda a: args.agent.lower() in _get_display_name(a).lower())
            if not agent:
                print(f"Error: Agent '{args.agent}' not found", file=sys.stderr)
                print("Available agents:", file=sys.stderr)
                for a in agents:
                    print(f"  - {_get_display_name(a)}", file=sys.stderr)
                sys.exit(1)
            # Save as default for next time
            self.config.set_default_agent(_get_display_name(agent), agent)
        elif stored_agent and stored_agent.get("id") and not agents:
            # Fast path: use stored settings with valid id
            agent = stored_agent
        else:
            agent = select_agent(
                agents,
                default_agent_name=self.config.data.get("default_agent_name"),
                set_default=self.config.set_default_agent
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
                await async_request(self.edge, 'put',
                    f"/api/v1/agents/{agent_id}/edge-mcp-config",
                    {"agentSettingsId": agent_id, "edgeId": edge_id,
                     "mcpName": "todoai_edge", "config": edge_mcp_config})
                print(f"Registered edge {edge_id} with agent settings", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Failed to register edge with agent: {e}", file=sys.stderr)
            # Also update local dict for watch_todo
            configs = agent.get("edgesMcpConfigs") or {}
            configs[edge_id] = {"todoai_edge": edge_mcp_config}
            agent["edgesMcpConfigs"] = configs

        # Create TODO
        print(f"\nCreating TODO...", file=sys.stderr)
        todo = await self.create_todo(content, project_id, agent)
        
        # Get the actual todo ID from response
        actual_todo_id = todo.get('id', todo_id)
        self.config.data["last_todo_id"] = actual_todo_id
        self.config.save_config()
        frontend_url = self._get_frontend_url(project_id, actual_todo_id)

        # Output result
        if args.json:
            todo_with_url = todo.copy()
            todo_with_url['frontend_url'] = frontend_url
            print(json.dumps(todo_with_url, indent=2))
        else:
            print(f"TODO created: {frontend_url}", file=sys.stderr)

        # Watch for completion (default behavior)
        if not args.no_watch:
            auto_approve = args.edge is not None
            await self.watch_todo(actual_todo_id, project_id, args.timeout, args.json, agent, auto_approve=auto_approve)

        # Interactive mode (default) - continue conversation
        if not args.print_mode and not args.no_watch:
            print("\n" + "─" * 40, file=sys.stderr)
            session = create_session()
            auto_approve = args.edge is not None
            while True:
                try:
                    follow_up = await get_interactive_input(session)
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

                    # Send follow-up message to same todo
                    print("─" * 40, file=sys.stderr)
                    await self.edge.add_message(
                        project_id=project_id,
                        content=follow_up,
                        agent_settings=agent,
                        todo_id=actual_todo_id,
                        allow_queue=True
                    )
                    await self.watch_todo(actual_todo_id, project_id, args.timeout, args.json, agent, auto_approve=auto_approve)
                except (KeyboardInterrupt, EOFError):
                    break

        # Clean up embedded edge if running
        await self.stop_embedded_edge()

def main():
    parser = argparse.ArgumentParser(
        description="Create TODOs and stream results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  todoai "Research AI trends"               # Prompt as argument
  todoai -p "Quick task"                    # Print mode (non-interactive)
  echo "Piped content" | todoai             # Pipe from stdin
  todoai --path /my/project "Fix the bug"  # Explicit workspace path
  todoai --edge "Run locally"               # Execute blocks in this process
        """
    )
    # Ensure first Ctrl+C exits immediately with a message (exit code 130 = SIGINT)
    signal.signal(signal.SIGINT, _exit_on_sigint)

    parser.add_argument('prompt', nargs='*', help='Prompt text (if omitted, reads from stdin or interactive input)')
    parser.add_argument('--path', default='.', help='Workspace path (auto-selects agent by matching workspacePaths, defaults to cwd)')
    parser.add_argument('--project', help='Project ID (will prompt if not provided)')
    parser.add_argument('--agent', '-a', help='Agent name (partial match, will prompt if not provided)')
    parser.add_argument('--todo-id', help='Custom TODO ID (auto-generated if not provided)')
    # TODO: --resume without ID should list todos for the agentSettings matched by path/folder
    parser.add_argument('--resume', '-r', metavar='TODO_ID', nargs='?', const='__pick__',
                        help='Resume existing todo (without ID: show picker for current agent)')
    parser.add_argument('--continue', '-c', action='store_true', dest='continue_last',
                        help='Continue the most recent todo for the current agent')
    parser.add_argument('--api-url', help='API URL (overrides environment and saved default)')
    parser.add_argument('--json', action='store_true', help='Output result as JSON')
    parser.add_argument('--no-watch', action='store_true', help='Create todo and exit without watching for completion')
    parser.add_argument('-p', '--print', action='store_true', dest='print_mode', help='Non-interactive: run single message and exit')
    parser.add_argument('--timeout', type=int, default=300, help='Watch timeout in seconds (default: 300)')
    parser.add_argument('--safe', action='store_true', help='Validate API key and fetch lists upfront')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--edge', nargs='?', const='.', default=None, metavar='WORKSPACE',
                        help='Start embedded edge for local block execution (optionally specify workspace path, default: cwd)')
    parser.add_argument('--config-path', metavar='PATH', help='Custom config file path')

    # Config management
    config_group = parser.add_argument_group('configuration')
    config_group.add_argument('--set-defaults', action='store_true', help='Interactive configuration of default settings')
    config_group.add_argument('--set-default-project', metavar='PROJECT_ID', help='Set default project ID')
    config_group.add_argument('--set-default-agent', metavar='AGENT_NAME', help='Set default agent name')
    config_group.add_argument('--set-default-api-url', metavar='API_URL', help='Set default API URL')
    config_group.add_argument('--set-default-api-key', metavar='API_KEY', help='Set default API key')
    config_group.add_argument('--show-config', action='store_true', help='Show current configuration (includes path)')
    config_group.add_argument('--reset-config', action='store_true', help='Reset configuration file at current path')
    
    args = parser.parse_args()
    
    # Build config (with optional custom path)
    cfg = TODOCLIConfig(path_arg=args.config_path)
    
    # Handle config commands
    if args.show_config:
        print(f"Config file: {cfg.config_path}")
        print(json.dumps(cfg.data, indent=2))
        return
    
    if args.reset_config:
        if cfg.config_path.exists():
            cfg.config_path.unlink()
            print(f"Configuration reset: {cfg.config_path}")
        else:
            print("No configuration file to reset")
        return
    
    if args.set_defaults:
        tool = TODOCLITool(cfg)
        asyncio.run(tool.interactive_set_defaults())
        return
    
    if args.set_default_project or args.set_default_agent or args.set_default_api_url or args.set_default_api_key:
        if args.set_default_project:
            cfg.set_default_project(args.set_default_project)
            print(f"Default project set to: {args.set_default_project}")
        if args.set_default_agent:
            cfg.set_default_agent(args.set_default_agent)
            print(f"Default agent set to: {args.set_default_agent}")
        if args.set_default_api_url:
            cfg.set_default_api_url(args.set_default_api_url)
            print(f"Default API URL set to: {args.set_default_api_url}")
        if args.set_default_api_key:
            cfg.set_default_api_key(args.set_default_api_key)
            print(f"Default API key set")
        return

    # Main async execution
    asyncio.run(_async_main(cfg, args))


async def _async_main(cfg: TODOCLIConfig, args: argparse.Namespace) -> None:
    """Async entry point for the main CLI workflow."""
    tool = TODOCLITool(cfg)

    if args.resume or args.continue_last:
        await tool.init_edge(args.api_url, skip_validation=not args.safe)
        if args.edge is not None:
            await tool.start_embedded_edge(workspace_path=os.path.abspath(args.edge))
        try:
            todo_id = args.resume if (args.resume and args.resume != '__pick__') else None
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
            await tool.resume_todo(todo_id, args.timeout, args.json, auto_approve=args.edge is not None)
        finally:
            await tool.stop_embedded_edge()
    else:
        await tool.run(args)

if __name__ == "__main__":
    main()