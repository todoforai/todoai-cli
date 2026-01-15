import json
import os
import platform
from pathlib import Path
from typing import Optional
import stat
import base64


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

def _simple_obfuscate(data: str) -> str:
    """Simple obfuscation for API keys (not encryption, just encoding)"""
    if not data:
        return data
    return base64.b64encode(data.encode('utf-8')).decode('utf-8')


def _simple_deobfuscate(data: str) -> str:
    """Reverse simple obfuscation"""
    if not data:
        return data
    try:
        return base64.b64decode(data.encode('utf-8')).decode('utf-8')
    except Exception:
        return data  # Return as-is if decoding fails (backward compatibility)


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
            "default_api_key": None,
            "recent_projects": [],
            "recent_agents": []
        }
    
    def load_config(self) -> dict:
        """Load configuration from file"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Deobfuscate API key if present
                if data.get("default_api_key"):
                    data["default_api_key"] = _simple_deobfuscate(data["default_api_key"])
                    
                return data
            except (json.JSONDecodeError, OSError):
                return self._default_config()
        return self._default_config()
    
    def save_config(self):
        """Persist configuration to file with secure permissions"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Create a copy for saving with obfuscated API key
            save_data = self.data.copy()
            if save_data.get("default_api_key"):
                save_data["default_api_key"] = _simple_obfuscate(save_data["default_api_key"])

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)

            # Set secure permissions (owner read/write only) on Unix systems
            # This protects the API key from being read by other users
            if platform.system() != "Windows":
                self.config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

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
    
    def set_default_agent(self, agent_name: str, agent_settings: dict = None):
        from datetime import datetime, timezone
        self.data["default_agent_name"] = agent_name
        self.data["default_agent_settings"] = agent_settings
        self.data["default_agent_settings_updated_at"] = datetime.now(timezone.utc).isoformat()
        recent = self.data.get("recent_agents", [])
        if agent_name not in recent:
            recent.insert(0, agent_name)
            self.data["recent_agents"] = recent[:10]
        self.save_config()
    
    def set_default_api_url(self, api_url: str):
        self.data["default_api_url"] = api_url
        self.save_config()
    
    def set_default_api_key(self, api_key: str):
        self.data["default_api_key"] = api_key
        self.save_config()