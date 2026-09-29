import importlib
import inspect
import pkgutil
from django.apps import apps
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.data import BarType
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy as NautilusStrategy


def resolve_strategy_classes(class_path: str):
    """
    Imports and returns (strategy_class, config_class) for a given strategy class path.
    Discovers the configuration class dynamically without assuming a fixed naming pattern.
    """
    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    strategy_class = getattr(module, class_name)

    config_class = None

    # 1. Inspect __init__ signature of strategy_class for a 'config' parameter annotation
    try:
        sig = inspect.signature(strategy_class.__init__)
        if "config" in sig.parameters:
            ann = sig.parameters["config"].annotation
            if inspect.isclass(ann) and issubclass(ann, StrategyConfig):
                config_class = ann
            elif isinstance(ann, str) and hasattr(module, ann):
                candidate = getattr(module, ann)
                if inspect.isclass(candidate) and issubclass(candidate, StrategyConfig):
                    config_class = candidate
    except Exception:
        pass

    # 2. Check strategy_class attributes
    if not config_class:
        for attr in ("config_type", "Config", "config_class"):
            candidate = getattr(strategy_class, attr, None)
            if inspect.isclass(candidate) and issubclass(candidate, StrategyConfig):
                config_class = candidate
                break

    # 3. Check conventional naming variants in the module
    if not config_class:
        candidates = [
            f"{class_name}Config",
            f"{class_name[:-8]}Config" if class_name.endswith("Strategy") else f"{class_name}Config",
        ]
        for c in candidates:
            candidate = getattr(module, c, None)
            if inspect.isclass(candidate) and issubclass(candidate, StrategyConfig):
                config_class = candidate
                break

    # 4. Search module for any StrategyConfig subclass
    if not config_class:
        for attr_name in dir(module):
            val = getattr(module, attr_name)
            if inspect.isclass(val) and issubclass(val, StrategyConfig) and val is not StrategyConfig:
                config_class = val
                break

    return strategy_class, config_class


DEFAULT_STRATEGIES = [
    {
        "name": "EMA Crossover Strategy",
        "class_path": "argo.strategies.ema_cross.EMACrossStrategy",
        "description": "Trend-following strategy using Fast vs Slow Exponential Moving Average crossover."
    },
    {
        "name": "Bollinger Bands Mean Reversion",
        "class_path": "argo.strategies.mean_reversion.BBMeanReversionStrategy",
        "description": "Mean-reversion strategy that buys below lower band and closes at upper band / mean."
    },
    {
        "name": "RSI Mean Reversion",
        "class_path": "argo.strategies.rsi.RSIStrategy",
        "description": "Oscillator strategy buying when oversold (<30) and exiting when overbought (>70)."
    },
    {
        "name": "MACD Momentum Strategy",
        "class_path": "argo.strategies.macd.MACDStrategy",
        "description": "Momentum strategy trading MACD line crossovers with the signal line."
    },
    {
        "name": "Donchian Breakout (Turtle)",
        "class_path": "argo.strategies.donchian_breakout.DonchianBreakoutStrategy",
        "description": "Classic Turtle Trading breakout system on N-period channel highs and lows."
    },
    {
        "name": "SuperTrend Volatility Breakout",
        "class_path": "argo.strategies.supertrend_breakout.SuperTrendBreakoutStrategy",
        "description": "SuperTrend ATR volatility breakout trend-following system with dynamic trailing stops and multi-factor filtering."
    },
    {
        "name": "Kaufman Adaptive Trend Strategy",
        "class_path": "argo.strategies.kama_trend.KaufmanAdaptiveTrendStrategy",
        "description": "Adaptive trend-following using Kaufman Efficiency Ratio (KAMA) to filter noise and capture trends."
    },
    {
        "name": "Triple EMA Continuation Strategy",
        "class_path": "argo.strategies.triple_ma_trend.TripleMAContinuationStrategy",
        "description": "Multi-horizon structural trend alignment with pullback continuation triggers and risk forecasting."
    },
    {
        "name": "Dual Momentum Strategy",
        "class_path": "argo.strategies.dual_momentum.DualMomentumStrategy",
        "description": "Dual momentum system combining macro 200-SMA regime gating with momentum breakout execution and multi-factor risk controls."
    },
    {
        "name": "Buy and Hold Benchmark",
        "class_path": "argo.strategies.buy_and_hold.BuyAndHoldStrategy",
        "description": "Baseline passive benchmark holding an asset from start to evaluate strategy alpha."
    },
    {
        "name": "ORB Trend Following Strategy",
        "class_path": "argo.strategies.orb_trend_following.ORBTrendFollowingStrategy",
        "description": "US Market Opening Range Breakout (ORB) trend-following strategy with S&P 500 and ETF confirmation buying top underlying winners."
    },
]


def discover_strategies():
    """Returns available strategy choices for Strategy.class_path field."""
    return [(s["class_path"], s["name"]) for s in DEFAULT_STRATEGIES]


def load_strategies_from_package(package_name: str = "argo.strategies"):
    """
    Dynamically discovers all NautilusStrategy subclasses in the package
    and creates/updates corresponding Strategy database records.
    """
    Strategy = apps.get_model("argo", "Strategy")
    package = importlib.import_module(package_name)
    loaded = []

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        full_module_name = f"{package_name}.{module_name}"
        try:
            module = importlib.import_module(full_module_name)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    inspect.isclass(attr)
                    and issubclass(attr, NautilusStrategy)
                    and attr is not NautilusStrategy
                    and attr.__module__ == full_module_name
                ):
                    class_path = f"{full_module_name}.{attr.__name__}"
                    doc = inspect.getdoc(attr) or ""
                    name = attr.__name__.replace("Strategy", " Strategy").strip()
                    obj, _ = Strategy.objects.update_or_create(
                        class_path=class_path,
                        defaults={"name": name, "description": doc.strip()}
                    )
                    loaded.append(obj)
        except Exception as e:
            print(f"[ERROR] Failed loading strategies from {full_module_name}: {e}")

    return loaded


def populate_default_strategies():
    """Populates the database Strategy model with default benchmark strategies."""
    return load_strategies_from_package("argo.strategies")


def load_strategies_from_db(node: TradingNode):
    """
    Finds the active portfolio in the database and loads its strategy instances
    into the trading node.
    """
    Portfolio = apps.get_model("argo", "Portfolio")
    try:
        active_portfolio = Portfolio.objects.get(is_active=True)
    except (Portfolio.DoesNotExist, Portfolio.MultipleObjectsReturned):
        return

    instances = (
        active_portfolio.strategy_instances.filter(is_active=True)
        if hasattr(active_portfolio, "strategy_instances")
        else apps.get_model("argo", "StrategyInstance").objects.filter(is_active=True)
    )

    for instance in instances:
        try:
            strategy = instance.instantiate_strategy()
            node.add_strategy(strategy)
        except Exception as e:
            print(f"[ERROR] Failed to load strategy instance {instance.id}: {e}")