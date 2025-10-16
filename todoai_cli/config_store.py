import json
import os
import platform
from pathlib import Path
from typing import Optional


def get_default_config_dir() -> Path:
    """Get the appropriate config directory for the current platform"""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
        return Path(base) / "todoai-cli"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "todoai-cli"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        return Path(xdg_config) / "todoai-cli"


def resolve_config_path(path_arg: Optional[str]) -> Path:
    """Resolve user-provided config path or use default"""
    if path_arg:
        p = Path(os.path.expanduser(path_arg))
        if p.is_dir() or str(p).endswith(os.sep):
            return p / "config.json"
        # Treat as a file path
        return p
    return get_default_config_dir() / "config.json"


class TODOCLIConfig:
    def __init__(self, path_arg: Optional[str] = None):
        self.config_path: Path = resolve_config_path(path_arg)
        self.data = self.load_config()
    
    @property
    def config_dir(self) -> Path:
        return self.config_path.parent
    
    def _default_config(self) -> dict:
        return {
            "default_project_id": None,
            "default_agent_name": None,
            "default_api_url": None,
            "recent_projects": [],
            "recent_agents": []
        }
    
    def load_config(self) -> dict:
        """Load configuration from file"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return self._default_config()
        return self._default_config()
    
    def save_config(self):
        """Persist configuration to file"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
    
    def set_default_project(self, project_id: str, project_name: str = None):
        self.data["default_project_id"] = project_id
        recent = self.data.get("recent_projects", [])
        entry = {"id": project_id, "name": project_name or project_id}
        recent = [p for p in recent if p["id"] != project_id]
        recent.insert(0, entry)
        self.data["recent_projects"] = recent[:10]
        self.save_config()
    
    def set_default_agent(self, agent_name: str):
        self.data["default_agent_name"] = agent_name
        recent = self.data.get("recent_agents", [])
        if agent_name not in recent:
            recent.insert(0, agent_name)
            self.data["recent_agents"] = recent[:10]
        self.save_config()
    
    def set_default_api_url(self, api_url: str):
        self.data["default_api_url"] = api_url
        self.save_config()