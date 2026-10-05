import datetime
import os
import re
from pathlib import Path
from django.db import models
from django.conf import settings
from nautilus_trader.model.data import BarType
from argo.ib.ib_download import IBDownloader
from .utils import (
    discover_strategies,
    is_interval_empty,
    is_market_closure_gap,
    load_empty_intervals,
)
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords
from task.mixins import AfterSaveActionMixin
from task.models import TaskHolder
from agent.models import GetContentsMixin, Agent
from typing import Optional, List, Tuple, Dict, Any
from django.utils import timezone
from .mixins import CloneModelMixin
from nautilus_trader.adapters.interactive_brokers.common import IBContract as NautilusIBContract
from argo.ib.search import InteractiveBrokersSearchService
from dataclasses import asdict
from nautilus_trader.core.datetime import dt_to_unix_nanos, unix_nanos_to_dt
from nautilus_trader.model.data import Bar
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model.data import Bar
from nautilus_trader.persistence.catalog import ParquetDataCatalog

class BarType(models.TextChoices):
    SEC_1 = '1-SECOND', _('1 Second')
    MIN_1 = '1-MINUTE', _('1 Minute')
    MIN_5 = '5-MINUTE', _('5 Minutes')
    MIN_15 = '15-MINUTE', _('15 Minutes')
    MIN_30 = '30-MINUTE', _('30 Minutes')
    HOUR_1 = '1-HOUR', _('1 Hour')
    HOUR_4 = '4-HOUR', _('4 Hours')
    DAY_1 = '1-DAY', _('1 Day')
    WEEK_1 = '1-WEEK', _('1 Week')
    MONTH_1 = '1-MONTH', _('1 Month')

class Account(models.Model):
    """
    Represents a trading account synchronized from NautilusTrader.
    """
    account_id = models.CharField(max_length=100, unique=True, help_text="Nautilus AccountId string.")
    account_type = models.CharField(max_length=50, blank=True, help_text="e.g. CASH, MARGIN, BETTING.")
    base_currency = models.CharField(max_length=10, blank=True, help_text="Base currency code (e.g. USD, EUR).")
    
    balance_total = models.DecimalField(max_digits=20, decimal_places=4, default=0.0)
    balance_free = models.DecimalField(max_digits=20, decimal_places=4, default=0.0)
    balance_locked = models.DecimalField(max_digits=20, decimal_places=4, default=0.0)
    
    balances = models.JSONField(default=dict, blank=True, help_text="Multi-currency balance breakdowns.")
    margins = models.JSONField(default=dict, blank=True, help_text="Margin usage details.")
    info = models.JSONField(default=dict, blank=True, help_text="Additional broker metadata.")
    
    is_reported = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['account_id']
        verbose_name = _('Account')
        verbose_name_plural = _('Accounts')

    def __str__(self):
        return f"{self.account_id} ({self.base_currency} {self.balance_total})"

    @classmethod
    def sync_from_nautilus(cls, nautilus_account):
        """
        Synchronizes a NautilusTrader Account instance or AccountState event to the database.
        """
        account_id = str(getattr(nautilus_account, "id", getattr(nautilus_account, "account_id", nautilus_account)))
        account_type = str(getattr(nautilus_account, "account_type", ""))
        base_currency = str(getattr(nautilus_account, "base_currency", ""))
        
        balances_dict = {}
        total_bal = 0.0
        free_bal = 0.0
        locked_bal = 0.0

        if hasattr(nautilus_account, "balances"):
            raw_balances = nautilus_account.balances() if callable(nautilus_account.balances) else nautilus_account.balances
            if isinstance(raw_balances, dict):
                for curr, bal in raw_balances.items():
                    curr_str = str(curr)
                    c_total = float(getattr(bal, "total", getattr(bal, "balance_total", 0.0)))
                    c_free = float(getattr(bal, "free", getattr(bal, "balance_free", 0.0)))
                    c_locked = float(getattr(bal, "locked", getattr(bal, "balance_locked", 0.0)))
                    balances_dict[curr_str] = {"total": c_total, "free": c_free, "locked": c_locked}
                    if not total_bal or curr_str == base_currency:
                        total_bal, free_bal, locked_bal = c_total, c_free, c_locked
            elif isinstance(raw_balances, list):
                for bal in raw_balances:
                    curr_str = str(getattr(bal, "currency", base_currency))
                    c_total = float(getattr(bal, "total", 0.0))
                    c_free = float(getattr(bal, "free", 0.0))
                    c_locked = float(getattr(bal, "locked", 0.0))
                    balances_dict[curr_str] = {"total": c_total, "free": c_free, "locked": c_locked}
                    if not total_bal or curr_str == base_currency:
                        total_bal, free_bal, locked_bal = c_total, c_free, c_locked

        if hasattr(nautilus_account, "balance_total"):
            b_total = getattr(nautilus_account, "balance_total", None)
            total_bal = float(b_total() if callable(b_total) else b_total) if b_total is not None else total_bal
        if hasattr(nautilus_account, "balance_free"):
            b_free = getattr(nautilus_account, "balance_free", None)
            free_bal = float(b_free() if callable(b_free) else b_free) if b_free is not None else free_bal
        if hasattr(nautilus_account, "balance_locked"):
            b_locked = getattr(nautilus_account, "balance_locked", None)
            locked_bal = float(b_locked() if callable(b_locked) else b_locked) if b_locked is not None else locked_bal

        margins_dict = {}
        if hasattr(nautilus_account, "margins"):
            raw_margins = nautilus_account.margins() if callable(nautilus_account.margins) else nautilus_account.margins
            if isinstance(raw_margins, dict):
                margins_dict = {str(k): float(v) if isinstance(v, (int, float)) else str(v) for k, v in raw_margins.items()}

        info_dict = {}
        if hasattr(nautilus_account, "info"):
            raw_info = nautilus_account.info
            info_dict = raw_info if isinstance(raw_info, dict) else {}

        instance, _ = cls.objects.update_or_create(
            account_id=account_id,
            defaults={
                "account_type": account_type,
                "base_currency": base_currency,
                "balance_total": total_bal,
                "balance_free": free_bal,
                "balance_locked": locked_bal,
                "balances": balances_dict,
                "margins": margins_dict,
                "info": info_dict,
            },
        )
        return instance


class Position(models.Model):
    class Side(models.TextChoices):
        LONG = 'LONG', 'Long'
        SHORT = 'SHORT', 'Short'

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        CLOSED = 'CLOSED', 'Closed'

    account_id = models.CharField(max_length=50)
    instrument_id = models.CharField(max_length=100)
    
    # Track BOTH direction and lifecycle status
    side = models.CharField(max_length=5, choices=Side.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    avg_price = models.DecimalField(max_digits=18, decimal_places=6)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=4, default=0.0)
    unrealized_pnl = models.DecimalField(max_digits=18, decimal_places=4, default=0.0)
    
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.account_id} - {self.instrument_id}"



class Strategy(models.Model, GetContentsMixin):
    """
    Represents a strategy class available in the system.
    """
    # Generate the choices list dynamically
    STRATEGY_CHOICES = discover_strategies()

    name = models.CharField(max_length=100, unique=True, help_text="A unique name for the strategy.")
    class_path = models.CharField(
        choices=STRATEGY_CHOICES,
        max_length=255,
        unique=True,
        help_text="Full Python path to the strategy class (e.g., 'argo.nautilus.strategies.EMACross')."
    )
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    def get_contents(self, generate_self=True, preset=None):
        parts = [
            f"### Strategy: {self.name}",
            f"- Class Path: `{self.class_path}`",
        ]
        if self.description:
            parts.append(f"- Description: {self.description}")

        source_code = self._get_strategy_source()
        if source_code:
            parts.append(f"### Strategy Source Code, Documentation & Optimization Tips:\n```python\n{source_code}\n```")
        else:
            config_summary = self._get_config_summary()
            if config_summary:
                parts.append(config_summary)
        return parts

    def get_source_file_path(self) -> str | None:
        """Returns the file path of the strategy module/class on the filesystem."""
        try:
            import importlib, inspect
            if not self.class_path or "." not in self.class_path:
                return None
            module_path, class_name = self.class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls_obj = getattr(module, class_name, None)
            if cls_obj is not None:
                src_file = inspect.getsourcefile(cls_obj)
                if src_file:
                    return src_file
            return inspect.getsourcefile(module)
        except Exception:
            return None

    def save_strategy_source(self, code: str) -> None:
        """Saves source code to the strategy module file on the filesystem."""
        file_path = self.get_source_file_path()
        if not file_path:
            raise ValueError(f"Could not locate source file for strategy '{self.class_path}'")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

    def _get_strategy_source(self) -> str:
        """Loads the complete source code of the strategy module including optimization tips and docstrings."""
        try:
            file_path = self.get_source_file_path()
            if file_path:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            import importlib, inspect
            module_path, _ = self.class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return inspect.getsource(module)
        except Exception:
            return ""

    def _get_config_summary(self) -> str:
        """Inspects and returns configuration parameter specifications for this strategy."""
        try:
            import inspect
            from .utils import resolve_strategy_classes
            _, config_class = resolve_strategy_classes(self.class_path)
            if not config_class:
                return ""
            doc = inspect.getdoc(config_class) or ""
            fields = []
            if hasattr(config_class, "__annotations__"):
                for name, typ in config_class.__annotations__.items():
                    val = getattr(config_class, name, "<required>")
                    fields.append(f"  - `{name}` ({getattr(typ, '__name__', str(typ))}): default={val}")
            lines = [f"- Config Schema: `{config_class.__name__}`"]
            if fields:
                lines.append("- Parameters:\n" + "\n".join(fields))
            if doc:
                lines.append(f"- Documentation:\n```\n{doc}\n```")
            return "\n".join(lines)
        except Exception:
            return ""


class Portfolio(CloneModelMixin, AfterSaveActionMixin, models.Model, GetContentsMixin, TaskHolder):
    """
    A collection of strategy instances to be run together.
    """
    TASK_TEXT_GENERATE = getattr(settings, 'TASK_TYPE_GENERATE_TEXT', 'generate_text')

    PRESET_SYNC_INSTANCES = "sync_instances"
    PRESET_CREATE_INSTANCES = "create_instances"

    ACTION_CREATE_INSTANCES = f"{TASK_TEXT_GENERATE}-preset-{PRESET_CREATE_INSTANCES}-target-description-schema-instances"
    ACTION_SYNC_INSTANCES = f"{TASK_TEXT_GENERATE}-preset-{PRESET_SYNC_INSTANCES}-target-description-schema-instances"

    ACTION_CHOICES = (
        (ACTION_CREATE_INSTANCES, _("Create instances from description")),
        (ACTION_SYNC_INSTANCES, _("Sync instances")),
    ) + getattr(settings, 'COMMON_TEXT_ACTION_CHOICES', ())

    AGENT_PRESETS = (
        (PRESET_CREATE_INSTANCES, _("Create instances")),
        (PRESET_SYNC_INSTANCES, _("Sync instances")),
    ) + getattr(settings, 'COMMON_TEXT_AGENT_PRESETS', ())

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    instrument_groups = models.ManyToManyField('InstrumentGroup', related_name='portfolios', blank=True)
    is_active = models.BooleanField(default=False, help_text="If active, this portfolio will be run by the trading node.")
    action = models.SlugField(_("action"), max_length=1024, choices=ACTION_CHOICES, null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = _('Portfolio')
        verbose_name_plural = _('Portfolios')
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_contents(self, generate_self=True, preset=None):
        parts = []
        if preset in [self.PRESET_SYNC_INSTANCES, self.PRESET_CREATE_INSTANCES]:
            if self.name:
                parts.append(f"Portfolio Name: {self.name}")
            if self.description:
                parts.append(f"Portfolio Description: {self.description}")

            instances_rel = getattr(self, 'strategy_instances', None)
            if instances_rel is not None:
                instances = instances_rel.select_related('strategy_model').prefetch_related('strategy_instruments__instrument').all()
                inst_lines = []
                for si in instances:
                    instr_names = ", ".join(f"{sinstr.instrument.symbol} ({sinstr.key})" for sinstr in si.strategy_instruments.all() if sinstr.instrument)
                    inst_lines.append(
                        f"- Strategy: {si.strategy_model.name} ({si.strategy_model.class_path}), Instruments: [{instr_names}], Active: {si.is_active}, Params: {si.params}"
                    )
                parts.append(
                    "### Existing Strategy Instances:\n" + ("\n".join(inst_lines) if inst_lines else "None")
                )

            # Provide available registered strategies in the system
            from argo.models import Strategy
            all_strats = Strategy.objects.all()
            if all_strats.exists():
                strat_lines = [
                    f"- Name: '{s.name}' | Class: '{s.class_path}' | Description: {s.description or 'N/A'}"
                    for s in all_strats
                ]
                parts.append("### Available Registered Strategies in System:\n" + "\n".join(strat_lines))
        else:
            parts = super().get_contents(generate_self=generate_self, preset=preset)

        groups = self.instrument_groups.all()
        if groups.exists():
            group_lines = [
                f"- Group: {g.name} ({g.code}), Symbols: {g.symbols}\n  Description: {g.description or 'No description'}"
                for g in groups
            ]
            parts.append("### Associated Instrument Groups:\n" + "\n".join(group_lines))

        return parts

    def _prepare_clone_fields(self, clone_obj, **kwargs):
        """Prepares default description, resets active status, and adjusts fields prior to saving."""
        super()._prepare_clone_fields(clone_obj, **kwargs)
        if 'is_active' not in kwargs:
            clone_obj.is_active = False

    @classmethod
    def sync_from_node(cls, node):
        """
        Synchronizes the state of a Nautilus TradingNode to the database.

        This function creates or updates a Portfolio and its StrategyInstances
        based on the strategies running in the provided node.

        Args:
            node: An instance of nautilus_trader.live.node.TradingNode.
        """
        portfolio_name = node.config.trader_id
        portfolio, created = cls.objects.update_or_create(
            name=portfolio_name,
            defaults={'description': f"Portfolio synced from node '{portfolio_name}'."}
        )
        if created:
            print(f"Created portfolio '{portfolio_name}' from trading node.")
        else:
            print(f"Syncing portfolio '{portfolio_name}' from trading node.")

        # Get the class paths of all strategies currently running on the node
        running_strategy_paths = {
            f"{s.__class__.__module__}.{s.__class__.__name__}" for s in node.strategies
        }

        # Deactivate any instances in the DB that are no longer running on the node
        if hasattr(portfolio, 'strategy_instances'):
            deactivated_count, _ = portfolio.strategy_instances.exclude(
                strategy_model__class_path__in=running_strategy_paths
            ).update(is_active=False)

            if deactivated_count > 0:
                print(f"Deactivated {deactivated_count} strategy instance(s) no longer on the node.")

        # Add or update strategy instances from the node
        for strategy in node.strategies:
            class_path = f"{strategy.__class__.__module__}.{strategy.__class__.__name__}"
            strategy_model = Strategy.objects.get(class_path=class_path)
            raw_id = str(strategy.instrument_id)
            parts = raw_id.split(".")
            symbol = parts[0]
            venue = parts[1] if len(parts) > 1 else "SMART"
            instrument, _ = Instrument.objects.get_or_create(
                symbol=symbol,
                venue=venue,
                defaults={'is_active': True}
            )

            instance, _ = StrategyInstance.objects.update_or_create(
                strategy_model=strategy_model,
                defaults={'params': strategy.config, 'is_active': True}
            )
            instance.strategy_instruments.update_or_create(
                instrument=instrument,
                defaults={'key': 'instrument_id'}
            )
        print(f"Synced {len(node.strategies)} strategy instance(s).")
        return portfolio


class StrategyInstance(CloneModelMixin, AfterSaveActionMixin, models.Model, GetContentsMixin, TaskHolder):
    """
    A specific, parameterized instance of a strategy for a given instrument.
    """
    TASK_TEXT_GENERATE = getattr(settings, 'TASK_TYPE_GENERATE_TEXT', 'generate_text')

    PRESET_OPTIMIZE = "optimize"

    ACTION_OPTIMIZE = f"{TASK_TEXT_GENERATE}-preset-{PRESET_OPTIMIZE}-schema-optimize"
    ACTION_INSTANTIATE_STRATEGY = f"{settings.TASK_EXECUTE_FUNC}-func-instantiate_strategy"

    ACTION_CHOICES = (
        (ACTION_OPTIMIZE, _("Optimize Parameters & Instrument")),
        (ACTION_INSTANTIATE_STRATEGY, _("Instantiate Strategy")),
    ) + getattr(settings, 'COMMON_TEXT_ACTION_CHOICES', ())

    ACTIONS_NO_INPUT = (ACTION_INSTANTIATE_STRATEGY,)

    AGENT_PRESETS = (
        (PRESET_OPTIMIZE, _("Optimize")),
    ) + getattr(settings, 'COMMON_TEXT_AGENT_PRESETS', ())

    strategy_model = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name='instances', null=True, blank=True)
    instruments = models.ManyToManyField(
        'Instrument',
        through='StrategyInstrument',
        related_name='strategy_instances',
        blank=True,
        help_text=_("Instruments associated with this strategy instance.")
    )
    bar_type = models.CharField(max_length=50, null=True, blank=True, choices=BarType.choices, help_text=_("Bar type for historical data (e.g., MIN_1, HOUR_1)."))
    description = models.TextField(blank=True, help_text=_("Description or trading rationale for this instance."))
    params = models.JSONField(default=dict, blank=True, help_text="JSON object of strategy-specific parameters.")
    is_active = models.BooleanField(default=True)
    action = models.SlugField(_("action"), max_length=1024, choices=ACTION_CHOICES, null=True, blank=True)
    history = HistoricalRecords()


    @property
    def instrument(self) -> Optional['Instrument']:
        """Returns the primary instrument configured for this strategy instance."""
        si = self.strategy_instruments.select_related('instrument').first()
        if si and si.instrument:
            return si.instrument
        return self.instruments.first()

    def get_instruments(self) -> list['Instrument']:
        """Returns all distinct instruments configured for this instance."""
        return list(self.instruments.all())

    def get_instruments_as_params(self) -> dict[str, Any]:
        """Returns key -> Instrument or key -> tuple of Instruments if multiple match."""
        grouped: dict[str, list['Instrument']] = {}
        for si in self.strategy_instruments.select_related('instrument'):
            if si.instrument:
                grouped.setdefault(si.key, []).append(si.instrument)
        return {
            key: instrs[0] if len(instrs) == 1 else tuple(instrs)
            for key, instrs in grouped.items()
        }

    def get_instruments_dict(self) -> dict[str, Any]:
        """Returns key -> Instrument or key -> tuple of Instruments mapping for multi-instrument configurations."""
        return self.get_instruments_as_params()

    def _prepare_clone_fields(self, clone_obj, **kwargs):
        """Prepares default description and resets fields prior to saving the clone."""
        super()._prepare_clone_fields(clone_obj, **kwargs)
        if not clone_obj.description and 'description' not in kwargs:
            strat_name = self.strategy_model.name if self.strategy_model else "Strategy"
            clone_obj.description = f"Copy of {strat_name}"

    def _clone_related(self, new_instance, **kwargs):
        """Clones associated StrategyInstrument records to the new strategy instance."""
        super()._clone_related(new_instance, **kwargs)
        model_cls = self.strategy_instruments.model
        instruments = [
            model_cls(
                strategy_instance=new_instance,
                instrument=si.instrument,
                key=si.key,
                bar_type=si.bar_type,
            )
            for si in self.strategy_instruments.all()
        ]
        if instruments:
            model_cls.objects.bulk_create(instruments)

    def task_from_action(self, action_type, user=None, message=None):
        """Creates a background Task corresponding to the specified action."""
        if action_type in (self.ACTION_INSTANTIATE_STRATEGY, "instantiate_strategy"):
            from task.models import Task
            return Task.createTaskIfQueueEnabled(
                subject=self,
                task_type=settings.TASK_EXECUTE_FUNC,
                payload={'func': 'instantiate_strategy'},
                owner=user,
            )
        return super().task_from_action(action_type, user=user, message=message)

    def instantiate_strategy(
        self,
        params_override: dict | None = None,
        bar_type: str | None = None,
    ):
        """
        Instantiates and returns the NautilusStrategy for this StrategyInstance.
        Injects configured StrategyInstruments with their respective keys into the configuration.
        Throws an exception if the strategy or configuration cannot be instantiated.
        """
        if not self.strategy_model or not self.strategy_model.class_path:
            raise ValueError(f"StrategyInstance #{self.pk} has no Strategy or class_path configured.")

        import inspect
        from .utils import resolve_strategy_classes

        strategy_class, config_class = resolve_strategy_classes(self.strategy_model.class_path)
        target = config_class or strategy_class.__init__

        sig = inspect.signature(target)
        valid_params = set(sig.parameters.keys())
        if inspect.isclass(target) and hasattr(target, "__dataclass_fields__"):
            valid_params |= set(target.__dataclass_fields__.keys())

        has_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        type_hints = getattr(target, "__annotations__", {})

        # Start with instance params merged with overrides
        merged_params = dict(self.params or {})
        if params_override:
            merged_params.update(params_override)

        # Inject StrategyInstruments with their keys ONLY if expected by target
        key_instruments: dict[str, list[str]] = {}
        for si in self.strategy_instruments.select_related('instrument'):
            if si.instrument:
                key_instruments.setdefault(si.key, []).append(si.instrument.instrument_id_str)

        for key, instr_ids in key_instruments.items():
            if key in valid_params or has_var_kwargs:
                expected = str(type_hints.get(key, "")).lower()
                if len(instr_ids) == 1 and not any(t in expected for t in ["list", "tuple", "sequence"]):
                    merged_params.setdefault(key, instr_ids[0])
                elif "tuple" in expected:
                    merged_params.setdefault(key, tuple(instr_ids))
                else:
                    merged_params.setdefault(key, instr_ids)

        instruments = self.get_instruments()
        # Fallback for primary instrument ONLY if target explicitly expects instrument_id
        if "instrument_id" in valid_params and "instrument_id" not in merged_params and instruments:
            merged_params["instrument_id"] = instruments[0].instrument_id_str

        # Fallback for plural instrument_ids ONLY if target explicitly expects it
        if "instrument_ids" in valid_params and "instrument_ids" not in merged_params and instruments:
            expected = str(type_hints.get("instrument_ids", "")).lower()
            ids = [i.instrument_id_str for i in instruments]
            merged_params["instrument_ids"] = tuple(ids) if "tuple" in expected else ids

        # Supply bar_type ONLY if target explicitly expects it
        if "bar_type" in valid_params:
            target_bar = merged_params.get("bar_type") or bar_type
            if target_bar is not None:
                expected_type = str(type_hints.get("bar_type", ""))
                if "BarType" in expected_type:
                    from nautilus_trader.model.data import BarType
                    merged_params["bar_type"] = target_bar if isinstance(target_bar, BarType) else BarType.from_str(str(target_bar))
                else:
                    merged_params["bar_type"] = str(target_bar)

        # Filter kwargs to strictly what target accepts
        filtered_kwargs = {}
        for k, v in merged_params.items():
            if k in ["actor_path", "config_path", "config"]:
                continue
            if k in valid_params or has_var_kwargs:
                filtered_kwargs[k] = v

        if config_class:
            config = config_class(**filtered_kwargs)
            strat_sig = inspect.signature(strategy_class.__init__)
            if "config" in strat_sig.parameters:
                return strategy_class(config=config)
            return strategy_class(config)

        return strategy_class(**filtered_kwargs)

    def __str__(self):
        strat_name = self.strategy_model.name if self.strategy_model else "Unassigned Strategy"
        if not self.pk:
            return strat_name
        instruments = list(self.instruments.all()[:3])
        if instruments:
            symbols = ", ".join(i.symbol for i in instruments)
            return f"{strat_name} ({symbols})"
        return f"{strat_name} (#{self.id})"

    def get_contents(self, generate_self=True, preset=None):
        parts = []
        if self.description:
            parts.append(f"### Trading Objective / Description:\n{self.description}")

        portfolio = getattr(self, 'portfolio', None)
        if portfolio:
            parts.append(f"### Portfolio: {portfolio.name}")
            if portfolio.description:
                parts.append(f"Portfolio Description: {portfolio.description}")
            groups = portfolio.instrument_groups.all()
            if groups.exists():
                group_lines = [f"- Group '{g.name}' ({g.code}): {g.symbols}" for g in groups]
                parts.append("### Available Instrument Groups:\n" + "\n".join(group_lines))

        instruments_list = list(self.strategy_instruments.select_related('instrument'))
        if instruments_list:
            instr_lines = [f"- {si.key}: {si.instrument.symbol} [{si.bar_type}] ({si.instrument.venue}, {si.instrument.asset_class}, {si.instrument.currency})" for si in instruments_list if si.instrument]
            parts.append("### Target Instruments:\n" + "\n".join(instr_lines))

        if self.params:
            import json
            parts.append(f"### Current Configured Parameters:\n```json\n{json.dumps(self.params, indent=2)}\n```")

        # If the strategy is set, pass only that strategy; otherwise pass all strategies via get_contents()
        if self.strategy_model:
            parts.append("### Assigned Strategy Details:")
            strat_parts = self.strategy_model.get_contents(generate_self=generate_self, preset=preset)
            parts.extend(strat_parts if isinstance(strat_parts, list) else [str(strat_parts)])
        else:
            from argo.models import Strategy
            all_strats = Strategy.objects.all()
            parts.append("### All Available Strategies in System:")
            for s in all_strats:
                strat_parts = s.get_contents(generate_self=generate_self, preset=preset)
                parts.extend(strat_parts if isinstance(strat_parts, list) else [str(strat_parts)])

        return parts


class StrategyInstrument(models.Model):
    """
    Connects a StrategyInstance to an Instrument, allowing multi-instrument strategies.
    Identified by a key string defaulting to 'instrument_id'.
    """
 
    strategy_instance = models.ForeignKey(
        StrategyInstance,
        on_delete=models.CASCADE,
        related_name='strategy_instruments',
        help_text=_("The strategy instance.")
    )
    instrument = models.ForeignKey(
        'Instrument',
        on_delete=models.CASCADE,
        related_name='strategy_instruments',
        help_text=_("The connected instrument.")
    )
    key = models.CharField(
        max_length=64,
        default="instrument_id",
        help_text=_("Identifier or role key for the instrument within the strategy, e.g. 'instrument_id'.")
    )
    bar_type = models.CharField(
        max_length=32,
        choices=BarType.choices,
        null=True,
        blank=True,
        help_text=_("Bar aggregation timeframe choice (defaults to 1-MINUTE).")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Strategy Instrument')
        verbose_name_plural = _('Strategy Instruments')
        unique_together = ('strategy_instance', 'instrument', 'key')
        ordering = ['strategy_instance', 'key']

    def __str__(self):
        return f"{self.strategy_instance} - {self.key}: {self.instrument} [{self.bar_type}]"

    @property
    def nautilus_bar_spec(self) -> str:
        """Builds the Nautilus BarSpecification string (e.g. '1-MINUTE-LAST')."""
        return self.bar_type

    @property
    def nautilus_bar_type(self):
        """Builds a native Nautilus BarType identifier or object."""
        return Instrument.get_nautilus_bar_type(self.instrument, self.bar_type)




class HistoricalData(AfterSaveActionMixin, models.Model, GetContentsMixin, TaskHolder):
    """
    Persisted historical bar dataset for an Instrument and BarType.
    Stored exclusively in Parquet format within instrument-specific folders in HISTORICAL_ROOT.
    """
    ACTION_SYNC_DATA = f"{settings.TASK_EXECUTE_FUNC}-func-sync_data"

    ACTION_CHOICES = (
        (ACTION_SYNC_DATA, _("Sync Historical Data")),
    )

    instrument = models.ForeignKey(
        'Instrument',
        on_delete=models.CASCADE,
        related_name='historical_datasets',
        help_text=_("The instrument this data series belongs to.")
    )
    bar_type = models.CharField(
        max_length=32,
        choices=BarType.choices,
        default=BarType.MIN_1,
        help_text=_("Bar aggregation timeframe choice.")
    )
    start_date = models.DateTimeField(help_text=_("Start timestamp of the dataset."))
    end_date = models.DateTimeField(help_text=_("End timestamp of the dataset."))
    bar_count = models.PositiveIntegerField(default=0, help_text=_("Total number of bars in this dataset."))
    catalog_path = models.CharField(
        _("catalog path"),
        max_length=512,
        blank=True,
        help_text=_("Filesystem path of the Parquet file (.parquet) for this dataset.")
    )
    summary = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Key summary statistics (open, high, low, close, volume).")
    )
    action = models.SlugField(
        _("action"),
        max_length=1024,
        choices=ACTION_CHOICES,
        null=True,
        blank=True,
        help_text=_("Trigger a background action task upon save.")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Historical Data')
        verbose_name_plural = _('Historical Data')
        ordering = ['-end_date']
        indexes = [
            models.Index(fields=['instrument', 'bar_type', 'start_date', 'end_date']),
        ]

    def __str__(self):
        s_date = self.start_date.strftime('%Y-%m-%d') if self.start_date else '?'
        e_date = self.end_date.strftime('%Y-%m-%d') if self.end_date else '?'
        return f"{self.instrument.symbol} [{self.bar_type}] ({s_date} to {e_date}): {self.bar_count:,} bars"

    def get_contents(self, generate_self=True, preset=None):
        return [
            f"Historical Dataset: {self.instrument.symbol} [{self.bar_type}]",
            f"Range: {self.start_date} to {self.end_date}",
            f"Bars: {self.bar_count:,}",
            f"Catalog: {self.catalog_path}",
            f"Storage: Parquet",
        ]

    @property
    def nautilus_bar_spec(self) -> str:
        """Returns the Nautilus BarSpecification string, e.g. '5-MINUTE-LAST'."""
        return self.instrument.get_nautilus_bar_spec(self.bar_type)

    @property
    def nautilus_bar_type(self) -> str:
        """Builds the full Nautilus BarType identifier from instrument and bar_type choice."""
        return self.instrument.get_nautilus_bar_type(self.bar_type)


    def get_instrument_dir(self) -> Path:
        """Returns the instrument-specific folder inside settings.HISTORICAL_ROOT."""
        if self.catalog_path:
            p = Path(self.catalog_path)
            target = p.parent if str(p).endswith('.parquet') else p
            target.mkdir(parents=True, exist_ok=True)
            return target
        from django.conf import settings
        historical_root = getattr(settings, "HISTORICAL_ROOT", None) or os.path.join(settings.BASE_DIR, "historical_data")
        instr_folder = self.instrument.instrument_id_str.replace("/", "_")
        target_dir = Path(historical_root) / instr_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir

    def check_coverage(
        self,
        tolerance_days: int = 4,
    ) -> list:
        start_ns = dt_to_unix_nanos(self.start_date)
        end_ns = dt_to_unix_nanos(self.end_date)
        catalog = ParquetDataCatalog(settings.HISTORICAL_ROOT)
        bar_type = self.nautilus_bar_type
        missing = catalog.get_missing_intervals_for_request(
            start=start_ns,
            end=end_ns,
            data_cls=Bar,
            identifier=bar_type
        )
        intervals = []
        is_crypto = getattr(self.instrument, "sec_type", "") == "CRYPTO"
        empty = load_empty_intervals(settings.HISTORICAL_ROOT, bar_type)
        for s_ns, e_ns in missing:
            if s_ns < e_ns:
                s_dt = unix_nanos_to_dt(s_ns)
                e_dt = unix_nanos_to_dt(e_ns)
                # Skip verified empty intervals from catalog JSON
                if is_interval_empty(s_dt, e_dt, empty):
                    continue
                # Skip expected weekend and holiday market closures
                if not is_crypto and is_market_closure_gap(s_dt, e_dt, tolerance_days):
                    continue
                intervals.append((s_dt, e_dt))
        return intervals
    
    def is_covered(
        self,
    ) -> bool:
        """Checks if this dataset is healthy and covers the requested time range."""
        return len(self.check_coverage()) == 0

    def health_check(self):
        """Runs integrity and alignment health check against the on-disk Parquet file."""
        return self.is_covered()
    
    def sync_data(self) -> "HistoricalData":
        """
        Synchronizes this HistoricalData model with the Parquet catalog on disk.
        Completes and extends the parquet file if incomplete for the requested range.
        Throws a ConnectionError if Interactive Brokers is offline or fails to return data.
        """
        downloader = IBDownloader() 
        for itervals in self.check_coverage():
            start_dt, end_dt = itervals
            downloader.download(
                instrument=self.instrument,
                start=start_dt,
                end=end_dt,
                bar_spec=self.nautilus_bar_spec,
            )
        return self

class Backtest(CloneModelMixin, AfterSaveActionMixin, models.Model, GetContentsMixin, TaskHolder):
    """
    Represents an isolated backtesting or parameter optimization experiment 
    for a StrategyInstance.
    """
    TASK_RUN_BACKTEST = "run_backtest"
    TASK_RUN_OPTIMIZATION = "run_optimization"
    TASK_LOAD_DATA = "load_data"

    ACTION_RUN_BACKTEST = TASK_RUN_BACKTEST
    ACTION_RUN_OPTIMIZATION = TASK_RUN_OPTIMIZATION
    ACTION_LOAD_DATA = f"{settings.TASK_EXECUTE_FUNC}-func-load_data"

    ACTION_CHOICES = (
        (ACTION_LOAD_DATA, _("Load Historical Data")),
        (ACTION_RUN_BACKTEST, _("Run Backtest")),
        (ACTION_RUN_OPTIMIZATION, _("Run Parameter Optimization")),
    ) + getattr(settings, 'COMMON_TEXT_ACTION_CHOICES', ())

    ACTIONS_NO_INPUT = (ACTION_LOAD_DATA, ACTION_RUN_BACKTEST)

    AGENT_PRESETS = (
        (TASK_LOAD_DATA, _("Load Data")),
        (TASK_RUN_BACKTEST, _("Backtest")),
        (TASK_RUN_OPTIMIZATION, _("Optimization")),
    ) + getattr(settings, 'COMMON_TEXT_AGENT_PRESETS', ())

    strategy_instance = models.ForeignKey(
        StrategyInstance,
        on_delete=models.CASCADE,
        related_name='backtests',
        help_text=_("The StrategyInstance being evaluated.")
    )

    name = models.CharField(max_length=150, blank=True, help_text=_("Experiment name (e.g. '2024 Macro Trend Run')."))
    start_date = models.DateField(help_text=_("Backtest start timestamp."))
    end_date = models.DateField(help_text=_("Backtest end timestamp."))
    initial_capital = models.DecimalField(max_digits=18, decimal_places=2, default=100000.0)
    commission_rate = models.FloatField(default=0.0001, help_text=_("Simulated broker commission percentage."))

    params_override = models.JSONField(default=dict, blank=True, help_text=_("Specific parameters override for single backtest."))
    param_grid = models.JSONField(default=dict, blank=True, help_text=_("Parameter ranges for optimization sweep."))
    optimization_objective = models.CharField(
        max_length=50,
        default="sharpe",
        choices=[
            ("sharpe", _("Sharpe Ratio")),
            ("calmar", _("Calmar Ratio")),
            ("profit_factor", _("Profit Factor")),
            ("pnl", _("Total PnL")),
        ]
    )

    total_pnl = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    return_pct = models.FloatField(null=True, blank=True)
    sharpe_ratio = models.FloatField(null=True, blank=True)
    sortino_ratio = models.FloatField(null=True, blank=True)
    calmar_ratio = models.FloatField(null=True, blank=True)
    max_drawdown_pct = models.FloatField(null=True, blank=True)
    profit_factor = models.FloatField(null=True, blank=True)
    win_rate = models.FloatField(null=True, blank=True)
    total_trades = models.IntegerField(null=True, blank=True)

    best_params = models.JSONField(default=dict, blank=True, help_text=_("Optimal parameters from sweep."))
    leaderboard = models.JSONField(default=list, blank=True, help_text=_("Ranked leaderboard of parameter combinations."))

    action = models.SlugField(_("action"), max_length=1024, choices=ACTION_CHOICES, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Backtest')
        verbose_name_plural = _('Backtests')
        ordering = ['-created_at']

    def __str__(self):
        label = self.name or f"Backtest #{self.id}"
        return f"{label} ({self.strategy_instance})"

    def _prepare_clone_fields(self, clone_obj, **kwargs):
        """Prepares fields for cloned backtest, clearing execution results and updating experiment name."""
        super()._prepare_clone_fields(clone_obj, **kwargs)
        if not clone_obj.name and 'name' not in kwargs:
            strat_label = str(self.strategy_instance) if self.strategy_instance else "Backtest"
            clone_obj.name = f"Copy of {strat_label}"

        metric_fields = (
            'total_pnl',
            'return_pct',
            'sharpe_ratio',
            'sortino_ratio',
            'calmar_ratio',
            'max_drawdown_pct',
            'profit_factor',
            'win_rate',
            'total_trades',
        )
        for field in metric_fields:
            if field not in kwargs:
                setattr(clone_obj, field, None)

        if 'best_params' not in kwargs:
            clone_obj.best_params = {}
        if 'leaderboard' not in kwargs:
            clone_obj.leaderboard = []

    def get_instruments(self):
        return self.strategy_instance.get_instruments()

    def _resolve_bar_type_for_instrument(self, instr) -> str:
        """Resolves the appropriate bar_type for an instrument within this backtest."""
        si = self.strategy_instance.strategy_instruments.filter(instrument=instr).first() if self.strategy_instance else None
        return (si.bar_type if si and si.bar_type else None) or (self.strategy_instance.bar_type if self.strategy_instance else None) or BarType.MIN_5

    def is_covered(self) -> bool:
        for instr in self.get_instruments():
            bar_type = self._resolve_bar_type_for_instrument(instr)
            hd = HistoricalData.objects.filter(
                instrument=instr,
                bar_type=bar_type,
                start_date__lte=self.start_date,
                end_date__gte=self.end_date,
            ).first()
            if not hd or not hd.is_covered():
                return False
        return True

    def check_coverage(self) -> list:
        missing_intervals = []
        for instr in self.get_instruments():
            bar_type = self._resolve_bar_type_for_instrument(instr)
            hd = HistoricalData.objects.filter(
                instrument=instr,
                bar_type=bar_type,
                start_date__lte=self.start_date,
                end_date__gte=self.end_date,
            ).first()
            if not hd or not hd.is_covered():
                missing_intervals.append(hd.check_coverage())
        return missing_intervals
    
    def load_data(self):
        for instr in self.get_instruments():
            bar_type = self._resolve_bar_type_for_instrument(instr)
            hd = HistoricalData.objects.filter(
                instrument=instr,
                bar_type=bar_type,
                start_date__lte=self.start_date,
                end_date__gte=self.end_date,
            ).first()
            if not hd:
                hd = HistoricalData.objects.create(
                    instrument=instr,
                    bar_type=bar_type,
                    start_date=self.start_date,
                    end_date=self.end_date,
                )
            if not hd.is_covered():
                hd.sync_data()
    

    def sync_data(self, *args, **kwargs):
        """Alias for load_data."""
        return self.load_data(*args, **kwargs)

    def apply_best_params_to_instance(self):
        """Promotes the winning parameters back to the parent StrategyInstance."""
        if self.best_params and self.strategy_instance:
            self.strategy_instance.params = {**(self.strategy_instance.params or {}), **self.best_params}
            self.strategy_instance.save(update_fields=['params'])


class BacktestRun(GetContentsMixin, models.Model):
    """
    Historical execution record of a single backtest run.
    Stores the exact strategy configuration used, a frozen snapshot of the strategy code,
    the complete runtime log, and the interactive HTML tearsheet generated by Nautilus.
    """
    backtest = models.ForeignKey(
        'Backtest',
        on_delete=models.CASCADE,
        related_name='runs',
        null=True,
        blank=True,
        help_text=_("Parent backtest session if initiated from a Backtest entity.")
    )
    strategy_instance = models.ForeignKey(
        'StrategyInstance',
        on_delete=models.CASCADE,
        related_name='backtest_runs',
        null=True,
        blank=True,
        help_text=_("Strategy instance executed.")
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Final configuration parameters used for the backtest execution.")
    )
    code = models.TextField(
        blank=True,
        help_text=_("Frozen snapshot of strategy source code at execution time.")
    )
    log = models.TextField(
        blank=True,
        help_text=_("Execution and simulation logs.")
    )
    html_report = models.TextField(
        blank=True,
        help_text=_("Interactive HTML tearsheet report generated by Nautilus Trader.")
    )

    # Core performance metrics
    total_pnl = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    return_pct = models.FloatField(null=True, blank=True)
    sharpe_ratio = models.FloatField(null=True, blank=True)
    sortino_ratio = models.FloatField(null=True, blank=True)
    calmar_ratio = models.FloatField(null=True, blank=True)
    max_drawdown_pct = models.FloatField(null=True, blank=True)
    profit_factor = models.FloatField(null=True, blank=True)
    win_rate = models.FloatField(null=True, blank=True)
    total_trades = models.IntegerField(null=True, blank=True)

    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _('Backtest Run')
        verbose_name_plural = _('Backtest Runs')

    def __str__(self):
        strat = self.strategy_instance or (self.backtest.strategy_instance if self.backtest else "Run")
        return f"Run #{self.id} for {strat} ({self.created_at:%Y-%m-%d %H:%M})"

    def get_contents(self, generate_self=True, preset=None):
        parts = [
            f"### Backtest Run #{self.id}",
            f"- Strategy Instance: {self.strategy_instance}",
            f"- Backtest: {self.backtest}",
            f"- Period: {self.start_date} to {self.end_date}",
        ]
        if self.total_pnl is not None:
            parts.append(
                f"### Performance Metrics:\n"
                f"- PnL: ${self.total_pnl:,.2f} ({self.return_pct:.2%})\n"
                f"- Sharpe Ratio: {self.sharpe_ratio:.2f} | Sortino: {self.sortino_ratio:.2f} | Calmar: {self.calmar_ratio:.2f}\n"
                f"- Max Drawdown: {self.max_drawdown_pct:.2%} | Win Rate: {self.win_rate:.1%}\n"
                f"- Total Trades: {self.total_trades}"
            )
        return parts


BackTestRun = BacktestRun



# =============================================================================
# ALPHA SCANNER, SIGNAL, AND RECOMMENDATION MODELS
# =============================================================================

class Scanner(models.Model):
    """
    A configurable scanner to find trading opportunities (alpha).
    This is a template for a type of scan (e.g., "Volume Spike Scanner").
    """
    name = models.CharField(max_length=100, unique=True)
    scanner_class_path = models.CharField(
        max_length=255,
        unique=True,
        help_text="Full Python path to the scanner class (e.g., 'argo.scanners.volatility.VolatilityScanner')."
    )
    description = models.TextField(blank=True)
    # Default parameters that instances of this scanner might use
    default_params = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.name


class Signal(models.Model):
    """
    Represents a potential trading opportunity identified by a Scanner.
    """
    class SignalType(models.TextChoices):
        BULLISH = 'BULLISH', _('Bullish')
        BEARISH = 'BEARISH', _('Bearish')
        NEUTRAL = 'NEUTRAL', _('Neutral')

    class SignalStatus(models.TextChoices):
        NEW = 'NEW', _('New')
        VIEWED = 'VIEWED', _('Viewed')
        ACTIONED = 'ACTIONED', _('Actioned')
        DISMISSED = 'DISMISSED', _('Dismissed')

    scanner = models.ForeignKey(Scanner, on_delete=models.CASCADE, related_name='signals')
    instrument_id = models.CharField(max_length=100)
    signal_type = models.CharField(max_length=10, choices=SignalType.choices)
    status = models.CharField(max_length=10, choices=SignalStatus.choices, default=SignalStatus.NEW)
    confidence = models.FloatField(help_text="Confidence score from 0.0 to 1.0.", null=True, blank=True)
    details = models.JSONField(default=dict, blank=True, help_text="Scanner-specific data, e.g., indicator values.")
    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.signal_type} signal for {self.instrument_id} from {self.scanner.name}"

    class Meta:
        ordering = ['-generated_at']


class Recommendation(models.Model):
    """
    A concrete recommendation to act on a Signal, suggesting a specific
    strategy and its configuration.
    """
    class RecommendationStatus(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        ACCEPTED = 'ACCEPTED', _('Accepted')
        REJECTED = 'REJECTED', _('Rejected')

    signal = models.OneToOneField(Signal, on_delete=models.CASCADE, related_name='recommendation')
    recommended_strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE)
    recommended_params = models.JSONField(
        default=dict,
        help_text="Suggested parameters for the strategy instance (e.g., stop loss, take profit)."
    )
    justification = models.TextField(blank=True, help_text="Why this strategy is recommended for this signal.")
    status = models.CharField(max_length=10, choices=RecommendationStatus.choices, default=RecommendationStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Recommend {self.recommended_strategy.name} for {self.signal.instrument_id}"

    def accept(self, portfolio=None):
        """Creates and activates a StrategyInstance based on this recommendation."""
        parts = self.signal.instrument_id.split(".")
        symbol = parts[0]
        venue = parts[1] if len(parts) > 1 else "SMART"
        instrument, _ = Instrument.objects.get_or_create(
            symbol=symbol,
            venue=venue,
            defaults={'is_active': True}
        )
        instance, created = StrategyInstance.objects.update_or_create(
            strategy_model=self.recommended_strategy,
            defaults={
                'params': self.recommended_params,
                'is_active': True,
            }
        )
        StrategyInstrument.objects.update_or_create(
            strategy_instance=instance,
            instrument=instrument,
            defaults={'key': 'instrument_id'}
        )
        self.status = self.RecommendationStatus.ACCEPTED
        self.save()
        return instance


# =============================================================================
# INSTRUMENT AND BROKER CONTRACT MODELS
# =============================================================================

class AssetClass(models.TextChoices):
    EQUITY = 'EQUITY', _('Equity')
    FUTURE = 'FUTURE', _('Future')
    OPTION = 'OPTION', _('Option')
    FX = 'FX', _('Forex')
    COMMODITY = 'COMMODITY', _('Commodity')
    CRYPTO = 'CRYPTO', _('Crypto')
    INDEX = 'INDEX', _('Index')


class OptionRight(models.TextChoices):
    CALL = 'CALL', _('Call')
    PUT = 'PUT', _('Put')


class InstrumentGroup(AfterSaveActionMixin, models.Model, GetContentsMixin, TaskHolder):
    """
    A collection of instruments grouped for trading universes, scans, or execution.
    """
    TASK_TEXT_GENERATE = getattr(settings, 'TASK_TYPE_GENERATE_TEXT', 'generate_text')

    PRESET_PROMPT_TO_INSTR = "prompt_to_instr"

    ACTION_PROMPT_TO_INSTR = f"{TASK_TEXT_GENERATE}-preset-{PRESET_PROMPT_TO_INSTR}-schema-{settings.SCHEMA_INSTRUMENTS}"
    ACTION_SEARCH_CREATE_INSTRUMENTS =  f"{settings.TASK_EXECUTE_FUNC}-func-create_instruments"
    
    ACTION_CHOICES = (
        (ACTION_PROMPT_TO_INSTR, _("Prompt to Instruments")),
        (ACTION_SEARCH_CREATE_INSTRUMENTS, _("Search & Create Instruments")),
    ) + getattr(settings, 'COMMON_TEXT_ACTION_CHOICES', ())

    ACTIONS_NO_INPUT = (ACTION_PROMPT_TO_INSTR, ACTION_SEARCH_CREATE_INSTRUMENTS)

    AGENT_PRESETS = (
        (PRESET_PROMPT_TO_INSTR, _("Prompt to Instruments")),
    ) + getattr(settings, 'COMMON_TEXT_AGENT_PRESETS', ())

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=50, unique=True, help_text=_("Short identifier for the group (e.g., 'US_TECH', 'FX_MAJORS')."))
    prompt = models.TextField(_("prompt"), blank=True, null=True)
    instruments = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Gateway JSON specifications for instruments (symbol, venue, asset_class, currency).")
    )
    matches = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Gateway JSON unfiltered matches")
    )

    is_active = models.BooleanField(default=True)

    action = models.SlugField(_("action"), max_length=1024, choices=ACTION_CHOICES, null=True, blank=True)
    history = HistoricalRecords()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Instrument Group')
        verbose_name_plural = _('Instrument Groups')
        ordering = ['name']


    def __str__(self):
        return f"{self.name} ({self.code})"

    def get_contents(self, generate_self=True, preset=None):
        parts = []
        parts.append(self.prompt)
        return parts
    
    def is_ib_match(self, match, item: dict) -> bool:
        """Filters Interactive Brokers search matches based on the provided item criteria."""
        contract = match["contract"]
        excluded = ["exchange", "primaryExchange"]
        for key, value in item.items():
            if key not in excluded and key in contract and contract[key].strip() != "" and contract[key].upper() != value.upper():
                return False
        return True

    def create_instruments(self) -> dict:
        """Queries Interactive Brokers for each item in self.instruments and creates/links Instrument and IBContract records."""
        search_service = InteractiveBrokersSearchService()
        all_matches = []
        for item in self.instruments:
            code = (item.get("symbol") or "").strip().upper()
            if code:
                matches = search_service.search(query=code)
                if len(matches) > 0:
                    for match in matches:
                        match = asdict(match)
                        if self.is_ib_match(match, item):
                            Instrument.create_from_ib(candidate=match, group=self)
                        all_matches.append(match)
        self.matches = all_matches
        self.save()

class Instrument(models.Model):
    """
    Generalized financial instrument metadata for backtesting and execution.
    """
    groups = models.ManyToManyField(InstrumentGroup, related_name='linked_instruments', blank=True)
    symbol = models.CharField(max_length=64, db_index=True)
    # IB contract fields
    sec_type = models.CharField(max_length=16, default='STK', help_text="STK, FUT, OPT, CASH, IND, CRYPTO, CFD")
    exchange = models.CharField(max_length=32, default='SMART')
    primary_exchange = models.CharField(max_length=32, default='SMART')
    currency = models.CharField(max_length=8, default='USD')
    payload_ib = models.JSONField(default=dict, blank=True, help_text="Raw Interactive Brokers contract details.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['symbol']

    def __str__(self):
        return f"{self.symbol}.{self.exchange} ({self.sec_type})"

    @property
    def instrument_id_str(self) -> str:
        return f"{self.symbol}.{self.primary_exchange or self.exchange}"


    def get_ib_contract(self):
        primary_exch = self.primary_exchange
        if not primary_exch or primary_exch.upper() == "SMART":
            payload_contract = self.payload_ib.get("contract", {}) if isinstance(self.payload_ib, dict) else {}
            primary_exch = payload_contract.get("primaryExchange", "")
            if primary_exch.upper() == "SMART":
                primary_exch = ""

        con_id = self.payload_ib.get("contract", {}).get("conId", 0) if isinstance(self.payload_ib, dict) else 0

        return NautilusIBContract(
            secType=self.sec_type, 
            symbol=self.symbol, 
            exchange=self.exchange or "SMART", 
            primaryExchange=primary_exch,
            currency=self.currency or "USD",
            conId=con_id or 0,
        )

    def get_nautilus_bar_spec(self, bar_type: str = "1-MINUTE") -> str:
        """Returns the Nautilus BarSpecification string, e.g. '1-MINUTE-LAST' or '1-MINUTE-MID'."""
        spec = str(bar_type).strip()
        if any(pt in spec for pt in ("-LAST", "-MID", "-BID", "-ASK")):
            return spec.split("-EXTERNAL")[0].split("-INTERNAL")[0]
        price_type = "MID" if self.sec_type in ("CASH", "FX") or getattr(self, "asset_class", "") in ("CASH", "FX") else "LAST"
        return f"{spec}-{price_type}"

    def get_nautilus_bar_type(self, bar_type: str = "1-MINUTE") -> str:
        """Returns the full Nautilus BarType string, e.g. 'AAPL.SMART-5-MINUTE-LAST-EXTERNAL'."""
        spec = str(bar_type).strip()
        if "-EXTERNAL" in spec or "-INTERNAL" in spec:
            return spec
        return f"{self.instrument_id_str}-{self.get_nautilus_bar_spec(spec)}-EXTERNAL"
    
    @staticmethod
    def create_from_ib( candidate:dict, group=None):
        instance = Instrument.objects.create()
        instance.payload_ib = candidate
        contract = candidate["contract"]
        for key in contract.keys():
            if hasattr(instance, key):
                setattr(instance, key, contract[key])
        if "primaryExchange" in contract:
            instance.primary_exchange = contract["primaryExchange"]
        if group:
            instance.groups.add(group)
        instance.save()
