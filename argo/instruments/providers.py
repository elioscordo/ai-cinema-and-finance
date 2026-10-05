from typing import Iterable, List, Optional, Set, Union
from nautilus_trader.adapters.interactive_brokers.common import IBContract as NautilusIBContract
from nautilus_trader.model.instruments import Instrument as NautilusInstrument
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from argo.models import Instrument, InstrumentGroup


class DjangoInstrumentProvider:
    """
    Service layer providing Nautilus instruments and IB contracts directly from Django DB.
    """

    @classmethod
    def get_instruments(cls, queryset: Optional[Iterable[Instrument]] = None) -> List[NautilusInstrument]:
        """Loads and converts Django instruments into Nautilus domain objects."""
        qs = queryset if queryset is not None else Instrument.objects.filter(is_active=True)
        qs = qs.select_related("ib_contract")
        return [NautilusInstrumentFactory.create(inst) for inst in qs]

    @classmethod
    def get_ib_contracts(cls, queryset: Optional[Iterable[Instrument]] = None) -> List[NautilusIBContract]:
        """Loads and converts Django instruments into Nautilus IBContract configurations."""
        return None
    @classmethod
    def get_ib_contracts_set(cls, queryset: Optional[Iterable[Instrument]] = None) -> frozenset:
        """Returns frozenset of IBContracts ready for InteractiveBrokersInstrumentProviderConfig."""
        return frozenset(cls.get_ib_contracts(queryset))

    @classmethod
    def write_to_catalog(cls, catalog_path: str, queryset: Optional[Iterable[Instrument]] = None) -> int:
        """Persists instruments into ParquetDataCatalog for backtesting."""
        catalog = ParquetDataCatalog(catalog_path)
        instruments = cls.get_instruments(queryset)
        for instrument in instruments:
            catalog.write_data([instrument])
        return len(instruments)

    @classmethod
    def register_with_node(cls, node, queryset: Optional[Iterable[Instrument]] = None) -> int:
        """Registers active instruments with a live Nautilus TradingNode."""
        instruments = cls.get_instruments(queryset)
        for instrument in instruments:
            node.trader.add_instrument(instrument)
        return len(instruments)

    @classmethod
    def get_instruments_by_group(cls, group: Union[str, InstrumentGroup]) -> List[NautilusInstrument]:
        """Loads and converts instruments belonging to a specific group."""
        grp = group if isinstance(group, InstrumentGroup) else InstrumentGroup.objects.get(code=group, is_active=True)
        return cls.get_instruments(grp.instruments.filter(is_active=True))

    @classmethod
    def get_ib_contracts_by_group(cls, group: Union[str, InstrumentGroup]) -> List[NautilusIBContract]:
        """Loads IB contracts for a specific group."""
        grp = group if isinstance(group, InstrumentGroup) else InstrumentGroup.objects.get(code=group, is_active=True)
        return cls.get_ib_contracts(grp.instruments.filter(is_active=True))
