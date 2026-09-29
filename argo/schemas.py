from pydantic import BaseModel, Field
from typing import List, Optional
from agent.schemas import SyncReport, get_asset_sync_info


class InstrumentSchema(BaseModel):
    symbol: str = Field(description="Symbol or ticker, e.g. AAPL, EUR.USD, ES")
    name: Optional[str] = Field(default=None, description="Company or asset name")
    description: Optional[str] = Field(default=None, description="Description")
    asset_class: Optional[str] = Field(default="EQUITY", description="Asset class, e.g. EQUITY, FUTURE, OPTION, FX, COMMODITY, CRYPTO, INDEX")
    venue: Optional[str] = Field(default="SMART", description="Trading venue or exchange, e.g. SMART, NASDAQ, NYSE, CME")
    currency: Optional[str] = Field(default="USD", description="Currency code, e.g. USD, EUR, GBP")
    sec_type: Optional[str] = Field(default=None, description="Security type, e.g. STK, CASH, CRYPTO, FUT")


# Aliases for backwards compatibility
InstrumentItemSchema = InstrumentSchema
SymbolItemSchema = InstrumentSchema


class InstrumentsSchema(BaseModel):
    instruments: List[InstrumentSchema] = Field(default_factory=list, description="List of instruments")
    symbols: Optional[List[InstrumentSchema]] = Field(default=None, description="Optional alias for instruments")

    def model_post_init(self, __context) -> None:
        if not self.instruments and self.symbols:
            self.instruments = self.symbols
        elif not self.symbols and self.instruments:
            self.symbols = self.instruments

    @classmethod
    def from_group(cls, group) -> "InstrumentsSchema":
        return cls(instruments=[
            InstrumentSchema(
                symbol=code,
                asset_class=getattr(group, "asset_class", None),
                venue=getattr(group, "venue", "SMART"),
                currency=getattr(group, "currency", "USD")
            )
            for code in group.get_codes()
        ])

    def sync_db(self, instance) -> dict:
        return self.sync_model(instance)

    def sync_model(self, instance) -> dict:
        items = self.instruments or self.symbols or []
        instance.instruments = [item.model_dump(exclude_none=True) for item in items]
        instance.save()

        if hasattr(instance, "create_instruments"):
            return instance.create_instruments()

        return {
            "saved": len(instance.instruments),
            "instruments": instance.instruments,
        }


# Aliases for backwards compatibility
SymbolsSchema = InstrumentsSchema


class StrategyInstanceItemSchema(BaseModel):
    strategy: str
    symbol: str
    venue: Optional[str] = "SMART"
    asset_class: Optional[str] = None
    currency: Optional[str] = "USD"
    description: Optional[str] = None
    params: Optional[dict] = {}
    is_active: bool = True


class StrategyInstancesSchema(BaseModel):
    instances: List[StrategyInstanceItemSchema]

    def sync_model(self, portfolio) -> dict:
        from django.db.models import Q
        from argo.models import Strategy, Instrument, StrategyInstance, AssetClass
        from argo.instruments.search import InteractiveBrokersSearchService, ASSET_CLASS_TO_SEC_TYPE

        created_reports = []
        existing_reports = []
        skipped_reports = []
        search_service = InteractiveBrokersSearchService()

        for item in self.instances:
            strat_query = item.strategy.strip()
            strategy_obj = Strategy.objects.filter(
                Q(name__iexact=strat_query) | Q(class_path__iexact=strat_query) | Q(name__icontains=strat_query)
            ).first()

            if not strategy_obj:
                skipped_reports.append({
                    'item': f"{item.strategy} @ {item.symbol}",
                    'status': 'skipped',
                    'reason': f"Strategy '{item.strategy}' not found in registered strategies."
                })
                continue

            symbol_code = item.symbol.strip().upper()
            venue = item.venue or "SMART"
            asset_class = item.asset_class or AssetClass.EQUITY
            currency = item.currency or "USD"

            instrument = Instrument.objects.filter(symbol=symbol_code, venue=venue).first()
            if not instrument:
                try:
                    sec_type = ASSET_CLASS_TO_SEC_TYPE.get(asset_class, 'STK')
                    matches = search_service.search(query=symbol_code, sec_type=sec_type, currency=currency)
                    match = next((m for m in matches if m.symbol == symbol_code), None)
                    if match:
                        contract_venue = venue or match.primary_exchange or match.exchange or "SMART"
                        instrument, _ = Instrument.objects.get_or_create(
                            symbol=match.symbol,
                            venue=contract_venue,
                            asset_class=match.asset_class,
                            defaults={'currency': match.currency or currency, 'is_active': True}
                        )
                except Exception:
                    pass

            if not instrument:
                instrument, _ = Instrument.objects.get_or_create(
                    symbol=symbol_code,
                    venue=venue,
                    asset_class=asset_class,
                    defaults={'currency': currency, 'is_active': True}
                )

            instance_obj, created = StrategyInstance.objects.update_or_create(
                strategy_model=strategy_obj,
                defaults={
                    'description': item.description or "",
                    'params': item.params or {},
                    'is_active': item.is_active,
                }
            )
            from argo.models import StrategyInstrument
            StrategyInstrument.objects.update_or_create(
                strategy_instance=instance_obj,
                instrument=instrument,
                defaults={'key': 'instrument_id'}
            )

            report = get_asset_sync_info(instance_obj, created)
            if created:
                created_reports.append(report)
            else:
                existing_reports.append(report)

        return {
            'created': created_reports,
            'existing': existing_reports,
            'skipped': skipped_reports,
            'total_created': len(created_reports),
            'total_skipped': len(skipped_reports),
        }


class StrategyInstanceOptimizeSchema(BaseModel):
    strategy: Optional[str] = Field(None, description="Exact name or class path of the trading strategy.")
    symbol: str = Field(..., description="The instrument symbol code (e.g. 'AAPL', 'EURUSD', 'NVDA', 'SPY').")
    venue: Optional[str] = Field("SMART", description="Exchange / venue (e.g. 'SMART', 'IDEALPRO', 'CME').")
    asset_class: Optional[str] = Field(None, description="Asset class ('EQUITY', 'FX', 'CRYPTO', 'FUTURE', 'OPTION').")
    currency: Optional[str] = Field("USD", description="Currency (e.g. 'USD', 'EUR').")
    description: Optional[str] = Field(None, description="Trading rationale and parameter optimization summary.")
    params: dict = Field(default_factory=dict, description="Dictionary of optimized strategy parameters.")
    is_active: bool = Field(True, description="Whether the instance is active.")

    def sync_model(self, instance) -> dict:
        from django.db.models import Q
        from argo.models import Strategy, Instrument, AssetClass

        if self.strategy:
            strat_query = self.strategy.strip()
            strat_obj = Strategy.objects.filter(
                Q(name__iexact=strat_query) | Q(class_path__iexact=strat_query) | Q(name__icontains=strat_query)
            ).first()
            if strat_obj:
                instance.strategy_model = strat_obj

        symbol_code = self.symbol.strip().upper()
        venue = self.venue or "SMART"
        asset_class = self.asset_class or AssetClass.EQUITY
        currency = self.currency or "USD"

        instrument = self._resolve_instrument(symbol_code, venue, asset_class, currency)
        from argo.models import StrategyInstrument
        StrategyInstrument.objects.update_or_create(
            strategy_instance=instance,
            instrument=instrument,
            defaults={'key': 'instrument_id'}
        )

        # Populate and merge default strategy parameters with optimized params
        defaults = self._get_default_strategy_params(instance.strategy_model)
        merged_params = {**defaults, **(self.params or {})}
        instance.params = merged_params

        if self.description:
            instance.description = self.description
        instance.is_active = self.is_active
        instance.save()

        report = get_asset_sync_info(instance, created=False)
        return {
            'instance_id': instance.id,
            'strategy': str(instance.strategy_model),
            'instrument': str(instance.instrument),
            'params': instance.params,
            'report': report,
        }

    def _get_default_strategy_params(self, strategy_model) -> dict:
        """Extracts default parameters from the strategy Config class."""
        if not strategy_model or not strategy_model.class_path:
            return {}
        try:
            import importlib
            module_path, class_name = strategy_model.class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            config_class = getattr(module, f"{class_name}Config", None)
            if not config_class:
                return {}
            defaults = {}
            if hasattr(config_class, "__annotations__"):
                for field_name in config_class.__annotations__:
                    if field_name not in ["instrument_id", "bar_type"] and hasattr(config_class, field_name):
                        defaults[field_name] = getattr(config_class, field_name)
            return defaults
        except Exception:
            return {}

    def _resolve_instrument(self, symbol_code: str, venue: str, asset_class: str, currency: str):
        from argo.models import Instrument
        from argo.instruments.search import InteractiveBrokersSearchService, ASSET_CLASS_TO_SEC_TYPE

        instrument = Instrument.objects.filter(symbol=symbol_code, venue=venue).first()
        if instrument:
            return instrument

        search_service = InteractiveBrokersSearchService()
        try:
            sec_type = ASSET_CLASS_TO_SEC_TYPE.get(asset_class, 'STK')
            matches = search_service.search(query=symbol_code, sec_type=sec_type, currency=currency)
            match = next((m for m in matches if m.symbol == symbol_code), None)
            if match:
                contract_venue = venue or match.primary_exchange or match.exchange or "SMART"
                instrument, _ = Instrument.objects.get_or_create(
                    symbol=match.symbol,
                    venue=contract_venue,
                    asset_class=match.asset_class or asset_class,
                    defaults={'currency': match.currency or currency, 'is_active': True}
                )
                return instrument
        except Exception:
            pass

        instrument, _ = Instrument.objects.get_or_create(
            symbol=symbol_code,
            venue=venue,
            asset_class=asset_class,
            defaults={'currency': currency, 'is_active': True}
        )
        return instrument