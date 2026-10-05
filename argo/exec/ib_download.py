import asyncio
import datetime
from nautilus_trader.adapters.interactive_brokers.common import IBContract
from nautilus_trader.adapters.interactive_brokers.historical.client import HistoricInteractiveBrokersClient
from nautilus_trader.persistence.catalog import ParquetDataCatalog


async def download_historical_data():
    # Initialize client
    client = HistoricInteractiveBrokersClient(
        host="127.0.0.1",
        port=4002,
        client_id=1,
    )

    # Connect
    await client.connect()
    await asyncio.sleep(2)  # Allow connection to stabilize

    # Define contracts
    contracts = [
        IBContract(secType="STK", symbol="AAPL", exchange="SMART", primaryExchange="NASDAQ"),
        IBContract(secType="CASH", symbol="EUR", currency="USD", exchange="IDEALPRO")
    ]

    # Request instruments
    instruments = await client.request_instruments(contracts=contracts)

    

    # Request tick data
    ticks = await client.request_ticks(
        tick_type="TRADES",
        start_date_time=datetime.datetime(2025, 1, 1, 0, 1),
        end_date_time=datetime.datetime(2026, 1, 1, 0, 1),
        tz_name="America/New_York",
        contracts=contracts,
    )

    # Save to catalog
    catalog = ParquetDataCatalog("./catalog")
    catalog.write_data(instruments)
    catalog.write_data(ticks)

    print(f"Downloaded {len(instruments)} instruments")
    print(f"Downloaded {len(ticks)} ticks")


# Run the example
if __name__ == "__main__":
    asyncio.run(download_historical_data())