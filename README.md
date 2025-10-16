# TODOforAI CLI

A command-line interface for creating TODOs from piped input using the TODOforAI Edge package.

## Installation

Install globally with pip:

```bash
pip install todoai-cli
```

Or install from source:

```bash
git clone <repository>
cd todoai-cli
pip install -e .
```

## Setup

Set your API key:
```bash
export TODOFORAI_API_KEY=your_api_key_here
```

## Usage

### Basic Usage

```bash
echo "Debug authentication issue" | todoai_cli
```

### With Options

```bash
# Specify agent and skip confirmation
echo "Send email to client" | todoai_cli --agent "gmail" -y

# Custom TODO ID
echo "Weekly report" | todoai_cli --todo-id weekly-report-2024-01

# JSON output for scripting
echo "API task" | todoai_cli --json
```

### Configuration

Set defaults to avoid repeated prompting:

```bash
# Set default project and agent
todoai_cli --set-default-project abc123
todoai_cli --set-default-agent "todoforai gmail"

# Now you can just pipe content
echo "Quick task" | todoai_cli -y
```

### Examples

```bash
# From file
cat task_description.txt | todoai_cli

# From clipboard (macOS)
pbpaste | todoai_cli --agent "gmail"

# From git commit
git log -1 --pretty=%B | todoai_cli --agent "code review"

# Multi-line with confirmation
cat << EOF | todoai_cli
Research the following:
1. AI safety regulations  
2. GDPR compliance
3. Model deployment best practices
EOF
```

## Configuration File Locations

Default locations (if --config-path is not used):

- Windows: %APPDATA%\todoai-cli\config.json
- macOS: ~/Library/Application Support/todoai-cli/config.json
- Linux: ~/.config/todoai-cli/config.json (XDG)

Override with:
```bash
todoai_cli --config-path /custom/path/config.json
```

## Command Line Options

- `--project, -p`: Project ID (prompts if not set)
- `--agent, -a`: Agent name (partial match, prompts if not set)  
- `--todo-id`: Custom TODO ID (auto-generated UUID if not provided)
- `--api-url`: API URL (overrides environment and config defaults)
- `--json`: Output result as JSON
- `--yes, -y`: Skip confirmation prompt
- `--set-default-project`: Set default project ID
- `--set-default-agent`: Set default agent name
- `--set-default-api-url`: Set default API URL
- `--show-config`: Show current configuration
- `--reset-config`: Reset all configuration
- `--config-path PATH`: Use specific config file path (overrides default)

## Features

- ✅ **Global installation**: Available as `todoai_cli` command
- ✅ **Cross-platform config**: Proper config locations for Windows/macOS/Linux
- ✅ **Clean imports**: Simple, reliable package imports
- ✅ **Flexible API URL**: Environment variables, CLI args, or saved config
- ✅ **Confirmation dialog**: Shows summary before creating TODO
- ✅ **Stateful config**: Remembers preferences
- ✅ **Auto-generated IDs**: UUIDs created automatically
- ✅ **Partial agent matching**: "gmail" matches "todoforai gmail"
- ✅ **Skip confirmation**: Use `-y` for automation
- ✅ **JSON output**: For scripting integration
- ✅ **Error handling**: Clear messages for common issues