#!/usr/bin/env python3
"""
TODOforAI CLI - Create todos from piped input
Usage: echo "todo content" | todoai_cli [options]
"""

import argparse
import asyncio
import json
import sys
import uuid
import signal
from typing import Optional, List, Dict, Any

# Try to import todoforai_edge components
# Note: The heavy lifting for edge initialization and config is now handled in internal modules.
from todoforai_edge.utils import findBy
from todoforai_edge.types import ProjectListItem, AgentSettings

# New internal modules
from .config_store import TODOCLIConfig
from .edge_client import init_edge
from .selectors import select_project, select_agent, _get_display_name, _get_item_id, _get_terminal_input

def _exit_on_sigint(signum, frame):
    """Handle SIGINT (Ctrl+C) by exiting with a message and code 130."""
    print("\n❌ Cancelled by user (Ctrl+C)", file=sys.stderr)
    sys.exit(130)

class TODOCLITool:
    def __init__(self, config: TODOCLIConfig):
        self.config = config
        self.edge = None
    
    async def init_edge(self, api_url: Optional[str] = None):
        """Initialize TODOforAI Edge client (validates API key)"""
        self.edge = await init_edge(
            api_url, 
            self.config.data.get("default_api_url"),
            self.config.data.get("default_api_key")
        )
    
    def read_stdin(self) -> str:
        """Read content from stdin"""
        if sys.stdin.isatty():
            print("❌ No piped input detected. Usage: echo 'content' | todoai_cli", file=sys.stderr)
            sys.exit(1)
        
        content = sys.stdin.read().strip()
        if not content:
            print("❌ Empty input", file=sys.stderr)
            sys.exit(1)
        
        return content
    
    async def get_projects(self) -> List[ProjectListItem]:
        """Get available projects"""
        try:
            return await self.edge.list_projects()
        except Exception as e:
            print(f"❌ Error fetching projects: {e}", file=sys.stderr)
            sys.exit(1)
    
    async def get_agents(self) -> List[AgentSettings]:
        """Get available agent settings"""
        try:
            return await self.edge.list_agent_settings()
        except Exception as e:
            print(f"❌ Error fetching agents: {e}", file=sys.stderr)
            sys.exit(1)
    
    def confirm_creation(self, content: str, project_name: str, project_id: str, agent_name: str, todo_id: str, skip_confirm: bool = False) -> str:
        """Show confirmation dialog before creating TODO"""
        if skip_confirm:
            return "create"
            
        print("\n" + "="*60, file=sys.stderr)
        print("📋 TODO Creation Summary", file=sys.stderr)
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
            print("\n💡 Options: Y=create • n=cancel • a=append text • c=change config", file=sys.stderr)
            response = _get_terminal_input("Create this TODO? (Y/n/a/c): ").strip().lower()
            if response in ['n', 'no', 'N']:
                return "cancel"
            elif response in ['c', 'config', 'change']:
                return "config"
            elif response in ['a', 'append']:
                return "append"
            else:
                return "create"
        except KeyboardInterrupt:
            print("\n❌ Cancelled", file=sys.stderr)
            return "cancel"
    
    async def create_todo(self, content: str, project_id: str, agent: AgentSettings) -> Dict[str, Any]:
        """Create a new TODO"""
        try:
            todo = await self.edge.add_message(
                project_id=project_id,
                content=content,
                agent_settings=agent
            )
            return todo
        except Exception as e:
            print(f"❌ Error creating TODO: {e}", file=sys.stderr)
            sys.exit(1)
    
    def _get_frontend_url(self, project_id: str, todo_id: str) -> str:
        """Generate frontend URL based on API URL"""
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
            print("\n🔧 Configure Default Settings", file=sys.stderr)
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
                print("\n❌ Cancelled", file=sys.stderr)
                return
    
    async def _configure_option(self, option: Dict[str, str]):
        """Configure a specific option"""
        print(f"\n📝 Configuring: {option['name']}", file=sys.stderr)
        
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
                print("❌ Need valid API key to list projects", file=sys.stderr)
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
                        print(f"✅ Default project set to: {project_id}", file=sys.stderr)
                    break
                elif choice:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(projects):
                            project = projects[idx]
                            project_id = _get_item_id(project)
                            project_name = _get_display_name(project)
                            self.config.set_default_project(project_id, project_name)
                            print(f"✅ Default project set to: {project_name}", file=sys.stderr)
                            break
                        else:
                            print(f"Please enter a number between 0 and {len(projects)}", file=sys.stderr)
                    except ValueError:
                        print("Please enter a valid number", file=sys.stderr)
                        
        except Exception as e:
            print(f"❌ Error configuring project: {e}", file=sys.stderr)
    
    async def _configure_agent(self):
        """Configure default agent"""
        try:
            if not self.edge:
                print("❌ Need valid API key to list agents", file=sys.stderr)
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
                        print(f"✅ Default agent set to: {agent_name}", file=sys.stderr)
                    break
                elif choice:
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(agents):
                            agent = agents[idx]
                            agent_name = _get_display_name(agent)
                            self.config.set_default_agent(agent_name)
                            print(f"✅ Default agent set to: {agent_name}", file=sys.stderr)
                            break
                        else:
                            print(f"Please enter a number between 0 and {len(agents)}", file=sys.stderr)
                    except ValueError:
                        print("Please enter a valid number", file=sys.stderr)
                        
        except Exception as e:
            print(f"❌ Error configuring agent: {e}", file=sys.stderr)
    
    def _configure_text_option(self, option: Dict[str, str]):
        """Configure a text option"""
        current = self.config.data.get(option["key"])
        if current:
            print(f"Current value: {current}", file=sys.stderr)
        
        value = _get_terminal_input(f"Enter {option['name'].lower()}: ").strip()
        if value:
            getattr(self.config, f"set_{option['key']}")(value)
            print(f"✅ {option['name']} set to: {value}", file=sys.stderr)
    
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
                print(f"✅ {option['name']} set", file=sys.stderr)
        except KeyboardInterrupt:
            print("\n❌ Cancelled", file=sys.stderr)
    
    async def run(self, args):
        """Main execution"""
        # Init edge with URL priority: --api-url > env (inside Edge Config) > config default > package default
        await self.init_edge(args.api_url)
        
        # Read content from stdin
        content = self.read_stdin()
        
        # Get projects and agents
        projects = await self.get_projects()
        agents = await self.get_agents()
        
        # Remove DEBUG prints for cleaner output
        if args.debug:
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
                project = findBy(projects, lambda p: _get_item_id(p) == args.project)
                if not project:
                    print(f"❌ Project ID '{args.project}' not found", file=sys.stderr)
                    sys.exit(1)
                project_id, project_name = _get_item_id(project), _get_display_name(project)
            else:
                project_id, project_name = select_project(
                    projects,
                    default_project_id=self.config.data.get("default_project_id"),
                    set_default=self.config.set_default_project
                )
            
            # Select agent
            if args.agent:
                agent = findBy(agents, lambda a: args.agent.lower() in _get_display_name(a).lower())
                if not agent:
                    print(f"❌ Agent '{args.agent}' not found", file=sys.stderr)
                    print("Available agents:", file=sys.stderr)
                    for a in agents:
                        print(f"  - {_get_display_name(a)}", file=sys.stderr)
                    sys.exit(1)
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
                    print("❌ Cancelled", file=sys.stderr)
                    sys.exit(1)
                elif action == "config":
                    print("\n🔧 Quick Settings Change", file=sys.stderr)
                    await self.interactive_set_defaults()
                    # Clear CLI args so we re-select with new defaults
                    args.project = None
                    args.agent = None
                    break  # break inner loop to reselect with new defaults
                elif action == "append":
                    extra = _get_terminal_input("Enter text to append (empty to skip): ").strip()
                    if extra:
                        content = (content + ("\n" if content and not content.endswith("\n") else "") + extra)
                        print("➕ Appended.", file=sys.stderr)
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
        print(f"\n🚀 Creating TODO...", file=sys.stderr)
        todo = await self.create_todo(content, project_id, agent)
        
        # Get the actual todo ID from response
        actual_todo_id = todo.get('id', todo_id)
        frontend_url = self._get_frontend_url(project_id, actual_todo_id)
        
        # Output result
        if args.json:
            # Add URL to JSON output
            todo_with_url = todo.copy()
            todo_with_url['frontend_url'] = frontend_url
            print(json.dumps(todo_with_url, indent=2))
        else:
            print(f"✅ TODO created successfully!", file=sys.stderr)
            print(f"   Project: {project_name}", file=sys.stderr)
            print(f"   Agent: {_get_display_name(agent)}", file=sys.stderr)
            print(f"   URL: {frontend_url}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(
        description="Create TODOs from piped input",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  echo "Research AI trends" | todoai_cli
  cat task.txt | todoai_cli --project abc123 --agent "gmail"
  echo "Debug issue" | todoai_cli --todo-id custom-id --json
  echo "Quick task" | todoai_cli -y  # Skip confirmation
  
Environment Variables:
  TODOFORAI_API_KEY    Your TODOforAI API key (required)
  TODOFORAI_API_URL    API URL (default: https://api.todofor.ai)
        """
    )
    # Ensure first Ctrl+C exits immediately with a message (exit code 130 = SIGINT)
    signal.signal(signal.SIGINT, _exit_on_sigint)

    parser.add_argument('--project', '-p', help='Project ID (will prompt if not provided)')
    parser.add_argument('--agent', '-a', help='Agent name (partial match, will prompt if not provided)')
    parser.add_argument('--todo-id', help='Custom TODO ID (auto-generated if not provided)')
    parser.add_argument('--api-url', help='API URL (overrides environment and saved default)')
    parser.add_argument('--json', action='store_true', help='Output result as JSON')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--config-path', metavar='PATH', help='Use specific config file path (overrides default)')
    
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
            print(f"✅ Configuration reset: {cfg.config_path}")
        else:
            print("✅ No configuration file to reset")
        return
    
    if args.set_defaults:
        tool = TODOCLITool(cfg)
        asyncio.run(tool.interactive_set_defaults())
        return
    
    if args.set_default_project or args.set_default_agent or args.set_default_api_url or args.set_default_api_key:
        if args.set_default_project:
            cfg.set_default_project(args.set_default_project)
            print(f"✅ Default project set to: {args.set_default_project}")
        if args.set_default_agent:
            cfg.set_default_agent(args.set_default_agent)
            print(f"✅ Default agent set to: {args.set_default_agent}")
        if args.set_default_api_url:
            cfg.set_default_api_url(args.set_default_api_url)
            print(f"✅ Default API URL set to: {args.set_default_api_url}")
        if args.set_default_api_key:
            cfg.set_default_api_key(args.set_default_api_key)
            print(f"✅ Default API key set")
        return
    
    # Main execution
    tool = TODOCLITool(cfg)
    asyncio.run(tool.run(args))

if __name__ == "__main__":
    main()