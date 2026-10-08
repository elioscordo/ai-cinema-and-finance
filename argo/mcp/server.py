#!/usr/bin/env python3
"""
Model Context Protocol (MCP) server for querying backtest results and strategy analytics.
Communicates via JSON-RPC 2.0 over Stdio.
"""
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

# Configure stderr logging to ensure stdout is reserved exclusively for JSON-RPC
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [mcp-server]: %(message)s",
)
logger = logging.getLogger("mcp-server")

# Bootstrap Django environment
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["DJANGO_SETTINGS_MODULE"] = "project_argo.settings"
import django
django.setup()

from argo.mcp.reporter import StrategyBacktestAnalyzer


class MCPToolRegistry:
    """Defines and provides tool specifications conforming to MCP specification."""

    @staticmethod
    def get_tools_spec() -> List[Dict[str, Any]]:
        return [
            {
                "name": "get_strategy_backtest_report",
                "description": (
                    "Queries the database and returns a comprehensive backtest performance and optimization report "
                    "for a strategy given its source file path (e.g. /home/elio/projects/guillermo/argo/strategies/donchian_breakout.py), "
                    "class path, or name. Compares baseline vs optimized runs and highlights actionable parameter improvements."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "strategy_path_or_name": {
                            "type": "string",
                            "description": "File path (e.g. /home/elio/projects/guillermo/argo/strategies/donchian_breakout.py), class path, or strategy name."
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of recent runs to analyze (default: 10)."
                        }
                    },
                    "required": ["strategy_path_or_name"]
                }
            },
            {
                "name": "list_strategies_with_backtests",
                "description": (
                    "Lists all registered trading strategies in the database along with total backtest runs "
                    "and best Sharpe ratio achieved."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": "Optional search term to filter strategies by name or class path."
                        }
                    }
                }
            },
            {
                "name": "get_backtest_run_details",
                "description": (
                    "Retrieves complete performance metrics, parameters configuration, and execution info for a specific backtest run ID."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {
                            "type": "integer",
                            "description": "ID of the BacktestRun."
                        },
                        "include_log": {
                            "type": "boolean",
                            "description": "Whether to include simulation logs (default: false)."
                        }
                    },
                    "required": ["run_id"]
                }
            },
            {
                "name": "compare_backtest_runs",
                "description": (
                    "Performs a side-by-side comparative analysis of two or more backtest run IDs, calculating metric deltas."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of 2 or more BacktestRun IDs to compare."
                        }
                    },
                    "required": ["run_ids"]
                }
            }
        ]


class MCPDispatcher:
    """Dispatches MCP JSON-RPC requests to tool implementations."""

    @staticmethod
    def _success_response(req_id: Any, result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error_response(req_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message}
        }

    @staticmethod
    def _ensure_argo_db() -> None:
        from django.conf import settings
        from django.db import connections
        if settings.DATABASES.get("default", {}).get("NAME") != "argo2":
            settings.DATABASES["default"]["NAME"] = "argo2"
            connections["default"].close()

    @classmethod
    def execute_tool(cls, name: str, args: Dict[str, Any]) -> str:
        cls._ensure_argo_db()
        if name == "get_strategy_backtest_report":
            path_or_name = args.get("strategy_path_or_name", "")
            limit = int(args.get("limit", 10))
            return StrategyBacktestAnalyzer.get_strategy_report(path_or_name, limit)

        if name == "list_strategies_with_backtests":
            search = args.get("search", "")
            strats = StrategyBacktestAnalyzer.list_strategies(search)
            return json.dumps(strats, indent=2)

        if name == "get_backtest_run_details":
            run_id = int(args.get("run_id", 0))
            include_log = bool(args.get("include_log", False))
            detail = StrategyBacktestAnalyzer.get_run_detail(run_id, include_log)
            return json.dumps(detail, indent=2)

        if name == "compare_backtest_runs":
            raw_ids = args.get("run_ids", [])
            run_ids = [int(i) for i in raw_ids]
            return StrategyBacktestAnalyzer.compare_runs(run_ids)

        raise ValueError(f"Unknown tool: '{name}'")

    @classmethod
    def handle_request(cls, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = msg.get("method")
        req_id = msg.get("id")

        if method == "initialize":
            return cls._success_response(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "argo-backtest-mcp", "version": "1.0.0"}
                }
            )

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return cls._success_response(req_id, {})

        if method == "tools/list":
            return cls._success_response(
                req_id,
                {"tools": MCPToolRegistry.get_tools_spec()}
            )

        if method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})
            try:
                text_result = cls.execute_tool(name, args)
                return cls._success_response(
                    req_id,
                    {"content": [{"type": "text", "text": text_result}], "isError": False}
                )
            except Exception as e:
                logger.error(f"Tool execution failed for '{name}': {e}", exc_info=True)
                return cls._success_response(
                    req_id,
                    {"content": [{"type": "text", "text": f"Error executing tool: {str(e)}"}], "isError": True}
                )

        if req_id is not None:
            return cls._error_response(req_id, -32601, f"Method '{method}' not found")
        return None


class MCPServer:
    """Stdio transport loop reading JSON-RPC messages and writing responses."""

    @staticmethod
    def _read_message() -> Optional[Dict[str, Any]]:
        while True:
            line = sys.stdin.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError as err:
                    logger.warning(f"Failed to parse JSON line: {err}")
                    continue
            if line.lower().startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                    # Consume following blank line
                    sys.stdin.readline()
                    body = sys.stdin.read(length)
                    return json.loads(body)
                except Exception as err:
                    logger.warning(f"Failed to parse content-length frame: {err}")
                    continue

    @classmethod
    def run(cls) -> None:
        logger.info("Starting Argo Backtest MCP server...")
        while True:
            try:
                msg = cls._read_message()
                if msg is None:
                    break
                resp = MCPDispatcher.handle_request(msg)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp) + "\n")
                    sys.stdout.flush()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Unexpected error in server loop: {e}", exc_info=True)
        logger.info("Argo Backtest MCP server stopped.")


if __name__ == "__main__":
    MCPServer.run()
