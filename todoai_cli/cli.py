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
from typing import Optional

# Try to import todoforai_edge components
# Note: The heavy lifting for edge initialization and config is now handled in internal modules.
from todoforai_edge.utils import findBy

# New internal modules
from .config_store import TODOCLIConfig
from .edge_client import init_edge
from .selectors import select_project, select_agent, _get_display_name, _get_item_id


class TODOCLITool:
    def __init__(self, config: TODOCLIConfig):
        self.config = config
        self.edge = None
    
    async def init_edge(self, api_url: Optional[str] = None):
        """Initialize TODOforAI Edge client (validates API key)"""
        self.edge = await init_edge(api_url, self.config.data.get("default_api_url"))
    
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
    
    async def get_projects(self):
        """Get available projects"""
        try:
            return await self.edge.list_projects()
        except Exception as e:
            print(f"❌ Error fetching projects: {e}", file=sys.stderr)
            sys.exit(1)
    
    async def get_agents(self):
        """Get available agent settings"""
        try:
            return await self.edge.list_agent_settings()
        except Exception as e:
            print(f"❌ Error fetching agents: {e}", file=sys.stderr)
            sys.exit(1)
    
    def confirm_creation(self, content: str, project_name: str, project_id: str, agent_name: str, todo_id: str, skip_confirm: bool = False) -> bool:
        """Show confirmation dialog before creating TODO"""
        if skip_confirm:
            return True
            
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
            response = input("\nCreate this TODO? (y/N): ").strip().lower()
            return response in ['y', 'yes']
        except KeyboardInterrupt:
            print("\n❌ Cancelled", file=sys.stderr)
            return False
    
    async def create_todo(self, content: str, project_id: str, agent: dict) -> dict:
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
    
    async def run(self, args):
        """Main execution"""
        # Init edge with URL priority: --api-url > env (inside Edge Config) > config default > package default
        await self.init_edge(args.api_url)
        
        # Read content from stdin
        content = self.read_stdin()
        
        # Get projects and agents
        projects = await self.get_projects()
        agents = await self.get_agents()
        
        # DEBUG: Print actual project structure
        print("DEBUG - Projects structure:", file=sys.stderr)
        for i, project in enumerate(projects[:2]):  # Only first 2 to avoid spam
            print(f"Project {i}: {json.dumps(project, indent=2)}", file=sys.stderr)
        print("DEBUG - Agents structure:", file=sys.stderr)
        for i, agent in enumerate(agents[:2]):  # Only first 2 to avoid spam
            print(f"Agent {i}: {json.dumps(agent, indent=2)}", file=sys.stderr)
        print("="*50, file=sys.stderr)
        
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
        
        # Show confirmation
        if not self.confirm_creation(content, project_name, project_id, _get_display_name(agent), todo_id, args.yes):
            print("❌ Cancelled", file=sys.stderr)
            sys.exit(1)
        
        # Create TODO
        print(f"\n🚀 Creating TODO...", file=sys.stderr)
        todo = await self.create_todo(content, project_id, agent)
        
        # Output result
        if args.json:
            print(json.dumps(todo, indent=2))
        else:
            print(f"✅ TODO created successfully!", file=sys.stderr)
            print(f"   ID: {todo.get('id', todo_id)}", file=sys.stderr)
            print(f"   Project: {project_name}", file=sys.stderr)
            print(f"   Agent: {_get_display_name(agent)}", file=sys.stderr)

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
    
    parser.add_argument('--project', '-p', help='Project ID (will prompt if not provided)')
    parser.add_argument('--agent', '-a', help='Agent name (partial match, will prompt if not provided)')
    parser.add_argument('--todo-id', help='Custom TODO ID (auto-generated if not provided)')
    parser.add_argument('--api-url', help='API URL (overrides environment and saved default)')
    parser.add_argument('--json', action='store_true', help='Output result as JSON')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    parser.add_argument('--config-path', metavar='PATH', help='Use specific config file path (overrides default)')
    
    # Config management
    config_group = parser.add_argument_group('configuration')
    config_group.add_argument('--set-default-project', metavar='PROJECT_ID', help='Set default project ID')
    config_group.add_argument('--set-default-agent', metavar='AGENT_NAME', help='Set default agent name')
    config_group.add_argument('--set-default-api-url', metavar='API_URL', help='Set default API URL')
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
    
    if args.set_default_project or args.set_default_agent or args.set_default_api_url:
        if args.set_default_project:
            cfg.set_default_project(args.set_default_project)
            print(f"✅ Default project set to: {args.set_default_project}")
        if args.set_default_agent:
            cfg.set_default_agent(args.set_default_agent)
            print(f"✅ Default agent set to: {args.set_default_agent}")
        if args.set_default_api_url:
            cfg.set_default_api_url(args.set_default_api_url)
            print(f"✅ Default API URL set to: {args.set_default_api_url}")
        return
    
    # Main execution
    tool = TODOCLITool(cfg)
    asyncio.run(tool.run(args))

if __name__ == "__main__":
    main()