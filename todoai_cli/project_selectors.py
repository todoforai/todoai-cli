import sys
import os
from pathlib import Path
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


def _get_workspace_paths(agent: AgentSettings) -> List[str]:
    """Extract all workspace paths from an agent's configuration"""
    paths = []
    
    # Navigate through the nested structure: edgesMcpConfigs -> edge_id -> todoai -> workspacePaths
    edges_configs = agent.get('edgesMcpConfigs', {})
    for edge_id, edge_config in edges_configs.items():
        todoai_config = edge_config.get('todoai', {})
        workspace_paths = todoai_config.get('workspacePaths', [])
        if isinstance(workspace_paths, list):
            paths.extend(workspace_paths)
    
    return paths


def _find_workspace_agent_strict(agents: List[AgentSettings], current_path: Path) -> Optional[AgentSettings]:
    """Return agent if it has exactly one workspacePaths entry that strictly equals current_path."""
    for agent in agents:
        paths = _get_workspace_paths(agent)
        
        if len(paths) != 1:
            continue
        try:
            wp = Path(paths[0]).resolve()
        except (OSError, ValueError):
            continue
        if wp == current_path:
            return agent
    return None


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
    """Interactive agent selection with workspace-aware (strict) and default support"""
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

    # Resolve current path once, reuse
    current_path = Path(os.getcwd()).resolve()

    # First: strict workspace match (only agents with exactly one workspace path, equality required)
    workspace_agent = _find_workspace_agent_strict(agents, current_path)
    if workspace_agent:
        agent_name = _get_display_name(workspace_agent)
        print(f"Auto-selected workspace agent '{agent_name}' based on current directory: \033[36m{current_path}\033[0m", file=sys.stderr)
        return workspace_agent
    
    # Second: default agent (partial match)
    if default_agent_name:
        agent = findBy(agents, lambda a: default_agent_name.lower() in _get_display_name(a).lower())
        if agent:
            agent_name = _get_display_name(agent)
            print(f"Using default agent: {agent_name}", file=sys.stderr)
            return agent
    
    print("\nPlease choose an agent:", file=sys.stderr)
    print("", file=sys.stderr)
    
    # Display agents with numbers, highlighting workspace matches
    for i, agent in enumerate(agents, 1):
        agent_name = _get_display_name(agent)
        
        is_workspace_match = False
        workspace_paths = _get_workspace_paths(agent)
        for workspace_path in workspace_paths:
            try:
                wp = Path(workspace_path).resolve()
                if current_path == wp or (hasattr(current_path, "is_relative_to") and current_path.is_relative_to(wp)):
                    is_workspace_match = True
                    break
            except (OSError, ValueError):
                continue
        
        if is_workspace_match:
            print(f" [{i}] {agent_name} 📁", file=sys.stderr)
        else:
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