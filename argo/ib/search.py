import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional
from django.conf import settings
from ib_async import IB



class InteractiveBrokersSearchService:
    """
    Lean service for querying matching contract symbols and details from Interactive Brokers (TWS/Gateway).
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: int = 98,
        timeout: float = 20.0,
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
        exchange: Optional[str] = None,
    ):
        """Asynchronously queries IB Gateway/TWS for matching contracts with complete metadata."""
        ib = IB()
        try:
            await ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=self.timeout,
            )
            return await ib.reqMatchingSymbolsAsync(query)
        finally:
            if ib.isConnected():
                ib.disconnect()

    def search(
        self,
        query: str,
        sec_type: Optional[str] = None,
        currency: Optional[str] = None,
        exchange: Optional[str] = None,
    ):
        """Synchronously executes the search query, handling running event loops safely."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = self.search_async(query, sec_type=sec_type, currency=currency, exchange=exchange)
        if loop and loop.is_running():
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)


