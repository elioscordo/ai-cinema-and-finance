import os
from decimal import Decimal
from typing import Optional, List, Dict, Any
from pathlib import Path
from django.db.models import Q
from argo.models import Strategy, StrategyInstance, Backtest, BacktestRun
from argo.utils import populate_default_strategies


class StrategyResolver:
    """Resolves file paths, class paths, or names to a Strategy model instance."""

    @staticmethod
    def _extract_stem(path_or_name: str) -> str:
        clean = path_or_name.strip().rstrip("/\\")
        return Path(clean).stem.lower().replace("-", "_")

    @classmethod
    def resolve(cls, identifier: str) -> Optional[Strategy]:
        if not identifier:
            return None

        # 1. Direct PK lookup if numeric
        if identifier.isdigit():
            strat = Strategy.objects.filter(pk=int(identifier)).first()
            if strat:
                return strat

        # 2. File path or module path matching
        stem = cls._extract_stem(identifier)
        strat = Strategy.objects.filter(
            Q(class_path__icontains=stem) | Q(name__icontains=identifier.strip())
        ).first()
        if strat:
            return strat

        # 3. Source file path check
        for candidate in Strategy.objects.all():
            src_path = candidate.get_source_file_path()
            if src_path and (identifier in src_path or stem in Path(src_path).stem.lower()):
                return candidate

        # 4. Populate defaults and retry once
        populate_default_strategies()
        return Strategy.objects.filter(
            Q(class_path__icontains=stem) | Q(name__icontains=identifier.strip())
        ).first()


class MetricFormatter:
    """Formats numeric metrics into clean human-readable strings."""

    @staticmethod
    def format_pct(val: Optional[float]) -> str:
        if val is None:
            return "N/A"
        sign = "+" if val > 0 else ""
        return f"{sign}{val * 100:.2f}%"

    @staticmethod
    def format_num(val: Optional[float], decimals: int = 2) -> str:
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}"

    @staticmethod
    def format_currency(val: Optional[Decimal]) -> str:
        if val is None:
            return "N/A"
        num = float(val)
        sign = "+" if num > 0 else ""
        return f"{sign}${num:,.2f}"


class RunComparator:
    """Computes metric deltas and builds comparison tables across backtest runs."""

    @staticmethod
    def _format_diff(curr: Optional[float], base: Optional[float], is_pct: bool = False) -> str:
        if curr is None or base is None:
            return "N/A"
        diff = curr - base
        sign = "+" if diff > 0 else ""
        if is_pct:
            return f"{sign}{diff * 100:.2f}%"
        return f"{sign}{diff:.2f}"

    @classmethod
    def compute_deltas(cls, best_run: BacktestRun, base_run: BacktestRun) -> Dict[str, str]:
        best_pnl = float(best_run.total_pnl) if best_run.total_pnl is not None else None
        base_pnl = float(base_run.total_pnl) if base_run.total_pnl is not None else None
        pnl_diff = best_pnl - base_pnl if (best_pnl is not None and base_pnl is not None) else None

        return {
            "sharpe_delta": cls._format_diff(best_run.sharpe_ratio, base_run.sharpe_ratio),
            "pnl_delta": f"+${pnl_diff:,.2f}" if pnl_diff and pnl_diff > 0 else (f"-${abs(pnl_diff):,.2f}" if pnl_diff else "N/A"),
            "return_delta": cls._format_diff(best_run.return_pct, base_run.return_pct, is_pct=True),
            "drawdown_delta": cls._format_diff(best_run.max_drawdown_pct, base_run.max_drawdown_pct, is_pct=True),
            "win_rate_delta": cls._format_diff(best_run.win_rate, base_run.win_rate, is_pct=True),
        }

    @classmethod
    def build_summary_row(cls, run: BacktestRun, index: int) -> str:
        date_str = run.created_at.strftime("%Y-%m-%d %H:%M") if run.created_at else "N/A"
        pnl_str = MetricFormatter.format_currency(run.total_pnl)
        ret_str = MetricFormatter.format_pct(run.return_pct)
        sharpe_str = MetricFormatter.format_num(run.sharpe_ratio)
        dd_str = MetricFormatter.format_pct(run.max_drawdown_pct)
        wr_str = MetricFormatter.format_pct(run.win_rate)
        trades_str = str(run.total_trades) if run.total_trades is not None else "N/A"
        cfg_summary = ", ".join(f"{k}={v}" for k, v in (run.config or {}).items() if k not in ("bar_type", "instrument_id"))
        cfg_display = f"`{cfg_summary[:35]}...`" if len(cfg_summary) > 35 else (f"`{cfg_summary}`" if cfg_summary else "-")

        return f"| #{run.id} | {date_str} | {cfg_display} | {ret_str} | {pnl_str} | {sharpe_str} | {dd_str} | {wr_str} | {trades_str} |"


class BacktestReportBuilder:
    """Builds comprehensive markdown analysis reports from strategy runs and sessions."""

    @staticmethod
    def _build_header(strategy: Strategy) -> str:
        src_path = strategy.get_source_file_path() or "N/A"
        lines = [
            f"# Backtest Performance & Optimization Report",
            f"**Strategy**: {strategy.name} (`{strategy.class_path}`)",
            f"**Source File**: `{src_path}`",
            f"**Description**: {strategy.description or 'N/A'}",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _build_runs_table(runs: List[BacktestRun]) -> str:
        lines = [
            "## 1. Historical Backtest Runs",
            "| Run ID | Date | Config Parameters | Return | Total PnL | Sharpe | Max DD | Win Rate | Trades |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for idx, run in enumerate(runs, 1):
            lines.append(RunComparator.build_summary_row(run, idx))
        lines.append("")
        return "\n".join(lines)

    @classmethod
    def _build_improvement_section(cls, runs: List[BacktestRun]) -> str:
        valid_runs = [r for r in runs if r.sharpe_ratio is not None or r.total_pnl is not None]
        if len(valid_runs) < 2:
            return "## 2. Performance Improvement Analysis\n*Need at least 2 completed backtest runs to evaluate comparative improvements.*\n"

        base_run = valid_runs[-1]
        best_run = max(valid_runs, key=lambda r: (r.sharpe_ratio or -999.0, float(r.total_pnl or 0.0)))
        deltas = RunComparator.compute_deltas(best_run, base_run)

        lines = [
            "## 2. Highlighted Improvements (Best Run vs Baseline)",
            f"- **Baseline Run**: `Run #{base_run.id}` ({base_run.created_at:%Y-%m-%d})",
            f"- **Best Performing Run**: `Run #{best_run.id}` ({best_run.created_at:%Y-%m-%d})",
            "",
            "### Metric Changes:",
            f"- **Sharpe Ratio**: `{MetricFormatter.format_num(base_run.sharpe_ratio)}` ➔ `{MetricFormatter.format_num(best_run.sharpe_ratio)}` (**{deltas['sharpe_delta']}**)",
            f"- **Total Return**: `{MetricFormatter.format_pct(base_run.return_pct)}` ➔ `{MetricFormatter.format_pct(best_run.return_pct)}` (**{deltas['return_delta']}**)",
            f"- **Net PnL**: `{MetricFormatter.format_currency(base_run.total_pnl)}` ➔ `{MetricFormatter.format_currency(best_run.total_pnl)}` (**{deltas['pnl_delta']}**)",
            f"- **Max Drawdown**: `{MetricFormatter.format_pct(base_run.max_drawdown_pct)}` ➔ `{MetricFormatter.format_pct(best_run.max_drawdown_pct)}` (**{deltas['drawdown_delta']}**)",
            f"- **Win Rate**: `{MetricFormatter.format_pct(base_run.win_rate)}` ➔ `{MetricFormatter.format_pct(best_run.win_rate)}` (**{deltas['win_rate_delta']}**)",
            "",
            "### Winning Parameter Configuration:",
            "```json",
            str(best_run.config),
            "```",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _build_leaderboard_section(backtests: List[Backtest]) -> str:
        for bt in backtests:
            if bt.leaderboard:
                lines = [
                    f"## 3. Parameter Optimization Sweep ({bt.name or f'Session #{bt.id}'})",
                    f"- **Objective**: `{bt.optimization_objective}`",
                    f"- **Best Parameters**: `{bt.best_params}`",
                    "",
                    "| Rank | Parameters | Metric Score |",
                    "| :--- | :--- | :--- |",
                ]
                for rank, entry in enumerate(bt.leaderboard[:5], 1):
                    params = entry.get("params", entry)
                    score = entry.get("score", entry.get("metric", "N/A"))
                    lines.append(f"| #{rank} | `{params}` | {score} |")
                lines.append("")
                return "\n".join(lines)
        return ""

    @staticmethod
    def _build_recommendations(runs: List[BacktestRun]) -> str:
        lines = [
            "## 3. Key Observations & Actionable Recommendations",
            "- **Parameter Stability**: Compare runs across varying volatility regimes to ensure parameter sensitivity is not overfitted.",
            "- **Drawdown Protection**: Consider pairing entry breakout periods with dynamic trailing stops or volatility filters (e.g. ATR bands).",
            "- **Execution Confidence**: Review trade counts; sample sizes under 30 trades may exhibit high statistical variance.",
            "",
        ]
        return "\n".join(lines)

    @classmethod
    def assemble(cls, strategy: Strategy, runs: List[BacktestRun], backtests: List[Backtest]) -> str:
        parts = [
            cls._build_header(strategy),
        ]
        if runs:
            parts.append(cls._build_runs_table(runs))
            parts.append(cls._build_improvement_section(runs))
        else:
            parts.append("## Backtest Runs\n*No execution runs recorded in the database for this strategy yet.*\n")

        leaderboard_md = cls._build_leaderboard_section(backtests)
        if leaderboard_md:
            parts.append(leaderboard_md)

        if runs:
            parts.append(cls._build_recommendations(runs))

        return "\n".join(parts)


class StrategyBacktestAnalyzer:
    """Facade orchestrating database queries and analysis reporting for strategy backtests."""

    @classmethod
    def get_strategy_report(cls, strategy_path_or_name: str, limit: int = 10) -> str:
        strategy = StrategyResolver.resolve(strategy_path_or_name)
        if not strategy:
            return f"Error: Could not find registered strategy matching '{strategy_path_or_name}' in the database."

        instances = StrategyInstance.objects.filter(strategy_model=strategy)
        backtests = list(Backtest.objects.filter(strategy_instance__in=instances).order_by("-created_at")[:limit])
        runs = list(
            BacktestRun.objects.filter(
                Q(strategy_instance__in=instances) | Q(backtest__strategy_instance__in=instances)
            ).order_by("-created_at")[:limit]
        )

        return BacktestReportBuilder.assemble(strategy, runs, backtests)

    @classmethod
    def list_strategies(cls, search: str = "") -> List[Dict[str, Any]]:
        populate_default_strategies()
        qs = Strategy.objects.all()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(class_path__icontains=search))

        results = []
        for s in qs:
            instances = StrategyInstance.objects.filter(strategy_model=s)
            run_count = BacktestRun.objects.filter(
                Q(strategy_instance__in=instances) | Q(backtest__strategy_instance__in=instances)
            ).count()
            best_run = BacktestRun.objects.filter(
                Q(strategy_instance__in=instances) | Q(backtest__strategy_instance__in=instances)
            ).order_by("-sharpe_ratio").first()

            results.append({
                "id": s.id,
                "name": s.name,
                "class_path": s.class_path,
                "source_file": s.get_source_file_path() or "",
                "total_runs": run_count,
                "best_sharpe": best_run.sharpe_ratio if best_run else None,
            })
        return results

    @classmethod
    def get_run_detail(cls, run_id: int, include_log: bool = False) -> Dict[str, Any]:
        run = BacktestRun.objects.filter(pk=run_id).first()
        if not run:
            return {"error": f"BacktestRun #{run_id} not found."}

        data = {
            "id": run.id,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "start_date": run.start_date.isoformat() if run.start_date else None,
            "end_date": run.end_date.isoformat() if run.end_date else None,
            "total_pnl": float(run.total_pnl) if run.total_pnl is not None else None,
            "return_pct": run.return_pct,
            "sharpe_ratio": run.sharpe_ratio,
            "sortino_ratio": run.sortino_ratio,
            "calmar_ratio": run.calmar_ratio,
            "max_drawdown_pct": run.max_drawdown_pct,
            "win_rate": run.win_rate,
            "total_trades": run.total_trades,
            "config": run.config,
        }
        if include_log:
            data["log"] = run.log[:5000] if run.log else ""
        return data

    @classmethod
    def compare_runs(cls, run_ids: List[int]) -> str:
        runs = list(BacktestRun.objects.filter(pk__in=run_ids).order_by("id"))
        if len(runs) < 2:
            return "Error: Provide at least 2 valid run IDs to compare."

        lines = [
            "# Backtest Runs Comparison",
            "| Run ID | Config | Return | Total PnL | Sharpe | Max DD | Win Rate | Trades |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for idx, r in enumerate(runs, 1):
            lines.append(RunComparator.build_summary_row(r, idx))

        lines.append("")
        if len(runs) == 2:
            deltas = RunComparator.compute_deltas(runs[1], runs[0])
            lines.extend([
                f"### Delta (Run #{runs[1].id} vs Run #{runs[0].id}):",
                f"- **Sharpe**: {deltas['sharpe_delta']}",
                f"- **Return**: {deltas['return_delta']}",
                f"- **PnL**: {deltas['pnl_delta']}",
                f"- **Max Drawdown**: {deltas['drawdown_delta']}",
                f"- **Win Rate**: {deltas['win_rate_delta']}",
            ])
        return "\n".join(lines)
