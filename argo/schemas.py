from pydantic import BaseModel, Field
from typing import List, Optional

class InstrumentSchema(BaseModel):
    symbol: str = Field(description="Symbol or ticker, e.g. AAPL, EUR.USD, ES")
    currency: Optional[str] = Field(default="USD", description="Currency code, e.g. USD, EUR, GBP")
    secType: Optional[str] = Field(default=None, description="Security type, e.g. STK, CASH, CRYPTO, FUT")
    exchange: Optional[str] = Field(default=None, description="Exchange or venue, e.g. SMART, IDEALPRO, CME")
    primaryExchange: Optional[str] = Field(default=None, description="Primary exchange, e.g. NASDAQ, NYSE, CME")    

class InstrumentsSchema(BaseModel):
    instruments: List[InstrumentSchema] = Field(default_factory=list, description="List of instruments")
    
    def sync_model(self, instance) -> dict:
        items = self.instruments or self.symbols or []
        instance.instruments = [item.model_dump(exclude_none=True) for item in items]
        instance.save()
        return instance.instruments

