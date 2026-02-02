#!/usr/bin/env python3
"""
TODOforAI CLI - Create todos from piped input
Usage: echo "todo content" | todoai [options]
"""

import argparse
import asyncio
import json
import sys
import uuid
import signal
from typing import Optional, List, Dict, Any

from todoforai_edge.utils import findBy
from todoforai_edge.types import ProjectListItem, AgentSettings
from todoforai_edge.frontend_ws import TodoStreamError

from .config_store import TODOCLIConfig
from .edge_client import init_edge
from .project_selectors import select_project, select_agent, _get_display_name, _get_item_id, _get_terminal_input, _get_single_char_input
from .prompt_input import create_session, get_interactive_input
from .message_display import MessageDisplay
from .terminal_bench import run_terminal_bench_mode

def _exit_on_sigint(signum, frame):
    """Handle SIGINT (Ctrl+C) by exiting with a message and code 130."""
    print("\nCancelled by user (Ctrl+C)", file=sys.stderr)
    sys.exit(130)


class TODOCLITool:
    def __init__(self, config: TODOCLIConfig, message_display: MessageDisplay = None):
        self.config = config
        self.edge = None
        self.message_display = message_display or MessageDisplay()
    
    async def init_edge(self, api_url: Optional[str] = None, skip_validation: bool = False):
        """Initialize TODOforAI Edge client"""
        self.edge = await init_edge(
            api_url,
            self.config.data.get("default_api_url"),
            self.config.data.get("default_api_key"),
            skip_validation=skip_validation
        )
    
    def read_stdin(self) -> str:
        """Read content from stdin or prompt for interactive input"""
        if sys.stdin.isatty():
            # Interactive mode - prompt user for input
            print("Enter your TODO content (press Ctrl+D when done, or Ctrl+C to cancel):", file=sys.stderr)
            print("", file=sys.stderr)  # Empty line for better formatting
            
            lines = []
            try:
                while True:
                    line = input()
                    lines.append(line)
            except EOFError:
                # User pressed Ctrl+D
                pass
            
            content = '\n'.join(lines).strip()
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
    
    def confirm_creation(self, content: str, project_name: str, project_id: str, agent_name: str, todo_id: str, skip_confirm: bool = False) -> str:
        """Show confirmation dialog before creating TODO"""
        if skip_confirm:
            return "create"
            
        print("\n" + "="*60, file=sys.stderr)
        print("TODO Creation Summary", file=sys.stderr)
        print("="*60, file=sys.stderr)
        print(f"Project: {project_name}", file=sys.stderr)
        print(f"Project ID: {project_id}", file=sys.stderr)
        print(f"Agent: {agent_name}", file=sys.stderr)
        print(f"TODO ID: {todo_id}", file=sys.stderr)
        print(f"\nContent preview:", file=sys.stderr)
        print("-" * 40, file=sys.stderr)
        preview = content[:200] + "..." if len(content) > 200 else content
        print(preview, file=sys.stderr)
        print("-" * 40, file=sys.stderr)
        
        try:
            print("\nOptions: Y=create | n=cancel | a=append text | c=change config", file=sys.stderr)
            response = _get_single_char_input("Create this TODO? (Y/n/a/c): ")
            if response in ['n', 'N']:
                return "cancel"
            elif response in ['c', 'C']:
                return "config"
            elif response in ['a', 'A']:
                return "append"
            else:
                return "create"
        except KeyboardInterrupt:
            print("\nCancelled", file=sys.stderr)
            return "cancel"
    
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

    async def watch_todo(self, todo_id: str, project_id: str, timeout: int, json_output: bool) -> bool:
        """Watch todo execution. Returns True if completed normally, False if interrupted."""
        ignore = {
            "todo:msg_start", "todo:msg_done", "todo:msg_error", "todo:msg_stop_sequence",
            "todo:msg_meta_ai", "todo:status", "block:end",
            "block:start_text", "block:start_shell", "block:start_createfile",
            "block:start_modifyfile", "block:start_mcp",
        }

        def on_message(msg_type: str, payload: Dict[str, Any]):
            if msg_type == "block:message":
                sys.stdout.write(payload.get("content", ""))
                sys.stdout.flush()
            elif msg_type == "block:start_universal":
                skip = {"userId", "messageId", "todoId", "blockId", "block_type"}
                block_type = payload.get("block_type", "UNIVERSAL")
                info = {k: v for k, v in payload.items() if k not in skip}
                parts = [f"{k}={v}" for k, v in info.items()]
                extra = f" {' '.join(parts)}" if parts else ""
                print(f"\n\033[32m*\033[0m {block_type}{extra}", file=sys.stderr)
            elif msg_type not in ignore:
                print(f"[{msg_type}]", file=sys.stderr)

        # Set up interrupt handling
        watch_task = None

        def handle_interrupt():
            print("\n\033[33mInterrupting...\033[0m", file=sys.stderr)
            if watch_task:
                watch_task.cancel()

        old_handler = signal.signal(signal.SIGINT, lambda s, f: handle_interrupt())

        try:
            watch_task = asyncio.create_task(
                self.edge.wait_for_todo_completion(todo_id, timeout, on_message)
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
    
    async def resume_todo(self, todo_id: str, timeout: int, json_output: bool):
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
                await self.watch_todo(todo_id, project_id, timeout, json_output)
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
    
    async def run(self, args):
        """Main execution"""
        # Init edge with URL priority: --api-url > env (inside Edge Config) > config default > package default
        await self.init_edge(args.api_url, skip_validation=not args.safe)

        # Read content from stdin
        content = self.read_stdin()

        # Check if we can skip fetching lists (have defaults or CLI args)
        has_project = args.project or self.config.data.get("default_project_id")
        # For agent, we need full settings with id - name alone isn't enough
        # If --agent flag provided, we must fetch to get full settings
        stored_agent = self.config.data.get("default_agent_settings")
        has_agent = (stored_agent and stored_agent.get("id")) and not args.agent

        # Only fetch lists if needed for selection (or --safe mode)
        projects = None
        agents = None
        if not has_project or not has_agent or args.safe or args.debug:
            projects = await self.get_projects()
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

        while True:
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
            if args.agent:
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
            
            # Confirmation loop with append support (no reselection needed)
            proceed = False
            while True:
                action = self.confirm_creation(content, project_name, project_id, _get_display_name(agent), todo_id, args.yes)
                
                if action == "cancel":
                    print("Cancelled", file=sys.stderr)
                    sys.exit(1)
                elif action == "config":
                    print("\nQuick Settings Change", file=sys.stderr)
                    await self.interactive_set_defaults()
                    # Clear CLI args so we re-select with new defaults
                    args.project = None
                    args.agent = None
                    break  # break inner loop to reselect with new defaults
                elif action == "append":
                    extra = _get_terminal_input("Enter text to append (empty to skip): ").strip()
                    if extra:
                        content = (content + ("\n" if content and not content.endswith("\n") else "") + extra)
                        print("Appended.", file=sys.stderr)
                    else:
                        print("No changes.", file=sys.stderr)
                    continue  # re-show confirmation with updated content
                else:  # action == "create"
                    proceed = True
                    break
            
            if proceed:
                break
            else:
                continue

        # Create TODO
        print(f"\nCreating TODO...", file=sys.stderr)
        todo = await self.create_todo(content, project_id, agent)
        
        # Get the actual todo ID from response
        actual_todo_id = todo.get('id', todo_id)
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
            await self.watch_todo(actual_todo_id, project_id, args.timeout, args.json)

        # Interactive mode - continue conversation
        if args.interactive and not args.no_watch:
            print("\n" + "─" * 40, file=sys.stderr)
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

                    # Send follow-up message to same todo
                    print("─" * 40, file=sys.stderr)
                    await self.edge.add_message(
                        project_id=project_id,
                        content=follow_up,
                        agent_settings=agent,
                        todo_id=actual_todo_id,
                        allow_queue=True
                    )
                    await self.watch_todo(actual_todo_id, project_id, args.timeout, args.json)
                except (KeyboardInterrupt, EOFError):
                    break

def main():
    parser = argparse.ArgumentParser(
        description="Create TODOs and stream results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  echo "Research AI trends" | todoai        # Creates and watches
  echo "Quick task" | todoai -y             # Skip confirmation
  echo "Fire and forget" | todoai --no-watch
  echo "Long task" | todoai --timeout 600   # 10 min timeout
        """
    )
    # Ensure first Ctrl+C exits immediately with a message (exit code 130 = SIGINT)
    signal.signal(signal.SIGINT, _exit_on_sigint)

    parser.add_argument('--project', '-p', help='Project ID (will prompt if not provided)')
    parser.add_argument('--agent', '-a', help='Agent name (partial match, will prompt if not provided)')
    parser.add_argument('--todo-id', help='Custom TODO ID (auto-generated if not provided)')
    parser.add_argument('--resume', '-r', metavar='TODO_ID', help='Resume existing todo')
    parser.add_argument('--api-url', help='API URL (overrides environment and saved default)')
    parser.add_argument('--json', action='store_true', help='Output result as JSON')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    parser.add_argument('--no-watch', action='store_true', help='Create todo and exit without watching for completion')
    parser.add_argument('-i', '--interactive', action='store_true', help='Stay in interactive mode after completion')
    parser.add_argument('--timeout', type=int, default=300, help='Watch timeout in seconds (default: 300)')
    parser.add_argument('--safe', action='store_true', help='Validate API key and fetch lists upfront')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--config-path', metavar='PATH', help='Custom config file path')

    # Terminal-Bench mode
    tbench_group = parser.add_argument_group('terminal-bench')
    tbench_group.add_argument('--terminal-bench', action='store_true',
                              help='Terminal-Bench mode: direct LLM execution with tmux bridging')
    tbench_group.add_argument('--model', '-m', help='Model to use (for --terminal-bench mode)')
    
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

    # Terminal-Bench mode - special execution path (sync, doesn't need asyncio)
    if args.terminal_bench:
        sys.exit(run_terminal_bench_mode(args))

    # Main async execution
    asyncio.run(_async_main(cfg, args))


async def _async_main(cfg: TODOCLIConfig, args: argparse.Namespace) -> None:
    """Async entry point for the main CLI workflow."""
    tool = TODOCLITool(cfg)

    if args.resume:
        await tool.init_edge(args.api_url, skip_validation=not args.safe)
        await tool.resume_todo(args.resume, args.timeout, args.json)
    else:
        await tool.run(args)

if __name__ == "__main__":
    main()