"""Argparse builder and config command handling."""

import argparse
import asyncio
import json


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
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
        """,
    )

    parser.add_argument(
        "prompt",
        nargs="*",
        help="Prompt text (if omitted, reads from stdin or interactive input)",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Workspace path (auto-selects agent by matching workspacePaths, defaults to cwd)",
    )
    parser.add_argument("--project", help="Project ID (will prompt if not provided)")
    parser.add_argument(
        "--agent", "-a", help="Agent name (partial match, will prompt if not provided)"
    )
    parser.add_argument(
        "--todo-id", help="Custom TODO ID (auto-generated if not provided)"
    )
    parser.add_argument(
        "--resume",
        "-r",
        metavar="TODO_ID",
        nargs="?",
        const="__pick__",
        help="Resume existing todo (without ID: show picker for current agent)",
    )
    parser.add_argument(
        "--continue",
        "-c",
        action="store_true",
        dest="continue_last",
        help="Continue the most recent todo for the current agent",
    )
    parser.add_argument(
        "--api-url", help="API URL (overrides environment and saved default)"
    )
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    parser.add_argument(
        "--no-watch",
        action="store_true",
        help="Create todo and exit without watching for completion",
    )
    parser.add_argument(
        "-p",
        "--print",
        action="store_true",
        dest="print_mode",
        help="Non-interactive: run single message and exit",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Watch timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--safe", action="store_true", help="Validate API key and fetch lists upfront"
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug output"
    )
    parser.add_argument(
        "--edge",
        nargs="?",
        const=".",
        default=None,
        metavar="WORKSPACE",
        help="Start embedded edge for local block execution (optionally specify workspace path, default: cwd)",
    )
    parser.add_argument("--config-path", metavar="PATH", help="Custom config file path")

    # Config management
    config_group = parser.add_argument_group("configuration")
    config_group.add_argument(
        "--set-defaults",
        action="store_true",
        help="Interactive configuration of default settings",
    )
    config_group.add_argument(
        "--set-default-project", metavar="PROJECT_ID", help="Set default project ID"
    )
    config_group.add_argument(
        "--set-default-agent", metavar="AGENT_NAME", help="Set default agent name"
    )
    config_group.add_argument(
        "--set-default-api-url", metavar="API_URL", help="Set default API URL"
    )
    config_group.add_argument(
        "--set-default-api-key", metavar="API_KEY", help="Set default API key"
    )
    config_group.add_argument(
        "--show-config",
        action="store_true",
        help="Show current configuration (includes path)",
    )
    config_group.add_argument(
        "--reset-config",
        action="store_true",
        help="Reset configuration file at current path",
    )

    return parser


def handle_config_commands(cfg, args) -> bool:
    """Handle config-related commands. Returns True if a command was handled."""
    if args.show_config:
        print(f"Config file: {cfg.config_path}")
        print(json.dumps(cfg.data, indent=2))
        return True

    if args.reset_config:
        if cfg.config_path.exists():
            cfg.config_path.unlink()
            print(f"Configuration reset: {cfg.config_path}")
        else:
            print("No configuration file to reset")
        return True

    if args.set_defaults:
        from .config_ui import interactive_set_defaults

        asyncio.run(interactive_set_defaults(cfg))
        return True

    if (
        args.set_default_project
        or args.set_default_agent
        or args.set_default_api_url
        or args.set_default_api_key
    ):
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
        return True

    return False
