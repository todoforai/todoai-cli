import sys
from typing import Optional

from todoforai_edge.edge import TODOforAIEdge
from todoforai_edge.config import Config


async def init_edge(cli_api_url: Optional[str], saved_default_api_url: Optional[str]) -> TODOforAIEdge:
    """
    Build and validate the Edge client using URL priority:
      1) cli_api_url (argument)
      2) env via Config()
      3) saved_default_api_url (from CLI config)
      4) Config default
    """
    cfg = Config()
    if cli_api_url:
        cfg.api_url = cli_api_url
    elif saved_default_api_url:
        cfg.api_url = saved_default_api_url
    
    if not cfg.api_key:
        print("❌ Please set TODOFORAI_API_KEY (or TODO4AI_API_KEY) environment variable", file=sys.stderr)
        sys.exit(1)
    
    edge = TODOforAIEdge(cfg)
    result = await edge.validate_api_key()
    if not result.get("valid"):
        err = result.get("error", "Unknown error")
        print(f"❌ API key validation failed: {err}", file=sys.stderr)
        sys.exit(1)
    return edge