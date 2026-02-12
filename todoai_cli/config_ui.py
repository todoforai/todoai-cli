"""Interactive configuration UI for default settings."""

import sys
from typing import Dict

from .project_selectors import _get_display_name, _get_item_id, _get_terminal_input


async def interactive_set_defaults(config):
    """Interactive defaults configuration."""
    from .edge_client import init_edge

    edge = None
    try:
        edge = await init_edge(
            None,
            config.data.get("default_api_url"),
            config.data.get("default_api_key"),
        )
    except SystemExit:
        pass

    config_options = [
        {"key": "default_project_id", "name": "Default Project", "type": "project"},
        {"key": "default_agent_name", "name": "Default Agent", "type": "agent"},
        {"key": "default_api_url", "name": "Default API URL", "type": "text"},
        {"key": "default_api_key", "name": "Default API Key", "type": "password"},
    ]

    while True:
        print("\nConfigure Default Settings", file=sys.stderr)
        print("=" * 40, file=sys.stderr)
        print(
            "Which default config values would you like to change?", file=sys.stderr
        )
        print("", file=sys.stderr)

        for i, option in enumerate(config_options, 1):
            current = config.data.get(option["key"])
            if option["type"] == "password" and current:
                if len(current) > 8:
                    current = f"{current[:4]}***{current[-4:]}"
                else:
                    current = "***set***"
            elif option["type"] == "project" and current:
                project_name = None
                for recent in config.data.get("recent_projects", []):
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
                await _configure_option(config, edge, option)
            else:
                print(
                    f"Please enter a number between 0 and {len(config_options)}",
                    file=sys.stderr,
                )

        except ValueError:
            print("Please enter a valid number", file=sys.stderr)
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled", file=sys.stderr)
            return


async def _configure_option(config, edge, option: Dict[str, str]):
    """Configure a specific option."""
    print(f"\nConfiguring: {option['name']}", file=sys.stderr)

    if option["type"] == "project":
        await _configure_project(config, edge)
    elif option["type"] == "agent":
        await _configure_agent(config, edge)
    elif option["type"] == "text":
        _configure_text_option(config, option)
    elif option["type"] == "password":
        _configure_password_option(config, option)


async def _configure_project(config, edge):
    """Configure default project."""
    try:
        if not edge:
            print("Error: Need valid API key to list projects", file=sys.stderr)
            return

        projects = await edge.list_projects()

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
                    config.set_default_project(project_id)
                    print(f"Default project set to: {project_id}", file=sys.stderr)
                break
            elif choice:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(projects):
                        project = projects[idx]
                        project_id = _get_item_id(project)
                        project_name = _get_display_name(project)
                        config.set_default_project(project_id, project_name)
                        print(
                            f"Default project set to: {project_name}",
                            file=sys.stderr,
                        )
                        break
                    else:
                        print(
                            f"Please enter a number between 0 and {len(projects)}",
                            file=sys.stderr,
                        )
                except ValueError:
                    print("Please enter a valid number", file=sys.stderr)

    except Exception as e:
        print(f"Error: Failed to configure project: {e}", file=sys.stderr)


async def _configure_agent(config, edge):
    """Configure default agent."""
    try:
        if not edge:
            print("Error: Need valid API key to list agents", file=sys.stderr)
            return

        agents = await edge.list_agent_settings()

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
                    config.set_default_agent(agent_name)
                    print(f"Default agent set to: {agent_name}", file=sys.stderr)
                break
            elif choice:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(agents):
                        agent = agents[idx]
                        agent_name = _get_display_name(agent)
                        config.set_default_agent(agent_name, agent)
                        print(
                            f"Default agent set to: {agent_name}", file=sys.stderr
                        )
                        break
                    else:
                        print(
                            f"Please enter a number between 0 and {len(agents)}",
                            file=sys.stderr,
                        )
                except ValueError:
                    print("Please enter a valid number", file=sys.stderr)

    except Exception as e:
        print(f"Error: Failed to configure agent: {e}", file=sys.stderr)


def _configure_text_option(config, option: Dict[str, str]):
    """Configure a text option."""
    current = config.data.get(option["key"])
    if current:
        print(f"Current value: {current}", file=sys.stderr)

    value = _get_terminal_input(f"Enter {option['name'].lower()}: ").strip()
    if value:
        getattr(config, f"set_{option['key']}")(value)
        print(f"{option['name']} set to: {value}", file=sys.stderr)


def _configure_password_option(config, option: Dict[str, str]):
    """Configure a password option."""
    import getpass

    current = config.data.get(option["key"])
    if current:
        print("Current value: ***set***", file=sys.stderr)

    try:
        value = getpass.getpass(f"Enter {option['name'].lower()}: ")
        if value:
            getattr(config, f"set_{option['key']}")(value)
            print(f"{option['name']} set", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
