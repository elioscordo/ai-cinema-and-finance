import asyncio
import concurrent.futures
import datetime
import logging
from typing import List, Optional, Tuple
from django.conf import settings
from nautilus_trader.adapters.interactive_brokers.client.client import InteractiveBrokersClient
from nautilus_trader.adapters.interactive_brokers.historical.client import HistoricInteractiveBrokersClient
from nautilus_trader.core.datetime import dt_to_unix_nanos, unix_nanos_to_dt
from nautilus_trader.model.data import Bar
from nautilus_trader.persistence.catalog import ParquetDataCatalog

logger = logging.getLogger("argo.ib_download")

if not hasattr(InteractiveBrokersClient, "stop"):
    InteractiveBrokersClient.stop = InteractiveBrokersClient._stop

if not getattr(InteractiveBrokersClient.process_error, "_is_patched", False):
    _orig_process_error = InteractiveBrokersClient.process_error

    async def _patched_process_error(
        self,
        *,
        req_id: int,
        error_time: int,
        error_code: int,
        error_string: str,
        advanced_order_reject_json: str = "",
    ) -> None:
        if error_code == 326:
            self._client_id_in_use = True
        return await _orig_process_error(
            self,
            req_id=req_id,
            error_time=error_time,
            error_code=error_code,
            error_string=error_string,
            advanced_order_reject_json=advanced_order_reject_json,
        )

    _patched_process_error._is_patched = True
    InteractiveBrokersClient.process_error = _patched_process_error
from argo.utils import (
    is_interval_empty,
    is_market_closure_gap,
    load_empty_intervals,
    record_empty_interval,
)

_GLOBAL_LOG_GUARD = None


def patch_nautilus_historic_client_logging() -> None:
    """Safely wraps HistoricInteractiveBrokersClient logging to prevent Rust panic on re-initialization."""
    import nautilus_trader.adapters.interactive_brokers.historical.client as hist_client

    if getattr(hist_client.init_logging, "_is_safe_patched", False):
        return

    orig_init = hist_client.init_logging

    def safe_init(level_stdout=None):
        global _GLOBAL_LOG_GUARD
        if _GLOBAL_LOG_GUARD is not None:
            return _GLOBAL_LOG_GUARD
        try:
            if level_stdout is not None:
                _GLOBAL_LOG_GUARD = orig_init(level_stdout=level_stdout)
            else:
                _GLOBAL_LOG_GUARD = orig_init()
        except Exception:
            pass
        return _GLOBAL_LOG_GUARD

    safe_init._is_safe_patched = True
    hist_client.init_logging = safe_init


patch_nautilus_historic_client_logging()


def run_async_task(coro):
    """Executes an async coroutine across sync, threadpool, or Celery contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class IBDownloader:
    """Downloads historical bars via Nautilus HistoricInteractiveBrokersClient into Parquet catalog."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: int = 1
    ):
        self.host = host or getattr(settings, "IB_HOST", "127.0.0.1")
        self.port = port or getattr(settings, "IB_PORT", 4002)
        self.client_id = client_id


    @staticmethod
    async def _disconnect(client) -> None:
        if client is None:
            return
        try:
            if hasattr(client, "_data_client") and hasattr(client._data_client, "_disconnect"):
                await client._data_client._disconnect()
            if hasattr(client, "_client"):
                if hasattr(client._client, "_stop_async"):
                    await client._client._stop_async()
                elif hasattr(client._client, "stop"):
                    res = client._client.stop()
                    if asyncio.iscoroutine(res):
                        await res
                if hasattr(client._client, "_eclient") and hasattr(client._client._eclient, "disconnect"):
                    client._client._eclient.disconnect()
            elif hasattr(client, "disconnect"):
                res = client.disconnect()
                if asyncio.iscoroutine(res):
                    await res
            for t in asyncio.all_tasks():
                if t.get_name() == "_start_async" and not t.done():
                    t.cancel()
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _connect_client(self) -> HistoricInteractiveBrokersClient:
        cid = self.client_id
        for _ in range(5):
            client = HistoricInteractiveBrokersClient(host=self.host, port=self.port, client_id=cid)
            connect_task = asyncio.create_task(client.connect())
            try:
                for _ in range(30):
                    if connect_task.done():
                        await connect_task
                        self.client_id = cid
                        return client
                    if getattr(client._client, "_client_id_in_use", False):
                        connect_task.cancel()
                        break
                    await asyncio.sleep(0.2)
                if not connect_task.done():
                    connect_task.cancel()
            except Exception:
                pass
            await self._disconnect(client)
            cid += 1
        raise ConnectionError(f"Failed to connect to Interactive Brokers at {self.host}:{self.port}")

    @staticmethod
    def _to_naive(dt):
        if dt is None:
            return None
        if getattr(dt, "tzinfo", None) is not None:
            return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return dt

    @classmethod
    def get_next_chunk(cls, catalog: ParquetDataCatalog, identifier: str, start, end, days: int = 7):
        """Asks for remaining catalog gaps, skipping verified empty intervals and weekend closures."""
        missing = catalog.get_missing_intervals_for_request(
            dt_to_unix_nanos(start), dt_to_unix_nanos(end), Bar, identifier
        )
        if not missing:
            return None
        empty = load_empty_intervals(settings.HISTORICAL_ROOT, identifier)
        is_crypto = "CRYPTO" in str(identifier).upper()
        for s_ns, e_ns in missing:
            s = cls._to_naive(unix_nanos_to_dt(s_ns))
            e = cls._to_naive(unix_nanos_to_dt(e_ns))
            if is_interval_empty(s, e, empty):
                continue
            if not is_crypto and is_market_closure_gap(s, e):
                continue
            if not is_crypto:
                if s.weekday() == 5:
                    s = (s + datetime.timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
                elif s.weekday() == 6:
                    s = (s + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            if s >= e:
                continue
            return s, min(s + datetime.timedelta(days=days), e)
        return None

    @classmethod
    async def _fetch_and_record_chunk(
        cls,
        client: HistoricInteractiveBrokersClient,
        catalog: ParquetDataCatalog,
        bar_type: str,
        bar_spec: str,
        instrument,
        c_start: datetime.datetime,
        c_end: datetime.datetime,
        use_rth: bool,
    ) -> list:
        bars = await client.request_bars(
            bar_specifications=[bar_spec],
            start_date_time=c_start,
            end_date_time=c_end,
            tz_name="UTC",
            contracts=[instrument.get_ib_contract()],
            use_rth=use_rth,
        )
        if bars:
            catalog.write_data(bars, skip_disjoint_check=True)
            return bars
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        if c_end < now_utc:
            record_empty_interval(settings.HISTORICAL_ROOT, bar_type, c_start, c_end)
        return []

    async def fetch_bars(
        self,
        instrument,
        start,
        end,
        bar_spec: str,
        use_rth: bool = False,
    ) -> list:
        """Connects to IB, queries remaining intervals in reduced chunks, writes, and repeats."""
        catalog = ParquetDataCatalog(settings.HISTORICAL_ROOT)
        bar_type = instrument.get_nautilus_bar_type(bar_spec) if hasattr(instrument, "get_nautilus_bar_type") else bar_spec
        client = await self._connect_client()
        try:
            catalog.consolidate_data(
                Bar,
                identifier=bar_type,
                start=start,
                end=end,
                ensure_contiguous_files=False,
                deduplicate=True,
            )
        except Exception:
            pass
        try:
            all_bars, cur_start = [], self._to_naive(start)
            target_end = self._to_naive(end)
            while chunk := self.get_next_chunk(catalog, bar_type, cur_start, target_end):
                c_start, c_end = chunk
                if (c_end - c_start).total_seconds() <= 0:
                    break
                bars = await self._fetch_and_record_chunk(
                    client=client,
                    catalog=catalog,
                    bar_type=bar_type,
                    bar_spec=bar_spec,
                    instrument=instrument,
                    c_start=c_start,
                    c_end=c_end,
                    use_rth=use_rth,
                )
                if bars:
                    all_bars.extend(bars)
                    bar_type = str(bars[0].bar_type)
                cur_start = c_end
            if all_bars:
                try:
                    catalog.consolidate_data(
                        Bar,
                        identifier=bar_type,
                        start=start,
                        end=end,
                        ensure_contiguous_files=False,
                        deduplicate=True,
                    )
                except Exception as ex:
                    logger.warning(f"Consolidation failed for {bar_type}: {ex}")
            return all_bars
        finally:
            await self._disconnect(client)
        

    def download(
        self,
        instrument,
        start,
        end,
        bar_spec: str,
        use_rth: bool = False,
    ) -> list:
        """Synchronous entry point to download and persist missing bars."""
        coro = self.fetch_bars(
            instrument=instrument,
            start=start,
            end=end,
            bar_spec=bar_spec,
            use_rth=use_rth,
        )
        return run_async_task(coro) or []
