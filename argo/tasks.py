import datetime
from django.utils import timezone
from argo.backtest.runner import StrategyBacktestRunner
from argo.backtest.optimizer import ParameterOptimizer, ParameterGrid


class TaskRunBacktest:
    """
    Celery task delegate running historical simulation for a Backtest model instance.
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        backtest = self.task.subject
        if not backtest.is_covered():
            backtest.load_data()
        instance = backtest.strategy_instance
        runner = StrategyBacktestRunner(starting_balance=float(backtest.initial_capital))

        start_dt = backtest.start_date or (timezone.now() - datetime.timedelta(days=90))
        end_dt = backtest.end_date or timezone.now()

        result = runner.run(
            instance=instance,
            start=start_dt,
            end=end_dt,
            params_override=backtest.params_override or None,
            backtest=backtest,
        )

        # Update Backtest record with calculated metrics
        backtest.total_pnl = result.total_pnl
        backtest.return_pct = result.return_pct
        backtest.sharpe_ratio = result.sharpe_ratio
        backtest.sortino_ratio = result.sortino_ratio
        backtest.calmar_ratio = result.calmar_ratio
        backtest.max_drawdown_pct = result.max_drawdown_pct
        backtest.profit_factor = result.profit_factor
        backtest.win_rate = result.win_rate
        backtest.total_trades = result.total_trades
        backtest.save()

        summary_msg = (
            f"Backtest Completed for {instance}:\n"
            f"- Period: {result.start_time} -> {result.end_time}\n"
            f"- Total PnL: ${result.total_pnl:,.2f} ({result.return_pct:.2%})\n"
            f"- Sharpe: {result.sharpe_ratio:.2f} | Sortino: {result.sortino_ratio:.2f} | Calmar: {result.calmar_ratio:.2f}\n"
            f"- Max DD: {result.max_drawdown_pct:.2%} | Win Rate: {result.win_rate:.1%} ({result.total_trades} trades)"
        )
        if result.total_trades == 0:
            summary_msg += "\n[DIAGNOSTIC] 0 trades executed. Review strategy entry rules, parameters, or market data."
        self.task.log(summary_msg)


class TaskRunOptimization:
    """
    Celery task delegate running parameter grid sweeps and ranking for a Backtest model instance.
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        backtest = self.task.subject
        if not backtest.is_covered():
            backtest.load_data()
        instance = backtest.strategy_instance
        runner = StrategyBacktestRunner(starting_balance=float(backtest.initial_capital))
        optimizer = ParameterOptimizer(runner=runner, objective=backtest.optimization_objective or "sharpe")

        start_dt = backtest.start_date or (timezone.now() - datetime.timedelta(days=90))
        end_dt = backtest.end_date or timezone.now()

        grid_dict = backtest.param_grid or optimizer.get_default_grid(instance.strategy_model)
        grid = ParameterGrid(grid_dict)

        report = optimizer.optimize(
            instance=instance,
            param_grid=grid,
            start=start_dt,
            end=end_dt,
            apply_best=False,  # Keep params in Backtest model until explicit promotion
        )

        backtest.best_params = report.best_params
        backtest.leaderboard = report.leaderboard
        if report.best_result:
            res = report.best_result
            backtest.total_pnl = res.total_pnl
            backtest.return_pct = res.return_pct
            backtest.sharpe_ratio = res.sharpe_ratio
            backtest.sortino_ratio = res.sortino_ratio
            backtest.calmar_ratio = res.calmar_ratio
            backtest.max_drawdown_pct = res.max_drawdown_pct
            backtest.profit_factor = res.profit_factor
            backtest.win_rate = res.win_rate
            backtest.total_trades = res.total_trades

        backtest.save()

        summary_msg = (
            f"Optimization Completed ({report.total_iterations} iterations, objective: {report.objective}):\n"
            f"- Best Parameters: {report.best_params}\n"
            f"- Best Sharpe: {getattr(report.best_result, 'sharpe_ratio', 0.0):.2f}\n"
            f"- Best PnL: ${getattr(report.best_result, 'total_pnl', 0.0):,.2f}"
        )
        self.task.log(summary_msg)


class TaskLoadData:
    """
    Celery task delegate checking and loading historical market data for Backtest or HistoricalData model instances.
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        subject = self.task.subject
        if hasattr(subject, 'load_data'):
            data_record = subject.load_data()
        else:
            raise ValueError(f"Subject {subject} does not implement load_data.")

        summary_msg = (
            f"Historical Data Ready for {subject}:\n"
            f"- Instrument: {data_record.instrument.symbol}\n"
            f"- Bar Type: {data_record.bar_type}\n"
            f"- Range: {data_record.start_date.strftime('%Y-%m-%d %H:%M')} -> {data_record.end_date.strftime('%Y-%m-%d %H:%M')}\n"
            f"- Total Bars: {data_record.bar_count:,}\n"
            f"- Source: {data_record.get_source_display()}\n"
            f"- Catalog: {data_record.catalog_path}"
        )
        self.task.log(summary_msg)
        return data_record


class TaskSearchAndCreateInstruments:
    """
    Task delegate executing an IB search for each symbol in an InstrumentGroup
    and creating the corresponding Instrument and IBContract models.
    """

    def __init__(self, task):
        self.task = task

    def process(self):
        group = self.task.subject
        created_count, total_count = group.search_and_create_instruments()
        summary_msg = (
            f"IB Search & Instrument Creation completed for '{group.name}':\n"
            f"- Created: {created_count} new instrument(s)\n"
            f"- Total Processed: {total_count} symbol(s)"
        )
        self.task.log(summary_msg)

