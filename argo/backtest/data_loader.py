import datetime
import math
import random
from typing import List, Optional, Tuple
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from django.conf import settings

class BacktestDataLoader:
    """
    Adapter loading historical bar datasets for Nautilus Trader backtesting.
    Supports ParquetDataCatalog, on-demand download, and fallback market generation.
    """


    def load_or_fetch_bars(
        self,
        bar_type,
        start: datetime.datetime,
        end: datetime.datetime,
        
    ):
        """
        Loads bars with fallback chain: local catalog -> IB Gateway download.
        Returns a tuple of (bars, source_name).
        """
        catalog = ParquetDataCatalog(settings.HISTORICAL_ROOT)
        bars = catalog.bars(
            bar_type=bar_type,
            start=start,
            end=end,
        )
        return bars


    def _fetch_from_ib(
        self,
        instrument_obj,
        bar_type: BarType,
        start: datetime.datetime,
        end: datetime.datetime,
    ) -> Optional[List[Bar]]:
        """Attempts on-demand historical bar extraction from IB Gateway via Nautilus Trader."""
        try:
            from argo.ib.ib_download import HistoricInteractiveBrokersStrategy
            strategy = HistoricInteractiveBrokersStrategy()
            bars = strategy.fetch_bars(instrument_obj, str(bar_type), start, end)
            return bars if bars else None
        except Exception:
            return None

    def _load_from_catalog(
        self,
        bar_type: BarType,
        start: datetime.datetime,
        end: datetime.datetime,
    ) -> Optional[List[Bar]]:
        """Attempts to read historical bars from local ParquetDataCatalog."""
        try:
            catalog = ParquetDataCatalog(self.catalog_path)
            bars = catalog.bars(
                bar_type=bar_type,
                start=start,
                end=end,
            )
            if not bars and "-EXTERNAL" in str(bar_type):
                alt_bt = BarType.from_str(str(bar_type).replace("-EXTERNAL", "-INTERNAL"))
                bars = catalog.bars(bar_type=alt_bt, start=start, end=end)
            return list(bars) if bars else None
        except Exception:
            return None

   