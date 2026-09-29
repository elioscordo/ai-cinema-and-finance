import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Iterable, List, Optional

from django.conf import settings
from ib_async import IB, ContractDescription

from argo.models import AssetClass


ASSET_CLASS_TO_SEC_TYPE: dict[str, str] = {
    AssetClass.EQUITY: "STK",
    AssetClass.FUTURE: "FUT",
    AssetClass.OPTION: "OPT",
    AssetClass.FX: "CASH",
    AssetClass.CRYPTO: "CRYPTO",
    AssetClass.INDEX: "IND",
    AssetClass.COMMODITY: "CMDTY",
}

SEC_TYPE_TO_ASSET_CLASS: dict[str, str] = {
    "STK": AssetClass.EQUITY,
    "FUT": AssetClass.FUTURE,
    "OPT": AssetClass.OPTION,
    "CASH": AssetClass.FX,
    "CRYPTO": AssetClass.CRYPTO,
    "IND": AssetClass.INDEX,
    "CMDTY": AssetClass.COMMODITY,
}


@dataclass(frozen=True)
class IBSearchResult:
    """Rich contract metadata returned from Interactive Brokers symbol search."""
    con_id: int
    symbol: str
    sec_type: str
    primary_exchange: str
    currency: str
    exchange: str = "SMART"
    local_symbol: str = ""
    trading_class: str = ""
    asset_class: str = AssetClass.EQUITY
    derivative_sec_types: tuple = ()


class IBSearchServiceError(RuntimeError):
    """Raised when Interactive Brokers service is unreachable or encounters an error."""
    pass


class InteractiveBrokersSearchService:
    """
    Lean service for querying matching contract symbols and details from Interactive Brokers (TWS/Gateway).
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: int = 98,
        timeout: float = 10.0,
    ):
        self.host = host or getattr(settings, "IB_HOST", "127.0.0.1")
        self.port = port or getattr(settings, "IB_PORT", 4002)
        self.client_id = client_id
        self.timeout = timeout

    async def search_async(
        self,
        query: str,
        sec_type: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> List[IBSearchResult]:
        """Asynchronously queries IB Gateway/TWS for matching contracts with complete metadata."""
        ib = IB()
        try:
            await ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=self.timeout,
            )
            descriptions = await ib.reqMatchingSymbolsAsync(query)
            return self._extract_results(descriptions or [], sec_type=sec_type, currency=currency)
        except Exception as exc:
            raise IBSearchServiceError(
                f"Interactive Brokers search service failed at {self.host}:{self.port} "
                f"(clientId={self.client_id}): {exc}"
            ) from exc
        finally:
            if ib.isConnected():
                ib.disconnect()

    def search(
        self,
        query: str,
        sec_type: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> List[IBSearchResult]:
        """Synchronously executes the search query, handling running event loops safely."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = self.search_async(query, sec_type=sec_type, currency=currency)
        if loop and loop.is_running():
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)

    def populate_group(self, group, query: str, append: bool = False) -> List[str]:
        """Searches symbols and persists them into the given InstrumentGroup."""
        sec_type = ASSET_CLASS_TO_SEC_TYPE.get(getattr(group, "asset_class", None), None)
        currency = getattr(group, "currency", None)
        results = self.search(query=query, sec_type=sec_type, currency=currency)
        symbols = sorted({r.symbol for r in results})
        if not symbols:
            return []

        existing = set(group.get_codes()) if append else set()
        new_codes = sorted(existing.union(symbols))
        group.instruments = [{"symbol": s, "venue": "SMART", "asset_class": "EQUITY", "currency": "USD"} for s in new_codes]
        group.save(update_fields=["instruments", "updated_at"])
        return symbols

    def _extract_results(
        self,
        descriptions: Iterable[ContractDescription],
        sec_type: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> List[IBSearchResult]:
        """Extracts filtered and normalized contract search results."""
        results = []
        for desc in descriptions:
            c = desc.contract
            if not c.symbol:
                continue
            if sec_type and c.secType != sec_type:
                continue
            if currency and c.currency != currency:
                continue

            results.append(
                IBSearchResult(
                    con_id=c.conId or 0,
                    symbol=c.symbol.upper(),
                    sec_type=c.secType or "STK",
                    primary_exchange=c.primaryExchange or "",
                    currency=c.currency or "USD",
                    exchange=c.exchange or "SMART",
                    local_symbol=c.localSymbol or "",
                    trading_class=c.tradingClass or "",
                    asset_class=SEC_TYPE_TO_ASSET_CLASS.get(c.secType, AssetClass.EQUITY),
                    derivative_sec_types=tuple(desc.derivativeSecTypes or ()),
                )
            )
        return sorted(results, key=lambda r: (r.symbol, r.con_id))


