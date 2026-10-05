import datetime
import json
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from django.test import TransactionTestCase
from argo.models import (
    BarType,
    InstrumentGroup,
    Instrument,
    AssetClass,
    HistoricalData,
    Backtest,
    Strategy,
    StrategyInstance,
    StrategyInstrument,
)
from argo.ib.search import InteractiveBrokersSearchService
from argo.ib.ib_download import IBDownloader

        

class SearchTest(TransactionTestCase):
    """
    Live integration test for InstrumentsSchema using the real IB Gateway/TWS service.
    """

    def test_search(self):
        matches = InteractiveBrokersSearchService().search(query="BTC/USD")
        assert matches, "Expected to find at least one match for BTC/USD"
        match = next((m for m in matches if m.symbol == "BTC/USD"), None)
        assert match is not None, "Expected to find BTC/USD in the search results"

    def test_search_create(self):
        fixture_path = Path(__file__).parent / "fixtures" / "instruments.json"
        with open(fixture_path) as f:
            instruments = json.load(f)

        group = InstrumentGroup.objects.create(
            name="Test Group",
            code="TEST_GROUP",
            instruments=instruments,
        )
        group.create_instruments()

class HistoricTest(TransactionTestCase):
    """
    Live integration test verifying HistoricInteractiveBrokersStrategy against IB Gateway.
    """
    def test_load_data(self):
        instrument, _ = Instrument.objects.get_or_create(
            symbol="ADBE",
            currency="USD",
            sec_type="STK",
            primary_exchange="NASDAQ",
            exchange="NASDAQ",
        )
        strategy, _ = Strategy.objects.get_or_create(
            name="EMA Cross Test",
            defaults={"class_path": "argo.strategies.ema_cross.EMACrossStrategy"},
        )
        instance = StrategyInstance.objects.create(
            strategy_model=strategy,
            params={"fast_period": 10, "slow_period": 20},
            bar_type=BarType.MIN_5
        )
        StrategyInstrument.objects.create(
            strategy_instance=instance,
            instrument=instrument,
            key="instrument_id"
        )
        end = timezone.now() - datetime.timedelta(days=10)
        start = end - datetime.timedelta(days=1000)
        backtest = Backtest.objects.create(
            strategy_instance=instance,
            name="ADBE Test Run",
            start_date=start,
            end_date=end,
        )
        backtest.load_data()
        self.assertTrue(backtest.is_covered(), backtest.check_coverage())
