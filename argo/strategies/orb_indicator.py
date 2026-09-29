"""
Opening Range Breakout (ORB) Indicator
======================================
State pattern implementation tracking session opening range (high, low, open)
during US market open window (e.g. 09:30 - 10:00 AM US/Eastern) and identifying breakouts.
"""

from dataclasses import dataclass
import datetime
from typing import Optional
from zoneinfo import ZoneInfo
from nautilus_trader.model.data import Bar


@dataclass
class ORBState:
    """State snapshot for the Opening Range Breakout indicator."""
    session_date: Optional[datetime.date] = None
    open_price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    is_complete: bool = False
    is_breakout_high: bool = False
    is_breakout_low: bool = False
    breakout_pct: float = 0.0
    return_since_open: float = 0.0


class OpeningRangeBreakoutIndicator:
    """
    Opening Range Breakout (ORB) Indicator.
    Monitors market open window, locks opening range, and determines breakout states.
    """

    def __init__(
        self,
        orb_minutes: int = 30,
        open_time_str: str = "09:30",
        market_tz: str = "America/New_York",
    ):
        self.orb_minutes = orb_minutes
        self.tz = ZoneInfo(market_tz)
        hour, minute = map(int, open_time_str.split(":"))
        self.open_time = datetime.time(hour, minute)

        dummy_today = datetime.date.today()
        range_end_dt = datetime.datetime.combine(dummy_today, self.open_time) + datetime.timedelta(minutes=orb_minutes)
        self.range_end_time = range_end_dt.time()
        self.state = ORBState()

    def update(self, bar: Bar) -> ORBState:
        """Processes incoming bar and updates opening range breakout state."""
        dt = self._extract_bar_datetime(bar)
        bar_date = dt.date()
        bar_time = dt.time()

        if self.state.session_date != bar_date:
            self.state = ORBState(session_date=bar_date)

        if bar_time < self.open_time:
            return self.state

        if self.open_time <= bar_time < self.range_end_time:
            self._update_range_window(float(bar.open), float(bar.high), float(bar.low), float(bar.close))
        elif bar_time >= self.range_end_time and self.state.open_price > 0.0:
            self._evaluate_breakout(float(bar.close))

        return self.state

    def _extract_bar_datetime(self, bar: Bar) -> datetime.datetime:
        ts_ns = bar.ts_event or bar.ts_init
        return datetime.datetime.fromtimestamp(ts_ns / 1e9, tz=datetime.timezone.utc).astimezone(self.tz)

    def _update_range_window(self, open_px: float, high_px: float, low_px: float, close_px: float) -> None:
        if self.state.open_price == 0.0:
            self.state.open_price = open_px
            self.state.high = high_px
            self.state.low = low_px
        else:
            self.state.high = max(self.state.high, high_px)
            self.state.low = min(self.state.low, low_px)
        self.state.close = close_px
        self.state.is_complete = False

    def _evaluate_breakout(self, close_px: float) -> None:
        self.state.is_complete = True
        self.state.close = close_px
        self.state.return_since_open = (close_px - self.state.open_price) / self.state.open_price if self.state.open_price else 0.0

        if close_px > self.state.high:
            self.state.is_breakout_high = True
            self.state.breakout_pct = (close_px - self.state.high) / self.state.high
        else:
            self.state.is_breakout_high = False
            self.state.breakout_pct = 0.0

        self.state.is_breakout_low = close_px < self.state.low

    @property
    def is_breakout_high(self) -> bool:
        return self.state.is_complete and self.state.is_breakout_high

    @property
    def is_breakout_low(self) -> bool:
        return self.state.is_complete and self.state.is_breakout_low

    @property
    def return_since_open(self) -> float:
        return self.state.return_since_open

    @property
    def is_complete(self) -> bool:
        return self.state.is_complete
