import datetime
from django.test import TransactionTestCase
from django.utils import timezone

from argo.backtest.runner import StrategyBacktestRunner
from argo.models import (
    BarType,
    Instrument,
    Strategy,
    StrategyInstance,
    StrategyInstrument,
)
from argo.strategies.orb_trend_following import ORBTrendFollowingStrategy


class TestBacktest(TransactionTestCase):
    """Integration test suite verifying strategy configuration and backtest execution."""

    def _create_test_instruments(self):
        """Creates and returns the four test instruments required by ORB strategy."""
        xlk, _ = Instrument.objects.get_or_create(
            symbol="XLK",
            defaults={"currency": "USD", "sec_type": "STK", "primary_exchange": "ARCA", "exchange": "ARCA"},
        )
        aapl, _ = Instrument.objects.get_or_create(
            symbol="AAPL",
            defaults={"currency": "USD", "sec_type": "STK", "primary_exchange": "NASDAQ", "exchange": "SMART"},
        )
        msft, _ = Instrument.objects.get_or_create(
            symbol="MSFT",
            defaults={"currency": "USD", "sec_type": "STK", "primary_exchange": "NASDAQ", "exchange": "SMART"},
        )
        return  xlk, aapl, msft

    def _configure_orb_strategy(self, spy, xlk, aapl, msft) -> StrategyInstance:
        """Configures ORBTrendFollowingStrategy StrategyInstance with multi-instrument keys."""
        strategy, _ = Strategy.objects.get_or_create(
            name="ORB Trend Following Test",
            defaults={"class_path": "argo.strategies.orb_trend_following.ORBTrendFollowingStrategy"},
        )
        instance = StrategyInstance.objects.create(
            strategy_model=strategy,
            bar_type=BarType.MIN_5,
            params={"orb_minutes": 30, "top_k": 2, "trade_size": 100.0},
        )
        StrategyInstrument.objects.create(strategy_instance=instance, instrument=xlk, key="sp_id")
        StrategyInstrument.objects.create(strategy_instance=instance, instrument=xlk, key="etf_id")
        StrategyInstrument.objects.create(strategy_instance=instance, instrument=aapl, key="instrument_ids")
        StrategyInstrument.objects.create(strategy_instance=instance, instrument=msft, key="instrument_ids")
        return instance

    def test_run_breakout(self):
        """Tests configuring, instantiating, and running ORBTrendFollowingStrategy in StrategyBacktestRunner."""
        xlk, aapl, msft = self._create_test_instruments()
        instance = self._configure_orb_strategy(xlk, xlk, aapl, msft)

        # 1. Verify instrument parameters mapping with single and tuple grouping
        params = instance.get_instruments_as_params()
        self.assertEqual(params["sp_id"], xlk)
        self.assertEqual(params["etf_id"], xlk)
        self.assertEqual(params["instrument_ids"], (aapl, msft))
        self.assertEqual(instance.instrument, xlk)

        # 2. Instantiate strategy and verify injected attributes
        strategy = instance.instantiate_strategy()
        self.assertIsInstance(strategy, ORBTrendFollowingStrategy)
        self.assertEqual(str(strategy.sp_id), xlk.instrument_id_str)
        self.assertEqual(str(strategy.etf_id), xlk.instrument_id_str)
        self.assertEqual(len(strategy.underlying_ids), 2)

        # 3. Execute backtest runner session
        runner = StrategyBacktestRunner(starting_balance=100_000.0)
        end = timezone.now() - datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=7)
        result = runner.run(instance=instance, start=start, end=end)

        self.assertIsNotNone(result)
        self.assertEqual(result.initial_capital, 100_000.0)
