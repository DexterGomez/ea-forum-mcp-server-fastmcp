import logging
from src.config.settings import settings
from src.EAForumMCP import EAForumMCP

if __name__ == "__main__":

    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
    logger = logging.getLogger(__name__)

    logger.info(f"Starting {settings.MCP_SERVER_NAME} v{settings.MCP_SERVER_VERSION}")
    mcp = EAForumMCP()
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8010,
        path="/mcp"
    )