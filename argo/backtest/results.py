from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass(frozen=True)
class BacktestResult:
    """Immutable Value Object representing performance output of a single backtest run."""
    instance_id: int
    strategy_name: str
    instrument_id: str
    start_time: str
    end_time: str
    initial_capital: float
    final_equity: float
    total_pnl: float
    return_pct: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration: str
    profit_factor: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_trade_pnl: float
    params: Dict[str, Any]
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    run_id: Optional[int] = None

    def with_run_id(self, run_id: int) -> "BacktestResult":
        from dataclasses import replace
        return replace(self, run_id=run_id)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes result metrics into a clean dictionary."""
        return {
            "run_id": self.run_id,
            "instance_id": self.instance_id,
            "strategy_name": self.strategy_name,
            "instrument_id": self.instrument_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "initial_capital": round(self.initial_capital, 2),
            "final_equity": round(self.final_equity, 2),
            "total_pnl": round(self.total_pnl, 2),
            "return_pct": round(self.return_pct, 4),
            "annualized_return": round(self.annualized_return, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_duration": self.max_drawdown_duration,
            "profit_factor": round(self.profit_factor, 2),
            "win_rate": round(self.win_rate, 3),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "avg_trade_pnl": round(self.avg_trade_pnl, 2),
            "params": self.params,
        }


@dataclass
class OptimizationReport:
    """Summary of parameter optimization sweeps across multiple backtest iterations."""
    instance_id: int
    objective: str
    total_iterations: int
    best_params: Dict[str, Any]
    best_result: Optional[BacktestResult]
    leaderboard: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "objective": self.objective,
            "total_iterations": self.total_iterations,
            "best_params": self.best_params,
            "best_score": round(getattr(self.best_result, "sharpe_ratio", 0.0), 2) if self.best_result else 0.0,
            "leaderboard": self.leaderboard[:10],
        }
