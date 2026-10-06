"""
Opening Range Breakout (ORB) Trend-Following Strategy
=====================================================
Multi-instrument trend-following system:
- Monitors US Market open (09:30 AM US/Eastern) Opening Range (ORB).
- Validates macro regime: S&P 500 (sp_id) and sector ETF (etf_id) must both break out above their ORB highs.
- Executes: Selects and buys the top K underlying winners (ranked by return since open).
- Exits: Closes positions before market close (intraday trend persistence).
"""

import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy

from argo.strategies.orb_indicator import OpeningRangeBreakoutIndicator

logger = logging.getLogger("argo.strategy.ORBTrendFollowingStrategy")


class ORBTrendFollowingConfig(StrategyConfig, frozen=True):
    """
    Configuration parameters for ORBTrendFollowingStrategy.

    Attributes:
        sp_id: S&P 500 proxy identifier (e.g. 'SPY.SMART' or 'ES.CME').
        etf_id: Sub/sector ETF identifier (e.g. 'QQQ.SMART', 'XLK.SMART').
        instrument_ids: Tuple of underlying stock identifiers.
        bar_type: Bar aggregation type (default: '1-MINUTE-BAR-MID-EXTERNAL').
        orb_minutes: Duration of the opening range in minutes (default: 30).
        top_k: Number of top performing underlying winners to purchase (default: 3).
        trade_size: Position size per winning instrument (default: 100.0).
        open_time_str: Session open time in US/Eastern (default: '09:30').
        close_time_str: Session exit time in US/Eastern (default: '15:55').
        market_tz: Market timezone (default: 'America/New_York').
        exit_at_close: Whether to close all active positions before market close (default: True).
    """
    sp_id: str
    etf_id: str
    instrument_ids: Union[Tuple[str, ...], List[str]]
    bar_type: str = "1-MINUTE-BAR-MID-EXTERNAL"
    orb_minutes: int = 30
    top_k: int = 3
    trade_size: float = 100.0
    open_time_str: str = "09:30"
    close_time_str: str = "15:55"
    market_tz: str = "America/New_York"
    exit_at_close: bool = True


class ORBTrendFollowingStrategy(NautilusStrategy):
    """
    US Market Open Range Breakout (ORB) Trend Following Strategy.
    """

    def __init__(self, config: ORBTrendFollowingConfig):
        super().__init__(config=config)
        self.sp_id = InstrumentId.from_str(config.sp_id)
        self.etf_id = InstrumentId.from_str(config.etf_id)

        raw_ids = config.instrument_ids
        if isinstance(raw_ids, str):
            raw_ids = [s.strip() for s in raw_ids.split(",") if s.strip()]
        self.underlying_ids = [InstrumentId.from_str(s) for s in raw_ids]

        self.all_instrument_ids = [self.sp_id, self.etf_id] + self.underlying_ids

        self.tz = ZoneInfo(config.market_tz)
        hour, minute = map(int, config.close_time_str.split(":"))
        self.close_time = datetime.time(hour, minute)

        self.sp_orb = self._build_orb_indicator()
        self.etf_orb = self._build_orb_indicator()
        self.underlying_orbs: Dict[InstrumentId, OpeningRangeBreakoutIndicator] = {
            uid: self._build_orb_indicator() for uid in self.underlying_ids
        }

        self.current_session_date: Optional[datetime.date] = None
        self.entered_today: bool = False
        self.active_positions: Dict[InstrumentId, Quantity] = {}

    def _build_orb_indicator(self) -> OpeningRangeBreakoutIndicator:
        return OpeningRangeBreakoutIndicator(
            orb_minutes=self.config.orb_minutes,
            open_time_str=self.config.open_time_str,
            market_tz=self.config.market_tz,
        )

    def _log_msg(self, level: str, msg: str) -> None:
        """Dual-logs to NautilusTrader native logger and Python standard logger."""
        getattr(self.log, level, self.log.info)(msg)
        logger.log(getattr(logging, level.upper(), logging.INFO), msg)

    def on_start(self):
        super().on_start()
        self._log_msg(
            "info",
            f"Starting {self.__class__.__name__} with SP={self.sp_id}, ETF={self.etf_id}, "
            f"{len(self.underlying_ids)} underlyings, ORB={self.config.orb_minutes}m",
        )
        for instr_id in dict.fromkeys(self.all_instrument_ids):
            bar_type = self._resolve_bar_type(instr_id)
            self.subscribe_bars(bar_type)

    def _resolve_bar_type(self, instr_id: InstrumentId) -> BarType:
        """Resolves a valid native Nautilus BarType for the given instrument."""
        if isinstance(self.config.bar_type, BarType):
            if self.config.bar_type.instrument_id == instr_id:
                return self.config.bar_type
            return BarType(instr_id, self.config.bar_type.spec, self.config.bar_type.aggregation_source)

        raw = str(self.config.bar_type or "1-MINUTE").strip()
        # Strip leading instrument prefix if present (e.g. 'AAPL.SMART-5-MINUTE-LAST-EXTERNAL')
        if "-" in raw:
            prefix = raw.split("-", 1)[0]
            if "." in prefix or "/" in prefix:
                raw = raw.split("-", 1)[1]

        # Extract price type if specified, default to LAST
        price_type = "LAST"
        for pt in ("-LAST", "-MID", "-BID", "-ASK"):
            if pt in raw:
                price_type = pt.replace("-", "")
                break

        # Extract core timeframe spec (e.g. '5-MINUTE')
        timeframe = raw
        for token in ("-EXTERNAL", "-INTERNAL", "-LAST", "-MID", "-BID", "-ASK", "-BAR"):
            timeframe = timeframe.replace(token, "")
        timeframe = timeframe.strip("-") or "1-MINUTE"

        # Reconstruct canonical Nautilus BarType: {instrument_id}-{timeframe}-{price_type}-EXTERNAL
        full_spec = f"{instr_id}-{timeframe}-{price_type}-EXTERNAL"
        return BarType.from_str(full_spec)

    def on_bar(self, bar: Bar):
        instr_id = bar.bar_type.instrument_id
        self._route_bar_to_indicator(instr_id, bar)

        dt = self._extract_bar_datetime(bar)
        if self.current_session_date != dt.date():
            self._reset_daily_session(dt.date())

        if self.config.exit_at_close and dt.time() >= self.close_time and self.active_positions:
            self._close_all_positions()

        if not self.entered_today:
            self._check_and_execute_breakout()

    def _route_bar_to_indicator(self, instr_id: InstrumentId, bar: Bar) -> None:
        if instr_id == self.sp_id:
            self.sp_orb.update(bar)
        elif instr_id == self.etf_id:
            self.etf_orb.update(bar)
        elif instr_id in self.underlying_orbs:
            self.underlying_orbs[instr_id].update(bar)

    def _extract_bar_datetime(self, bar: Bar) -> datetime.datetime:
        ts_ns = bar.ts_event or bar.ts_init
        return datetime.datetime.fromtimestamp(ts_ns / 1e9, tz=datetime.timezone.utc).astimezone(self.tz)

    def _reset_daily_session(self, new_date: datetime.date) -> None:
        self.current_session_date = new_date
        self.entered_today = False
        self.active_positions.clear()
        self._log_msg("info", f"[ORB Session Reset] Date: {new_date}. Active positions cleared.")

    def _check_and_execute_breakout(self) -> None:
        if not (self.sp_orb.is_breakout_high and self.etf_orb.is_breakout_high):
            return

        candidates = [
            (uid, self.underlying_orbs[uid].return_since_open)
            for uid in self.underlying_ids
            if self.underlying_orbs[uid].is_complete
        ]
        if not candidates:
            return

        candidates.sort(key=lambda item: item[1], reverse=True)
        top_winners = candidates[:self.config.top_k]

        self._log_msg(
            "info",
            f"[ORB Breakout Triggered] Macro breakout confirmed: SP={self.sp_id}, ETF={self.etf_id}. "
            f"Executing top {len(top_winners)} winner(s).",
        )

        for winner_id, ret in top_winners:
            self._open_long_position(winner_id, ret)

        self.entered_today = True

    def _open_long_position(self, instrument_id: InstrumentId, score: float) -> None:
        instr = self.cache.instrument(instrument_id)
        qty = instr.make_qty(self.config.trade_size) if instr else Quantity.from_str(str(self.config.trade_size))
        order = self.order_factory.market(instrument_id, OrderSide.BUY, qty, TimeInForce.GTC)
        self.submit_order(order)
        self.active_positions[instrument_id] = qty
        self._log_msg(
            "info",
            f"[ORB Entry] Macro & Sector Breakout! Buying top winner {instrument_id} (Return: {score:.2%}, Qty: {qty})",
        )

    def _close_all_positions(self) -> None:
        for instrument_id, qty in list(self.active_positions.items()):
            order = self.order_factory.market(instrument_id, OrderSide.SELL, qty, TimeInForce.GTC)
            self.submit_order(order)
            self._log_msg("info", f"[ORB Session Close] Closing position {instrument_id} (Qty: {qty})")
        self.active_positions.clear()

    def on_order_submitted(self, event) -> None:
        self._log_msg("info", f"[ORB Order Submitted] client_order_id={getattr(event, 'client_order_id', event)}")

    def on_order_filled(self, event) -> None:
        self._log_msg(
            "info",
            f"[ORB Order Filled] client_order_id={getattr(event, 'client_order_id', 'N/A')}, "
            f"qty={getattr(event, 'last_qty', 'N/A')}, px={getattr(event, 'last_px', 'N/A')}",
        )

    def on_order_rejected(self, event) -> None:
        self._log_msg("warning", f"[ORB Order Rejected] {event}")

    def on_order_canceled(self, event) -> None:
        self._log_msg("info", f"[ORB Order Canceled] {event}")

    def on_stop(self):
        super().on_stop()
        self._log_msg("info", f"Stopping {self.__class__.__name__}. Completed simulation.")
