#!/usr/bin/env python3
"""
Bot — Strategia "Dashboard v2" (XLK/SMH, ORB + stop ATR14)
============================================================
Implementazione DIRETTA delle regole attuali del Dashboard v2, senza alcuna
opzione configurabile: i parametri sono gli stessi default pubblicati nella
chat, scritti qui come costanti. Per cambiarli, modifica la sezione CONFIG.

REGOLE (identiche al dashboard, in ordine di applicazione)
------------------------------------------------------------
1. Universo: XLK (10 titoli) e SMH (10 titoli). Si opera SOLO il settore
   piu' forte dei due quel giorno (non "entrambi").
2. Alle 9:35 NY: il settore scelto deve avere ritorno > 0% rispetto alla
   chiusura di ieri. Se nessuno dei due e' positivo, non si opera oggi.
3. Alle 9:40 NY: si classificano i titoli del settore scelto con momentum
   positivo (fino a 8 candidati), ordinati per forza; si prendono i primi 3
   (K=3, ordine="forza").
4. Finestra d'ingresso: 9:45-10:15 NY. Trigger = chiusura di una candela 5m
   del titolo sopra il massimo della SUA prima candela (9:30-9:35, l'ORB).
5. Filtro di ampiezza (nlead): al momento della rottura di un candidato,
   almeno 2 dei candidati del punto 3 devono aver gia' rotto il proprio ORB
   (incluso se stesso), contando SOLO le rotture avvenute fino a quella
   barra (nessun lookahead). Altrimenti il segnale e' scartato.
6. Scenario indici: stato di SPY e QQQ rispetto al loro ORB a 10 minuti
   (barre 9:30-9:40), alla barra della rottura:
     A: entrambi sopra il loro ORB        -> rischio 4% del capitale
     B: solo uno dei due sopra            -> rischio 2% del capitale
     D: entrambi dentro il proprio range  -> rischio 2% del capitale
     C: nessuno sopra (almeno uno sotto)  -> NON operare (strategia long-only)
7. Stop iniziale: prezzo di entrata - 1 x ATR14 giornaliero del titolo
   (calcolato sulle barre giornaliere fino a ieri incluso).
8. Dimensione posizione: capitale_attuale * rischio% / R, con R = entrata -
   stop. Tetto di leva: il valore nozionale della posizione non supera 4x
   il capitale attuale (az. arrotondate per difetto).
9. Uscita in tre gambe: 40% a TP1 (entrata + 2R) -> sposta lo stop del resto
   a pareggio; altro 40% a TP2 (entrata + 3R); ultimo 20% in trailing, esce
   alla prima candela 5m che CHIUDE sotto l'EMA9 (calcolata dall'apertura
   della sessione). Se ne' stop ne' target scattano entro la seduta, chiude
   tutto a fine giornata (15:55 NY, un po' prima della chiusura).
   Se nella stessa candela cadono sia lo stop sia un target, conta lo stop
   (convenzione prudente, identica al backtest).

LIMITI IMPORTANTI DA CONOSCERE PRIMA DI USARLO
------------------------------------------------------------
- Questo script NON e' stato eseguito contro l'API reale di Alpaca (l'ambiente
  che lo ha scritto non ha accesso alla rete di Alpaca). E' stato controllato
  solo per correttezza sintattica Python. Testalo a fondo in PAPER TRADING
  prima di avvicinarlo a un conto reale.
- Il piano dati gratuito di Alpaca ha un ritardo di 15 minuti sui dati SIP in
  tempo reale. Per operare dal vivo sui timeframe di questa strategia (5 min)
  serve un abbonamento dati in tempo reale (SIP a pagamento, o IEX gratuito
  ma con la cautela sulla qualita' del book che abbiamo gia' discusso).
- Lo script usa polling (si risveglia vicino a ogni chiusura di candela 5m),
  non uno stream websocket: piu' semplice e robusto, ma con qualche secondo
  di latenza in piu' rispetto a un feed push.
- Nessun controllo su notizie macro, orari di mercato festivi/accorciati,
  o doppi invii di ordine in caso di riavvio a meta' giornata: aggiungili
  prima di un uso reale prolungato.
- "Capitale attuale" e' letto dall'equity del conto Alpaca a ogni calcolo
  size, cosi' la leva e il rischio % si applicano come nel backtest (capitale
  composto), non a un capitale fisso.

Installazione:  pip install alpaca-py --break-system-packages
Esecuzione:     export APCA_API_KEY_ID=...    (chiavi paper o live)
                export APCA_API_SECRET_KEY=...
                python3 bot_dashboard_v2.py
"""

from __future__ import annotations
import os
import sys
import time
import logging
import dataclasses
from datetime import datetime, timedelta, date, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional

import pandas as pd
import numpy as np

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import Adjustment, DataFeed

# =============================================================================
# CONFIG — le regole del Dashboard v2, "congelate" come nei default pubblicati
# =============================================================================

NY = ZoneInfo("America/New_York")

SECTORS = {
    "XLK": ["MSFT", "AAPL", "ORCL", "CRM", "NOW", "PANW", "CRWD", "ADBE", "PLTR", "APP"],
    "SMH": ["NVDA", "MU", "AMD", "AVGO", "TSM", "ARM", "AMAT", "LRCX", "QCOM", "MRVL"],
}
INDEXES = ["SPY", "QQQ"]

MAX_CANDIDATES_PER_SECTOR = 8      # "fino a 8 candidati" (pool di leader)
SIGNALS_PER_DAY = 3                # K = 3 (dashboard: "Segnali al giorno")
ORDER_BY = "lp"                    # "lp" = per forza (momentum). Alternativa dashboard: "time"
MIN_LEADERS_CONFIRMED = 2          # "Leader che devono rompere" = Almeno 2
MIN_ORB_PCT = 0.0                  # "Ampiezza minima ORB" = 0 (disattivato)
MIN_RVOL = 0.0                     # "Volume relativo minimo" = 0 (disattivato)
REQUIRE_DAILY_TREND = False        # "Richiedi EMA20 giornaliera" = non spuntato
ENTRY_CUTOFF = dtime(10, 15)       # "Chiusura finestra d'ingresso" = 10:15
INDEX_ORB_MIN = 10                 # "Ampiezza ORB indici" = 10 minuti -> 2 barre da 5m

STOP_METHOD = "atr"                # "Metodo" stop = ATR14 giornaliero x k
ATR_K = 1.0                        # "k x ATR" = 1

EMA_TRAIL_PERIOD = 9               # "EMA di trailing" = EMA9 (5m)
LEG_WEIGHTS = (0.40, 0.40, 0.20)   # 40% TP1, 40% TP2, 20% trailing
TP1_R, TP2_R = 2.0, 3.0

RISK_BY_SCENARIO = {"A": 0.04, "B": 0.02, "D": 0.02}   # C non e' nel dizionario: non si opera
MAX_LEVERAGE = 4.0                 # "Leva massima" = 4x
COST_PER_SHARE_SIDE = 0.01         # "Costo per lato" = $0.01/azione (solo per il sizing teorico)

EOD_FLATTEN = dtime(15, 55)        # chiusura forzata di qualunque posizione residua

DATA_LOOKBACK_DAYS_FOR_ATR = 40    # giorni di storico daily scaricati per calcolare ATR14/EMA20
POLL_SECONDS = 5                   # quanto spesso controllare se e' il momento di una nuova barra 5m

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")


# =============================================================================
# CLIENT
# =============================================================================

def all_tracked_symbols() -> list[str]:
    """Indici + i due ETF di settore (serve il LORO prezzo, non la media dei membri) + i 20 titoli."""
    return INDEXES + list(SECTORS.keys()) + [s for v in SECTORS.values() for s in v]


def make_clients():
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        sys.exit("Imposta APCA_API_KEY_ID e APCA_API_SECRET_KEY come variabili d'ambiente.")
    paper = not key.startswith("AK")  # le chiavi "live" di Alpaca iniziano con AK, quelle paper con PK
    trading = TradingClient(key, secret, paper=paper)
    data = StockHistoricalDataClient(key, secret)
    log.info("Connesso ad Alpaca in modalita' %s", "PAPER" if paper else "LIVE (soldi reali!)")
    return trading, data


# =============================================================================
# DATI DI SUPPORTO: ATR14 e EMA20 giornalieri (una volta al giorno, pre-market)
# =============================================================================

def true_range(h, l, c_prev):
    return np.maximum(h - l, np.maximum((h - c_prev).abs(), (l - c_prev).abs()))


def fetch_daily_indicators(data_client: StockHistoricalDataClient, symbols: list[str]) -> dict[str, dict]:
    """Per ogni simbolo: ATR14 (fino a ieri incluso) ed EMA20 (idem), piu' la chiusura di ieri."""
    end = datetime.now(NY).date()
    start = end - timedelta(days=DATA_LOOKBACK_DAYS_FOR_ATR)
    req = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame(1, TimeFrameUnit.Day),
        start=datetime.combine(start, dtime()), end=datetime.combine(end, dtime()),
        adjustment=Adjustment.SPLIT, feed=DataFeed.SIP,
    )
    df = data_client.get_stock_bars(req).df
    out = {}
    for s in symbols:
        try:
            d = df.xs(s, level=0).sort_index()
        except KeyError:
            log.warning("Nessun dato giornaliero per %s", s)
            continue
        if len(d) < 21:
            log.warning("Storico insufficiente per ATR14/EMA20 su %s (%d barre)", s, len(d))
            continue
        d = d.iloc[:-1] if d.index[-1].date() == end else d  # esclude la barra di oggi se presente
        h, l, c = d["high"].values, d["low"].values, d["close"].values
        prevc = np.roll(c, 1); prevc[0] = np.nan
        tr = true_range(h, l, prevc)
        atr14 = pd.Series(tr).rolling(14).mean().iloc[-1]
        ema20 = pd.Series(c).ewm(span=20, adjust=False).mean().iloc[-1]
        out[s] = dict(atr14=float(atr14), ema20=float(ema20), prev_close=float(c[-1]))
    return out


# =============================================================================
# STATO DELLA SESSIONE
# =============================================================================

@dataclasses.dataclass
class Candle:
    o: float; h: float; l: float; c: float; v: float; t: datetime


@dataclasses.dataclass
class Position:
    symbol: str
    entry: float
    stop: float
    r: float
    shares_total: int
    shares_open: int
    stage: int = 0          # 0 = sotto TP1, 1 = TP1 preso, 2 = TP2 preso (trailing)
    closes_since_entry: list = dataclasses.field(default_factory=list)


class SessionState:
    def __init__(self):
        self.bars: dict[str, list[Candle]] = {s: [] for s in all_tracked_symbols()}
        self.daily: dict[str, dict] = {}
        self.sector_chosen: Optional[str] = None
        self.leaders: list[str] = []
        self.leader_breaks: dict[str, int] = {}   # simbolo -> indice barra di rottura (None se non ancora)
        self.positions: dict[str, Position] = {}
        self.done_for_today: set[str] = set()     # simboli gia' entrati/scartati oggi


# =============================================================================
# LOGICA DI STRATEGIA (porta 1:1 le funzioni gia' verificate nella dashboard)
# =============================================================================

def orb_state(bars: list[Candle], n_bars: int) -> str:
    """Stato 'U'/'D'/'I' rispetto all'ORB (massimo/minimo delle prime n_bars barre)."""
    if len(bars) <= n_bars:
        return "nd"
    h = max(b.h for b in bars[:n_bars])
    l = min(b.l for b in bars[:n_bars])
    c = bars[-1].c
    return "U" if c > h else ("D" if c < l else "I")


def index_scenario(state: SessionState) -> Optional[str]:
    n_bars = INDEX_ORB_MIN // 5
    a = orb_state(state.bars["SPY"], n_bars)
    b = orb_state(state.bars["QQQ"], n_bars)
    if "nd" in (a, b):
        return None
    u = (a == "U") + (b == "U")
    if u == 2: return "A"
    if u == 1: return "B"
    if a == "I" and b == "I": return "D"
    return "C"


def ema_series(closes: list[float], period: int) -> list[float]:
    al = 2 / (period + 1)
    out, e = [], None
    for c in closes:
        e = c if e is None else c * al + e * (1 - al)
        out.append(e)
    return out


def step_position(pos: Position, bar: Candle) -> list[tuple[int, float, str]]:
    """
    Avanza la macchina a stati di una posizione di UNA candela 5m.
    Ritorna una lista di (azioni_da_vendere, prezzo_di_riferimento, motivo) — puo' avere
    0, 1 o 2 elementi (2 solo se TP1 e TP2 scattano nella stessa candela: due ordini distinti).
    """
    pos.closes_since_entry.append(bar.c)
    tp1 = pos.entry + TP1_R * pos.r
    tp2 = pos.entry + TP2_R * pos.r
    out: list[tuple[int, float, str]] = []

    if pos.stage == 0:
        if bar.l <= pos.stop:
            out.append((pos.shares_open, pos.stop, "stop iniziale"))
            pos.shares_open = 0
            return out
        if bar.h >= tp1:
            qty = round(pos.shares_total * LEG_WEIGHTS[0])
            pos.stage = 1
            pos.stop = pos.entry  # stop del resto a pareggio
            pos.shares_open -= qty
            out.append((qty, tp1, "TP1 (+2R), stop residuo a pareggio"))
            if bar.h >= tp2:
                qty2 = round(pos.shares_total * LEG_WEIGHTS[1])
                pos.stage = 2
                pos.shares_open -= qty2
                out.append((qty2, tp2, "TP2 (+3R) nella stessa candela di TP1"))
    elif pos.stage == 1:
        if bar.l <= pos.stop:
            out.append((pos.shares_open, pos.stop, "pareggio dopo TP1"))
            pos.shares_open = 0
        elif bar.h >= tp2:
            qty = round(pos.shares_total * LEG_WEIGHTS[1])
            pos.stage = 2
            pos.shares_open -= qty
            out.append((qty, tp2, "TP2 (+3R), ultima gamba in trailing"))
    elif pos.stage == 2:
        es = ema_series(pos.closes_since_entry, EMA_TRAIL_PERIOD)
        if bar.c < es[-1]:
            out.append((pos.shares_open, bar.c, "chiusura sotto EMA9"))
            pos.shares_open = 0
    return out


# =============================================================================
# ESECUZIONE ORDINI
# =============================================================================

def submit_market_order(trading: TradingClient, symbol: str, qty: int, side: OrderSide):
    if qty <= 0:
        return
    req = MarketOrderRequest(symbol=symbol, qty=qty, side=side, time_in_force=TimeInForce.DAY)
    order = trading.submit_order(req)
    log.info("Ordine inviato: %s %d %s (id=%s)", side.value, qty, symbol, order.id)
    return order


def account_equity(trading: TradingClient) -> float:
    acc = trading.get_account()
    return float(acc.equity)


def size_position(equity: float, risk_pct: float, entry: float, stop: float) -> int:
    r = entry - stop
    if r <= 0:
        return 0
    shares = int(equity * risk_pct / r)
    max_by_leverage = int(MAX_LEVERAGE * equity / entry)
    return max(0, min(shares, max_by_leverage))


# =============================================================================
# CICLO PRINCIPALE (polling)
# =============================================================================

def next_5min_boundary(now: datetime) -> datetime:
    minute = (now.minute // 5 + 1) * 5
    base = now.replace(second=0, microsecond=0, minute=0) + timedelta(hours=minute // 60)
    return base.replace(minute=minute % 60)


def fetch_latest_bars(data_client: StockHistoricalDataClient, symbols: list[str]) -> dict[str, Candle]:
    req = StockLatestBarRequest(symbol_or_symbols=symbols, feed=DataFeed.SIP)
    latest = data_client.get_stock_latest_bar(req)
    out = {}
    for s, b in latest.items():
        out[s] = Candle(o=b.open, h=b.high, l=b.low, c=b.close, v=b.volume, t=b.timestamp)
    return out


def run_day():
    trading, data_client = make_clients()
    all_symbols = all_tracked_symbols()
    state = SessionState()

    log.info("Pre-market: calcolo ATR14 ed EMA20 giornalieri...")
    state.daily = fetch_daily_indicators(data_client, all_symbols)

    log.info("In attesa dell'apertura (9:30 NY)...")
    while datetime.now(NY).time() < dtime(9, 30):
        time.sleep(POLL_SECONDS)

    last_bar_time = None
    while True:
        now = datetime.now(NY)
        if now.time() >= EOD_FLATTEN:
            flatten_all(trading, state)
            log.info("Giornata conclusa.")
            break

        target = next_5min_boundary(now - timedelta(seconds=1))
        if now < target:
            time.sleep(POLL_SECONDS)
            continue

        bars = fetch_latest_bars(data_client, all_symbols)
        for s in all_symbols:
            if s in bars and (not state.bars[s] or state.bars[s][-1].t != bars[s].t):
                state.bars[s].append(bars[s])

        n_bars_done = len(state.bars["SPY"])

        # --- 9:35: scegli il settore (dopo la prima candela, n_bars_done==1) ---
        if n_bars_done == 1 and state.sector_chosen is None:
            choose_sector(state)

        # --- 9:40: classifica i leader (dopo la seconda candela) ---
        if n_bars_done == 2 and state.sector_chosen and not state.leaders:
            rank_leaders(state)

        # --- 9:45-10:15: cerca rotture ed entra ---
        if state.leaders and now.time() <= ENTRY_CUTOFF:
            check_entries(trading, data_client, state)

        # --- gestisci posizioni aperte ---
        manage_positions(trading, state)

        last_bar_time = bars.get("SPY", Candle(0,0,0,0,0,now)).t
        time.sleep(1)


def choose_sector(state: SessionState):
    """Alle 9:35: % dell'ETF di settore dalla chiusura di ieri (non la media dei membri)."""
    best, best_pct = None, -9e9
    for sec in SECTORS:
        if state.bars[sec] and sec in state.daily:
            pct = state.bars[sec][-1].c / state.daily[sec]["prev_close"] - 1
            if pct > best_pct:
                best, best_pct = sec, pct
    if best is not None and best_pct > 0:
        state.sector_chosen = best
        log.info("Settore scelto: %s (%.2f%%)", best, best_pct * 100)
    else:
        state.sector_chosen = "__NONE__"
        log.info("Nessun settore positivo alle 9:35: non si opera oggi.")


def rank_leaders(state: SessionState):
    if state.sector_chosen == "__NONE__":
        return
    cands = []
    for s in SECTORS[state.sector_chosen]:
        if state.bars[s] and s in state.daily and len(state.bars[s]) >= 2:
            lp = state.bars[s][1].c / state.daily[s]["prev_close"] - 1
            if lp > 0:
                cands.append((lp, s))
    cands.sort(reverse=True)
    cands = cands[:MAX_CANDIDATES_PER_SECTOR]           # pool completo: serve per calcolare nlead
    chosen = cands[:SIGNALS_PER_DAY]                     # ORDER_BY="lp": i primi K per forza sono operabili
    state.leaders = [s for _, s in cands]
    state._leaders_tradable = set(s for _, s in chosen)
    log.info("Leader (pool %d, operabili %d): %s", len(cands), len(state._leaders_tradable),
              [s for _, s in cands])


def check_entries(trading: TradingClient, data_client: StockHistoricalDataClient, state: SessionState):
    scen = index_scenario(state)
    for s in state.leaders:
        if s in state.done_for_today or s in state.positions:
            continue
        bars = state.bars[s]
        if len(bars) < 2:
            continue
        h0 = bars[0].h
        if bars[-1].c <= h0:
            continue  # non ha ancora rotto
        idx = len(bars) - 1
        if s not in state.leader_breaks:
            state.leader_breaks[s] = idx

        nlead = sum(1 for v in state.leader_breaks.values() if v <= idx)
        if nlead < MIN_LEADERS_CONFIRMED:
            continue
        if scen is None or scen not in RISK_BY_SCENARIO:
            state.done_for_today.add(s)
            continue
        if s not in state._leaders_tradable:
            continue  # fuori dai primi K per forza (fa comunque parte del pool per nlead)

        atr = state.daily.get(s, {}).get("atr14")
        if atr is None:
            state.done_for_today.add(s)
            continue
        entry = bars[-1].c
        stop = entry - ATR_K * atr
        r = entry - stop
        if r <= 0:
            state.done_for_today.add(s)
            continue

        equity = account_equity(trading)
        risk_pct = RISK_BY_SCENARIO[scen]
        shares = size_position(equity, risk_pct, entry, stop)
        if shares < 1:
            state.done_for_today.add(s)
            continue

        submit_market_order(trading, s, shares, OrderSide.BUY)
        state.positions[s] = Position(symbol=s, entry=entry, stop=stop, r=r,
                                       shares_total=shares, shares_open=shares)
        state.done_for_today.add(s)
        log.info("ENTRATA %s @ %.3f  stop=%.3f  R=%.3f  azioni=%d  scenario=%s  rischio=%.0f%%",
                  s, entry, stop, r, shares, scen, risk_pct * 100)


def manage_positions(trading: TradingClient, state: SessionState):
    for s, pos in list(state.positions.items()):
        bars = state.bars[s]
        if not bars:
            continue
        for qty, px, reason in step_position(pos, bars[-1]):
            submit_market_order(trading, s, qty, OrderSide.SELL)
            log.info("USCITA %s: %d azioni (%s), rif. prezzo %.3f, residue %d",
                      s, qty, reason, px, pos.shares_open)
        if pos.shares_open <= 0:
            del state.positions[s]


def flatten_all(trading: TradingClient, state: SessionState):
    for s, pos in list(state.positions.items()):
        if pos.shares_open > 0:
            submit_market_order(trading, s, pos.shares_open, OrderSide.SELL)
            log.info("Chiusura fine giornata: %s %d azioni", s, pos.shares_open)
    state.positions.clear()


if __name__ == "__main__":
    log.warning("=" * 70)
    log.warning("Bot NON testato contro l'API reale. Usa SOLO un conto paper finche'")
    log.warning("non hai verificato ogni comportamento a mano, candela per candela.")
    log.warning("=" * 70)
    run_day()
