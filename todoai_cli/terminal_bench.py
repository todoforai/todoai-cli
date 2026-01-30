#!/usr/bin/env python3
"""
Terminal-Bench Mode Support for TODOforAI CLI

This module provides direct LLM execution with tmux bridging for
Terminal-Bench benchmarking integration.

Usage:
    TBENCH_SESSION_ID=my-session echo "task" | todoai-cli --terminal-bench
"""

import json
import os
import re
import subprocess
import sys
import time
from typing import Optional, List, Dict, Any


SYSTEM_PROMPT = """You are an expert terminal user solving a task. You have access to a bash terminal.

For each step:
1. Think about what you need to do
2. Execute a single command
3. Observe the output
4. Decide next steps

Output your commands in this format:
```bash
your_command_here
```

When you have completed the task, output:
```
TASK_COMPLETE: <brief summary of what you did>
```

If you cannot complete the task, output:
```
TASK_FAILED: <reason>
```

Important:
- Execute one command at a time
- Wait for output before proceeding
- Use absolute paths when possible
- Handle errors gracefully
"""


class TmuxBridge:
    """Bridge for sending commands to a tmux session."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    def send_keys(self, command: str) -> None:
        """Send a command to the tmux session."""
        subprocess.run(
            ["tmux", "send-keys", "-t", self.session_id, command, "Enter"],
            check=True,
            capture_output=True,
        )

    def is_busy(self, timeout: float = 0.5) -> bool:
        """Check if the tmux pane is busy (command still running)."""
        time.sleep(timeout)

        result = subprocess.run(
            ["tmux", "list-panes", "-t", self.session_id, "-F", "#{pane_current_command}"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return False

        current_cmd = result.stdout.strip()
        return current_cmd not in ("bash", "zsh", "sh", "-bash", "-zsh", "-sh", "")

    def get_output(self, lines: int = 100) -> str:
        """Get recent output from the tmux pane."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self.session_id, "-p", "-S", f"-{lines}"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return f"Error capturing output: {result.stderr}"

        return result.stdout

    def execute_command(self, command: str, timeout: int = 60) -> str:
        """Execute a command and return output."""
        before = self.get_output()
        self.send_keys(command)

        waited = 0
        while self.is_busy() and waited < timeout:
            time.sleep(0.5)
            waited += 0.5

        time.sleep(0.3)
        after = self.get_output()

        if command in after:
            idx = after.rfind(command)
            return after[idx + len(command):].strip()

        return after[len(before):].strip() if len(after) > len(before) else after


class TerminalBenchRunner:
    """Runner for Terminal-Bench mode - direct LLM execution with tmux bridging."""

    def __init__(self, model: str = "claude-sonnet-4-5", provider: str = "anthropic", timeout: int = 600):
        self.model = model
        self.provider = provider
        self.timeout = timeout
        self.max_iterations = 50

        self.input_tokens = 0
        self.output_tokens = 0

        if provider == "anthropic":
            try:
                import anthropic
                self.client = anthropic.Anthropic()
            except ImportError:
                print("❌ anthropic package required: pip install anthropic", file=sys.stderr)
                sys.exit(1)
        elif provider == "openai":
            try:
                import openai
                self.client = openai.OpenAI()
            except ImportError:
                print("❌ openai package required: pip install openai", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"❌ Unknown provider: {provider}", file=sys.stderr)
            sys.exit(1)

    def _get_model_id(self) -> str:
        """Map model name to full model ID."""
        if self.provider == "anthropic":
            model_map = {
                # Claude 4.5 models
                "claude-sonnet-4-5": "claude-sonnet-4-5-20250514",
                "claude-opus-4-5": "claude-opus-4-5-20251101",
                "sonnet": "claude-sonnet-4-5-20250514",
                "opus": "claude-opus-4-5-20251101",
                # Claude 3.5 models (older)
                "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku": "claude-3-5-haiku-20241022",
                "sonnet-3.5": "claude-3-5-sonnet-20241022",
                "haiku": "claude-3-5-haiku-20241022",
            }
            mapped = model_map.get(self.model, self.model)
            # If model not found and doesn't look like a full ID, use opus as default
            if mapped == self.model and not mapped.startswith("claude-"):
                return "claude-opus-4-5-20251101"
            return mapped
        else:
            model_map = {
                "gpt-4o": "gpt-4o",
                "gpt-4": "gpt-4-turbo",
            }
            return model_map.get(self.model, self.model)

    def _extract_command(self, response: str) -> Optional[str]:
        """Extract bash command from LLM response."""
        pattern = r"```(?:bash|sh)?\s*\n(.*?)\n```"
        matches = re.findall(pattern, response, re.DOTALL)

        if matches:
            command = matches[0].strip()
            if '\n' in command:
                command = command.split('\n')[0].strip()
            return command

        return None

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Call the LLM and return response."""
        if self.provider == "anthropic":
            response = self.client.messages.create(
                model=self._get_model_id(),
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
            )

            self.input_tokens += response.usage.input_tokens
            self.output_tokens += response.usage.output_tokens

            return response.content[0].text
        else:
            full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

            response = self.client.chat.completions.create(
                model=self._get_model_id(),
                max_tokens=4096,
                messages=full_messages,
            )

            if response.usage:
                self.input_tokens += response.usage.prompt_tokens
                self.output_tokens += response.usage.completion_tokens

            return response.choices[0].message.content

    def run(self, task_description: str, tmux: TmuxBridge) -> Dict[str, Any]:
        """Run a Terminal-Bench task."""
        messages = [
            {"role": "user", "content": f"Task: {task_description}\n\nThe terminal is ready. Begin solving the task."}
        ]

        failure_mode = None
        commands_executed = []

        print(f"🚀 Starting Terminal-Bench task...", file=sys.stderr)
        print(f"   Model: {self._get_model_id()}", file=sys.stderr)
        print(f"   Session: {tmux.session_id}", file=sys.stderr)
        print("─" * 40, file=sys.stderr)

        for iteration in range(self.max_iterations):
            response = self._call_llm(messages)
            messages.append({"role": "assistant", "content": response})

            print(response, file=sys.stderr)

            if "TASK_COMPLETE:" in response:
                print("\n✅ Task completed", file=sys.stderr)
                break
            elif "TASK_FAILED:" in response:
                failure_mode = "agent_declared_failure"
                print("\n❌ Task failed (agent declared)", file=sys.stderr)
                break

            command = self._extract_command(response)

            if command:
                print(f"\n$ {command}", file=sys.stderr)
                commands_executed.append(command)

                output = tmux.execute_command(command, timeout=60)

                if len(output) > 8000:
                    output = output[:8000] + f"\n... (truncated, {len(output)} chars total)"

                print(output, file=sys.stderr)

                messages.append({
                    "role": "user",
                    "content": f"Command output:\n```\n{output}\n```"
                })
            else:
                messages.append({
                    "role": "user",
                    "content": "Please provide a bash command to execute, or indicate if the task is complete."
                })
        else:
            failure_mode = "max_iterations"
            print(f"\n⚠️ Max iterations ({self.max_iterations}) reached", file=sys.stderr)

        print("─" * 40, file=sys.stderr)
        print(f"📊 Tokens: {self.input_tokens} in / {self.output_tokens} out", file=sys.stderr)
        print(f"📋 Commands executed: {len(commands_executed)}", file=sys.stderr)

        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "commands_executed": commands_executed,
            "iterations": iteration + 1,
            "failure_mode": failure_mode,
        }


def run_terminal_bench_mode(args) -> int:
    """Run in Terminal-Bench mode."""
    session_id = os.environ.get("TBENCH_SESSION_ID")
    if not session_id:
        print("❌ TBENCH_SESSION_ID environment variable not set", file=sys.stderr)
        print("   This mode is for use with Terminal-Bench harness", file=sys.stderr)
        return 1

    if sys.stdin.isatty():
        print("❌ Task must be piped via stdin", file=sys.stderr)
        return 1

    task_description = sys.stdin.read().strip()
    if not task_description:
        print("❌ Empty task description", file=sys.stderr)
        return 1

    model = os.environ.get("TODOFORAI_MODEL", getattr(args, 'model', None) or "claude-sonnet-4-5")

    if "gpt" in model.lower():
        provider = "openai"
    else:
        provider = "anthropic"

    tmux = TmuxBridge(session_id)
    runner = TerminalBenchRunner(
        model=model,
        provider=provider,
        timeout=getattr(args, 'timeout', 600),
    )

    result = runner.run(task_description, tmux)

    print("__TOKENS__", file=sys.stdout)
    print(json.dumps({
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
    }), file=sys.stdout)

    return 0 if result["failure_mode"] is None else 1
