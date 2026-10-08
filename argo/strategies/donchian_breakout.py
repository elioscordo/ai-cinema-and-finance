from typing import Optional
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide, TimeInForce

from argo.strategies.base import ArgoBaseStrategy


class DonchianBreakoutConfig(StrategyConfig, frozen=True):
    """
    Configuration for Professional Donchian Breakout (Turtle Trend) Strategy.

    Parameters:
        instrument_id: Nautilus InstrumentId string.
        bar_type: Bar aggregation type string.
        entry_period: Lookback period for upper channel breakout (default: 20).
        exit_period: Lookback period for lower channel exit (default: 10).
        trade_size: Position order quantity (default: 100.0).
        atr_period: Period for Average True Range calculation (default: 14).
        atr_stop_multiplier: Trailing stop distance multiplier in ATR units (default: 2.0).
        trend_filter_period: EMA trend regime filter period; 0 disables (default: 100).
        atr_breakout_buffer: Breakout confirmation buffer in ATR units (default: 0.1).
    """
    instrument_id: str
    bar_type: str
    entry_period: int = 20
    exit_period: int = 10
    trade_size: float = 100.0
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0
    trend_filter_period: int = 100
    atr_breakout_buffer: float = 0.1


class DonchianBreakoutStrategy(ArgoBaseStrategy):
    """
    Professional Donchian Breakout Strategy (Turtle Trend System):
    - Long breakout above N-period highest high with ATR buffer.
    - Macro regime gating via long-term EMA trend filter to eliminate bear-market whipsaws.
    - Dynamic Chandelier trailing ATR stop loss capping drawdown on false breakouts.
    - Low-channel M-period exit to let winning trends run.
    """

    def __init__(self, config: DonchianBreakoutConfig):
        super().__init__(config=config)
        self.highs: list[float] = []
        self.lows: list[float] = []
        self._tr_history: list[float] = []
        self._prev_close: Optional[float] = None
        self._trend_ema: Optional[float] = None
        self.position_open = False
        self.entry_price: float = 0.0
        self.highest_since_entry: float = 0.0

    def on_start(self):
        super().on_start()
        self.log.info(
            f"Configured DonchianBreakout: entry={self.config.entry_period}, "
            f"exit={self.config.exit_period}, stop={self.config.atr_stop_multiplier}xATR, "
            f"trend_ema={self.config.trend_filter_period}"
        )

    def _update_atr(self, high: float, low: float, close: float) -> Optional[float]:
        if self._prev_close is None:
            self._prev_close = close
            return None
        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        self._tr_history.append(tr)
        if len(self._tr_history) > self.config.atr_period:
            self._tr_history.pop(0)
        if len(self._tr_history) < self.config.atr_period:
            return None
        return sum(self._tr_history) / len(self._tr_history)

    def _update_ema(self, close: float) -> Optional[float]:
        if self.config.trend_filter_period <= 0:
            return None
        if self._trend_ema is None:
            self._trend_ema = close
        else:
            k = 2.0 / (self.config.trend_filter_period + 1)
            self._trend_ema = (close * k) + (self._trend_ema * (1.0 - k))
        return self._trend_ema

    def _is_trend_bullish(self, close: float) -> bool:
        if self.config.trend_filter_period <= 0 or self._trend_ema is None:
            return True
        return close >= self._trend_ema

    def _check_entry(self, close: float, highest_high: float, atr: Optional[float]) -> bool:
        if self.position_open:
            return False
        if not self._is_trend_bullish(close):
            return False
        buffer = (self.config.atr_breakout_buffer * atr) if atr is not None else 0.0
        return close > (highest_high + buffer)

    def _check_exit(self, close: float, lowest_low: float, atr: Optional[float]) -> tuple[bool, str]:
        if not self.position_open:
            return False, ""
        if atr is not None and self.config.atr_stop_multiplier > 0:
            trailing_stop = self.highest_since_entry - (self.config.atr_stop_multiplier * atr)
            if close < trailing_stop:
                return True, f"ATR Trailing Stop ({close:.2f} < {trailing_stop:.2f})"
        if close < lowest_low:
            return True, f"Donchian Low Exit ({close:.2f} < {lowest_low:.2f})"
        return False, ""

    def _execute_buy(self, close: float) -> None:
        qty = self.make_qty(self.config.trade_size)
        order = self.order_factory.market(self.instrument_id, OrderSide.BUY, qty, TimeInForce.GTC)
        self.submit_order(order)
        self.position_open = True
        self.entry_price = close
        self.highest_since_entry = close
        self.log.info(f"[{self.instrument_id}] Donchian Buy at {close:.2f} (qty={qty})")

    def _execute_sell(self, close: float, reason: str) -> None:
        qty = self.make_qty(self.config.trade_size)
        order = self.order_factory.market(self.instrument_id, OrderSide.SELL, qty, TimeInForce.GTC)
        self.submit_order(order)
        self.position_open = False
        self.log.info(f"[{self.instrument_id}] Donchian Sell at {close:.2f} - {reason}")

    def _record_history(self, high: float, low: float) -> None:
        max_lookback = max(self.config.entry_period, self.config.exit_period)
        self.highs.append(high)
        self.lows.append(low)
        if len(self.highs) > max_lookback:
            self.highs.pop(0)
            self.lows.pop(0)

    def on_bar(self, bar: Bar):
        if not self.is_matching_bar(bar):
            return

        high = float(bar.high)
        low = float(bar.low)
        close = float(bar.close)

        atr = self._update_atr(high, low, close)
        self._update_ema(close)

        if self.position_open:
            self.highest_since_entry = max(self.highest_since_entry, high)
            if len(self.lows) >= self.config.exit_period:
                lowest_low = min(self.lows[-self.config.exit_period:])
                should_exit, reason = self._check_exit(close, lowest_low, atr)
                if should_exit:
                    self._execute_sell(close, reason)
        else:
            if len(self.highs) >= self.config.entry_period:
                highest_high = max(self.highs[-self.config.entry_period:])
                if self._check_entry(close, highest_high, atr):
                    self._execute_buy(close)

        self._record_history(high, low)

    def on_stop(self):
        super().on_stop()
        self.log.info(f"Stopping DonchianBreakoutStrategy for {self.instrument_id}")
