#!/usr/bin/env python3
"""
Model Context Protocol (MCP) server for querying backtest results and strategy analytics.
Powered by FastMCP.
"""
import json
import os
import sys

# Bootstrap Django environment
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project_argo.settings")
import django
django.setup()

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from fastmcp import FastMCP

from argo.mcp.reporter import StrategyBacktestAnalyzer

mcp = FastMCP("argo-backtest")


def _ensure_argo_db() -> None:
    from django.conf import settings
    from django.db import connections
    if settings.DATABASES.get("default", {}).get("NAME") != "argo2":
        settings.DATABASES["default"]["NAME"] = "argo2"
        connections["default"].close()


@mcp.tool()
def get_strategy_backtest_report(strategy_path_or_name: str, limit: int = 10) -> str:
    """Queries the database and returns a comprehensive backtest performance and optimization report for a strategy given its source file path, class path, or name. Compares baseline vs optimized runs and highlights actionable parameter improvements.

    Args:
        strategy_path_or_name: File path (e.g. /home/elio/projects/guillermo/argo/strategies/donchian_breakout.py), class path, or strategy name.
        limit: Maximum number of recent runs to analyze (default: 10).
    """
    _ensure_argo_db()
    return StrategyBacktestAnalyzer.get_strategy_report(strategy_path_or_name, limit)


@mcp.tool()
def list_strategies_with_backtests(search: str = "") -> str:
    """Lists all registered trading strategies in the database along with total backtest runs and best Sharpe ratio achieved.

    Args:
        search: Optional search term to filter strategies by name or class path.
    """
    _ensure_argo_db()
    strats = StrategyBacktestAnalyzer.list_strategies(search)
    return json.dumps(strats, indent=2)


@mcp.tool()
def get_backtest_run_details(run_id: int, include_log: bool = False) -> str:
    """Retrieves complete performance metrics, parameters configuration, and execution info for a specific backtest run ID.

    Args:
        run_id: ID of the BacktestRun.
        include_log: Whether to include simulation logs (default: false).
    """
    _ensure_argo_db()
    detail = StrategyBacktestAnalyzer.get_run_detail(run_id, include_log)
    return json.dumps(detail, indent=2)


@mcp.tool()
def compare_backtest_runs(run_ids: list[int]) -> str:
    """Performs a side-by-side comparative analysis of two or more backtest run IDs, calculating metric deltas.

    Args:
        run_ids: List of 2 or more BacktestRun IDs to compare.
    """
    _ensure_argo_db()
    return StrategyBacktestAnalyzer.compare_runs([int(i) for i in run_ids])


if __name__ == "__main__":
    mcp.run()
