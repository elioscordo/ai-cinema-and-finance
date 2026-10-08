"""
Database synchronization hook for MCP server and live node environments.
Ensures Django database connection targets the active Argo quantitative database.
"""
import importlib
import logging
import sys
from django.conf import settings
from django.db import connections

logger = logging.getLogger("mcp-server")


def synchronize_argo_database() -> None:
    """Verifies and points default database connection to the active argo database."""
    candidates = ["argo2", "argo"]
    for db_name in candidates:
        try:
            settings.DATABASES["default"]["NAME"] = db_name
            connections["default"].close()
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1 FROM argo_backtest LIMIT 1;")
            logger.info("Successfully targeted database: %s", db_name)
            break
        except Exception as err:
            logger.debug("Failed querying argo_backtest on %s: %s", db_name, err)


synchronize_argo_database()

if "argo.mcp.reporter" in sys.modules:
    importlib.reload(sys.modules["argo.mcp.reporter"])
