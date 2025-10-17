import sys
from typing import Callable, List, Dict, Tuple, Optional

from todoforai_edge.utils import findBy
from todoforai_edge.types import ProjectListItem, AgentSettings


def _get_display_name(item: Dict) -> str:
    """Get display name from item using the known structure"""
    # For projects: item["project"]["name"]
    if 'project' in item and isinstance(item['project'], dict):
        return item['project'].get('name', 'Unknown')
    
    # For agents: item["name"] 
    return item.get('name', 'Unknown')


def _get_item_id(item: Dict) -> str:
    """Get ID from item using the known structure"""
    # For projects: item["project"]["id"]
    if 'project' in item and isinstance(item['project'], dict):
        return item['project'].get('id', '')
    
    # For agents: item["id"]
    return item.get('id', '')


def _get_terminal_input(prompt: str) -> str:
    """Get input from terminal even when stdin is redirected"""
    try:
        # Try to open /dev/tty (Unix) for direct terminal access
        with open('/dev/tty', 'r') as tty:
            print(prompt, end='', file=sys.stderr)
            sys.stderr.flush()
            return tty.readline().strip()
    except (OSError, FileNotFoundError):
        # Fallback to regular input (will fail if stdin is redirected)
        return input(prompt).strip()


def select_project(projects: List[ProjectListItem], default_project_id: Optional[str], set_default: Callable[[str, str], None]) -> Tuple[str, str]:
    """Interactive project selection with default and recent support"""
    if not projects:
        print("❌ No projects available", file=sys.stderr)
        sys.exit(1)
    
    # Auto-select if only one project
    if len(projects) == 1:
        project = projects[0]
        project_id = _get_item_id(project)
        project_name = _get_display_name(project)
        print(f"Auto-selected only available project: {project_name} ({project_id})", file=sys.stderr)
        set_default(project_id, project_name)
        return project_id, project_name
    
    # Check if default project exists
    if default_project_id:
        project = findBy(projects, lambda p: _get_item_id(p) == default_project_id)
        if project:
            project_name = _get_display_name(project)
            print(f"Using default project: {project_name} ({default_project_id})", file=sys.stderr)
            return default_project_id, project_name
    
    print("\nPlease choose a project:", file=sys.stderr)
    print("", file=sys.stderr)
    
    # Display projects with numbers
    for i, project in enumerate(projects, 1):
        project_name = _get_display_name(project)
        project_id = _get_item_id(project)
        print(f" [{i}] {project_name}", file=sys.stderr)
        if project_id and project_id != project_name:
            print(f"     {project_id}", file=sys.stderr)
    
    print("", file=sys.stderr)
    
    while True:
        try:
            choice = _get_terminal_input("Please enter your numeric choice: ")
            if not choice:
                continue
                
            idx = int(choice) - 1
            if 0 <= idx < len(projects):
                selected = projects[idx]
                project_id = _get_item_id(selected)
                project_name = _get_display_name(selected)
                
                if not project_id:
                    print("❌ Selected project has no ID", file=sys.stderr)
                    continue
                
                # Save as default
                set_default(project_id, project_name)
                print(f"Selected: {project_name}", file=sys.stderr)
                return project_id, project_name
            else:
                print(f"Please enter a number between 1 and {len(projects)}", file=sys.stderr)
                
        except ValueError:
            print("Please enter a valid number", file=sys.stderr)
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled", file=sys.stderr)
            sys.exit(1)


def select_agent(agents: List[AgentSettings], default_agent_name: Optional[str], set_default: Callable[[str], None]) -> AgentSettings:
    """Interactive agent selection with default support (partial name match)"""
    if not agents:
        print("❌ No agents available", file=sys.stderr)
        sys.exit(1)
    
    # Auto-select if only one agent
    if len(agents) == 1:
        agent = agents[0]
        agent_name = _get_display_name(agent)
        print(f"Auto-selected only available agent: {agent_name}", file=sys.stderr)
        set_default(agent_name)
        return agent
    
    # Check if default agent exists
    if default_agent_name:
        agent = findBy(agents, lambda a: default_agent_name.lower() in _get_display_name(a).lower())
        if agent:
            agent_name = _get_display_name(agent)
            print(f"Using default agent: {agent_name}", file=sys.stderr)
            return agent
    
    print("\nPlease choose an agent:", file=sys.stderr)
    print("", file=sys.stderr)
    
    # Display agents with numbers
    for i, agent in enumerate(agents, 1):
        agent_name = _get_display_name(agent)
        print(f" [{i}] {agent_name}", file=sys.stderr)
    
    print("", file=sys.stderr)
    
    while True:
        try:
            choice = _get_terminal_input("Please enter your numeric choice: ")
            if not choice:
                continue
                
            idx = int(choice) - 1
            if 0 <= idx < len(agents):
                selected = agents[idx]
                agent_name = _get_display_name(selected)
                
                # Save as default
                set_default(agent_name)
                print(f"Selected: {agent_name}", file=sys.stderr)
                return selected
            else:
                print(f"Please enter a number between 1 and {len(agents)}", file=sys.stderr)
                
        except ValueError:
            print("Please enter a valid number", file=sys.stderr)
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled", file=sys.stderr)
            sys.exit(1)