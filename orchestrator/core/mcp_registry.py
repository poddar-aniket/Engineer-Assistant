import importlib.util
import logging
import sys
from pathlib import Path
import yaml
from mcp_server.base import BaseMCPServer

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "mcp_servers.yaml"


class MCPRegistry:

    def __init__(self, config_path: Path = _CONFIG_PATH):
        self._config_path = config_path
        self._servers: dict[str, BaseMCPServer] = {}

    async def initialize_all(self) -> None:
        config = self._load_config()
        for plugin_cfg in config.get("plugins", []):
            name = plugin_cfg["name"]
            if not plugin_cfg.get("enabled", False):
                logger.debug("Plugin '%s' disabled — skipping.", name)
                continue
            server = self._import_plugin(name, plugin_cfg["path"])
            if server is None:
                continue
            await server.initialize()
            self._servers[name] = server
            logger.info("Plugin '%s' ready.", name)

    async def shutdown_all(self) -> None:
        for name, server in self._servers.items():
            try:
                await server.shutdown()
            except Exception as e:
                logger.warning("Plugin '%s' shutdown error: %s", name, e)
        self._servers.clear()

    def get(self, name: str) -> BaseMCPServer:
        if name not in self._servers:
            raise KeyError(f"Plugin '{name}' not in registry. Available: {list(self._servers)}")
        return self._servers[name]

    def list_names(self) -> list[str]:
        return list(self._servers.keys())

    async def health_check(self) -> dict[str, bool]:
        return {name: await s.health_check() for name, s in self._servers.items()}

    def _load_config(self) -> dict:
        with open(self._config_path) as f:
            return yaml.safe_load(f) or {}

    def _import_plugin(self, name: str, relative_path: str) -> BaseMCPServer | None:
        server_path = _PROJECT_ROOT / relative_path / "server.py"
        if not server_path.exists():
            logger.error("Plugin '%s': server.py not found at %s", name, server_path)
            return None
        module_name = f"_mcp_plugin_{name}"
        spec = importlib.util.spec_from_file_location(module_name, server_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, BaseMCPServer) and obj is not BaseMCPServer:
                return obj(name=name)
        logger.error("Plugin '%s': no BaseMCPServer subclass found.", name)
        return None