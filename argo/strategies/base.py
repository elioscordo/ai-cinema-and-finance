from typing import Optional
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy


class ArgoBaseStrategy(NautilusStrategy):
    """
    Template base strategy providing standard instrument resolution,
    quantity formatting, and lifecycle hooks for NautilusTrader.
    """

    def __init__(self, config):
        super().__init__(config=config)
        self.instrument_id: InstrumentId = (
            InstrumentId.from_str(config.instrument_id)
            if isinstance(config.instrument_id, str)
            else config.instrument_id
        )
        self._instrument_id = self.instrument_id
        self._bar_type: BarType = (
            BarType.from_str(config.bar_type)
            if isinstance(config.bar_type, str)
            else config.bar_type
        )
        self.instrument: Optional[Instrument] = None

    def _log_msg(self, level: str, msg: str) -> None:
        getattr(self.log, level, self.log.info)(msg)
        import logging
        logging.getLogger(f"argo.strategy.{self.__class__.__name__}").log(
            getattr(logging, level.upper(), logging.INFO), msg
        )

    def on_start(self):
        self.instrument = self.cache.instrument(self.instrument_id)
        self._log_msg("info", f"Starting {self.__class__.__name__} for {self.instrument_id}")
        self.subscribe_bars(self._bar_type)

    def make_qty(self, trade_size: float) -> Quantity:
        if self.instrument is not None:
            return self.instrument.make_qty(trade_size)
        return Quantity.from_str(str(trade_size))

    def is_matching_bar(self, bar: Bar) -> bool:
        return bar.bar_type == self._bar_type or bar.instrument_id == self.instrument_id

    def on_order_submitted(self, event) -> None:
        self._log_msg("info", f"[{self.instrument_id}] ORDER SUBMITTED: client_order_id={getattr(event, 'client_order_id', event)}")

    def on_order_filled(self, event) -> None:
        self._log_msg(
            "info",
            f"[{self.instrument_id}] ORDER FILLED: client_order_id={getattr(event, 'client_order_id', 'N/A')}, "
            f"qty={getattr(event, 'last_qty', 'N/A')}, px={getattr(event, 'last_px', 'N/A')}"
        )

    def on_order_rejected(self, event) -> None:
        self._log_msg(
            "error",
            f"[{self.instrument_id}] ORDER REJECTED: client_order_id={getattr(event, 'client_order_id', 'N/A')}, "
            f"reason={getattr(event, 'reason', 'N/A')}"
        )

    def on_order_canceled(self, event) -> None:
        self._log_msg("warning", f"[{self.instrument_id}] ORDER CANCELED: client_order_id={getattr(event, 'client_order_id', 'N/A')}")

    def on_stop(self):
        super().on_stop()
        self._log_msg("info", f"Stopping {self.__class__.__name__} for {self.instrument_id}")

