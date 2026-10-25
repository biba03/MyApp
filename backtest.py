"""
backtest.py

Rigorous walk-forward backtesting engine for the pattern screener.

Answers one question: does this screening algorithm actually have
predictive power - evaluated the way a trading-platform strategy
tester would (TradingView's Bar Replay / Strategy Tester), iterating
one historical bar at a time, using only data available at that bar.

HOW LOOK-AHEAD BIAS IS ACTUALLY ELIMINATED (not just documented as a
caveat, as the earliest version of this file did): indicators -
including pivot detection, which uses a centered rolling window - are
recomputed FROM SCRATCH on a trailing window of raw OHLCV data ending
exactly at the bar being evaluated, not sliced out of a single
once-computed full-history dataframe. Since the window physically
contains no data beyond "today", nothing computed from it (including
near-boundary pivots) can see the future.

WHAT CHANGED IN THIS REVISION (review + fixes):

1. Summary performance is now computed from the trades the portfolio
   actually TOOK (`accepted_trades`), not from every raw signal. The
   equity curve and the headline stats therefore describe the same
   universe. The per-signal scanner-validation breakdowns (pattern /
   score / confidence) still run over *all* signals on purpose - that
   is a diagnostic of the raw scanner, and is reported separately.

2. Trading costs now hit the equity curve exactly once. The
   `PortfolioSimulator` is the single source of truth for cash: it
   applies commission on both the BUY and the SELL, sizes the
   position, and writes the realized dollar P/L back onto the trade.
   The old code applied a percentage cost only inside each trade's
   `net_return` fraction (which fed the stats) while the cash pool
   itself paid nothing - so the curve was systematically too rosy and
   disagreed with the stats.

3. Spec-driven trade model added as first-class config, without
   removing the original one:
      - flat per-side commission          (commission_flat)
      - equal-weight sizing from cash      (position_sizing="equal_weight")
      - single ATR-close exit rule         (exit_mode="atr_close")
        "sell when Close < Entry - mult x ATR(at entry)"
      - next-open entries AND next-open exit fills (no look-ahead on
        either leg).

HONEST, KNOWN LIMITATIONS (not glossed over):

- Survivorship bias: the universe comes from *today's* index
  membership, not point-in-time historical membership. A company
  delisted or removed during the backtest period simply isn't in the
  `data` dict, which biases results positively versus what actually
  happened. There is no free point-in-time constituents dataset wired
  up here to fully fix this.
- Costs are a flat commission per side. Real slippage scales with
  volatility, order size, and liquidity; a fixed slippage_pct is
  available but off by default in the spec config.
- The equity curve marks open positions to each day's close but does
  not model whether a position of that size could have been filled
  without moving the price.
- Recomputing indicators fresh at every bar is the whole point, but
  it is the expensive part. Use `step` and/or `use_multiprocessing`
  to explore; do the final validation run at step=1.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path
import time
from timing import timer, _record_elapsed

import numpy as np
import pandas as pd

try:  # tqdm is a hard dependency (requirements.txt) but degrade gracefully
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - fallback if tqdm missing
    def tqdm(iterable=None, **_kwargs):
        return iterable if iterable is not None else []

import config as project_config
import indicators


##############################################################################
# Configuration
##############################################################################

@dataclass
class BacktestConfig:

    # --- Period -------------------------------------------------------------
    start_date: object = None
    end_date: object = None

    # --- Capital ------------------------------------------------------------
    initial_capital: float = project_config.ACCOUNT_SIZE

    # --- Costs --------------------------------------------------------------
    # Flat dollar commission charged on EACH side (one on the buy, one on
    # the sell). When set, it overrides commission_pct in the cash
    # accounting. This is the spec model ($30 buy / $30 sell).
    commission_flat: float | None = None
    commission_pct: float = 0.0005      # 5 bps per side (used only if commission_flat is None)
    slippage_pct: float = 0.0           # 0 by default; commissions are the modeled cost

    # --- Position sizing ----------------------------------------------------
    # "equal_weight"  -> split available cash evenly across the free slots
    # "fixed_dollar"  -> a constant dollar notional per trade
    # "fixed_percent" / "atr_risk" -> risk a fixed % of equity off the stop
    position_sizing: str = "fixed_percent"
    fixed_dollar_amount: float = 10_000
    risk_per_trade: float = project_config.RISK_PER_TRADE
    max_open_positions: int = 5

    # --- Diversification (research-validated; off by default, on in spec()) --
    # one_position_per_ticker: never hold the same stock twice (a ticker
    #   firing several patterns was previously counted as several positions).
    # max_positions_per_sector: cap correlated exposure; needs a sector_map
    #   passed to the engine, otherwise silently skipped.
    one_position_per_ticker: bool = False
    max_positions_per_sector: int | None = None

    # Correlation-aware diversification: block a new entry that is >=
    # corr_cluster_threshold correlated (trailing corr_window days) with
    # >= max_per_corr_cluster already-open names. Catches one-bet clusters
    # the GICS sector cap misses. None = off. Validated: reduces drawdown
    # out-of-sample at a LOOSE threshold (~0.8); tight (<=0.7) over-constrains.
    corr_cluster_threshold: float | None = None
    max_per_corr_cluster: int = 2
    corr_window: int = 60

    # --- Regime entry gate (drawdown control) -------------------------------
    # Block NEW entries whose entry-date benchmark regime is in this set,
    # e.g. ("Bear",). Needs a benchmark passed to run(); otherwise ignored.
    # Validated: reduces max drawdown out-of-sample; does not reliably lift
    # returns, so it is a risk-control lever, not a return enhancer.
    block_entry_regimes: tuple = ()

    # Graded regime exposure (the Minervini/Qullamaggie "reduce exposure in
    # corrections" rule): {regime_name: slot_fraction}. On each day the
    # effective position cap is round(max_open_positions * fraction) for
    # that day's benchmark regime. Missing regimes default to 1.0 (full).
    # Empty dict = feature off. A fraction of 0.0 subsumes a hard block.
    regime_position_scale: dict = field(default_factory=dict)

    # --- Exit model ---------------------------------------------------------
    # "target_stop" -> original engine: intraday pattern stop + R target /
    #                  trailing / time stop (kept for backward compatibility)
    # "atr_close"   -> spec rule: exit when Close < Entry - mult x ATR(entry)
    exit_mode: str = "target_stop"
    atr_stop_multiple: float = 1.0      # the "1 x ATR" in the exit rule
    target_type: str = "2R"             # "2R" | "3R" | "trailing"  (target_stop mode)
    trailing_atr_multiple: float = 2.0
    max_holding_days: int | None = 40   # None = no time stop (pure ATR exit)

    # --- Entry / exit fill --------------------------------------------------
    entry_method: str = "close"         # "close" | "next_open"
    exit_fill: str = "close"            # "close" | "next_open" (atr_close mode)

    # --- Walk-forward mechanics --------------------------------------------
    step: int = 1                       # sample every Nth trading day (1 = every day)
    indicator_window: int = 310         # trailing bars recomputed fresh at each step
    min_history: int = 260              # first bar index eligible to be scanned
    lite_indicators: bool = False       # skip indicators no detector/feature reads
                                        # (indicators.LITE_SKIP) for a faster scan;
                                        # correctness-guarded by tests

    # --- Execution ----------------------------------------------------------
    use_multiprocessing: bool = False
    max_workers: int | None = None
    show_progress: bool = True          # tqdm progress bar during portfolio replay
    random_seed: int = 42               # forward-compat; engine is deterministic today

    def __post_init__(self):
        self.start_date = pd.Timestamp(self.start_date) if self.start_date else None
        self.end_date = pd.Timestamp(self.end_date) if self.end_date else None

    # Convenience: the spec's requirement set as a ready-to-run config.
    @classmethod
    def spec(
        cls,
        start_date: object = "2020-01-01",
        end_date: object = "2024-12-31",
        **overrides,
    ) -> "BacktestConfig":
        params = dict(
            start_date=start_date,
            end_date=end_date,
            initial_capital=100_000,
            commission_flat=30.0,
            slippage_pct=0.0,
            position_sizing="equal_weight",
            # Capacity fix (OOS-confirmed for drawdown): 20 slots turned the
            # -45% / 0.49-Sharpe 5-slot lottery into ~-17% / 0.89 Sharpe.
            max_open_positions=20,
            one_position_per_ticker=True,
            max_positions_per_sector=2,
            # Bear de-risking (OOS-confirmed for drawdown): no new entries
            # while SPY is in a Bear regime. Needs a benchmark passed to
            # run(); inert otherwise.
            regime_position_scale={"Bear": 0.0},
            exit_mode="atr_close",
            atr_stop_multiple=1.0,
            max_holding_days=None,
            entry_method="next_open",
            exit_fill="next_open",
        )
        params.update(overrides)
        return cls(**params)


##############################################################################
# Signal / Trade records
##############################################################################

@dataclass(slots=True)
class Signal:

    date: pd.Timestamp
    ticker: str
    pattern: str
    score: float
    confidence: float
    entry: float
    stop: float
    target: float
    rr: float
    atr: float = 0.0        # ATR14 captured at the signal bar (no look-ahead)
    features: dict = field(default_factory=dict)  # entry-time research features


@dataclass(slots=True)
class SimulatedTrade:

    ticker: str
    pattern: str
    score: float
    confidence: float
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    stop: float
    target: float
    exit_reason: str  # "stop" / "target" / "trailing_stop" / "time_stop" / "atr_stop"
    holding_days: int
    mfe: float  # max favorable excursion, in R
    mae: float  # max adverse excursion, in R
    gross_return: float
    net_return: float
    r_multiple: float | None
    atr_at_entry: float = 0.0

    # --- Filled in by the PortfolioSimulator for trades actually taken ------
    shares: int = 0
    position_size: float = 0.0     # dollar cost basis at entry (shares * entry)
    commission_paid: float = 0.0   # buy commission + sell commission
    gross_pl: float = 0.0          # shares * (exit - entry)
    net_pl: float = 0.0            # gross_pl - commission_paid
    return_pct: float = 0.0        # net_pl / cost basis * 100
    features: dict = field(default_factory=dict)  # entry-time research features
    exit_at_close: bool = False  # Close fills cannot fund earlier open entries.


##############################################################################
# Walk-forward screener - the no-look-ahead core
##############################################################################

class WalkForwardScreener:

    def __init__(self, detectors, cfg: BacktestConfig, feature_extractor=None):
        self.detectors = detectors
        self.cfg = cfg
        # Optional research.FeatureExtractor - when supplied, every signal
        # carries its entry-time feature vector for later analysis.
        self.feature_extractor = feature_extractor

    def scan_ticker(self, ticker: str, raw_df: pd.DataFrame) -> list[Signal]:
        """
        raw_df must be plain OHLCV (Open/High/Low/Close/Volume) with NO
        precomputed indicators - they are computed fresh on each trailing
        window inside this loop. That recomputation, on a window that
        physically ends at "today", is what eliminates look-ahead bias.
        """

        cfg = self.cfg
        signals: list[Signal] = []
        n = len(raw_df)

        for i in range(cfg.min_history, n, cfg.step):

            date = raw_df.index[i]

            if cfg.start_date is not None and date < cfg.start_date:
                continue

            if cfg.end_date is not None and date > cfg.end_date:
                break  # dates are sorted ascending

            window_start = max(0, i + 1 - cfg.indicator_window)
            window = raw_df.iloc[window_start: i + 1].copy()

            if len(window) < cfg.min_history:
                continue

            try:
                indicators.compute_all(window, lite=cfg.lite_indicators)
            except ValueError:
                continue  # not enough valid data in this particular window

            # ATR14 at the signal bar - the ATR "available in the project",
            # computed only from data up to and including this bar.
            atr_at_signal = self._safe_atr(window)

            # Entry-time research features (computed once per bar, reused
            # across detectors that fire on the same bar).
            features = (
                self.feature_extractor.extract(window)
                if self.feature_extractor is not None else {}
            )

            for detector in self.detectors:

                try:
                    pattern = detector.detect(window)
                except Exception:
                    continue

                if not pattern.detected:
                    continue

                risk = pattern.entry - pattern.stop
                rr = (pattern.target - pattern.entry) / risk if risk > 0 else 0.0

                signals.append(Signal(
                    date=date,
                    ticker=ticker,
                    pattern=detector.name,
                    score=pattern.score,
                    confidence=pattern.confidence,
                    entry=pattern.entry,
                    stop=pattern.stop,
                    target=pattern.target,
                    rr=rr,
                    atr=atr_at_signal,
                    features=dict(features),
                ))

        return signals

    @staticmethod
    def _safe_atr(window: pd.DataFrame) -> float:
        """ATR14 at the last (current) bar, or 0.0 if unavailable."""
        col = f"ATR{project_config.ATR_PERIOD}"
        if col not in window.columns:
            return 0.0
        val = window[col].iloc[-1]
        return float(val) if pd.notna(val) else 0.0


##############################################################################
# Position sizing (per-trade risk models; equal-weight lives in the portfolio)
##############################################################################

class PositionSizer:

    def __init__(self, cfg: BacktestConfig):
        self.cfg = cfg

    def shares_for(self, equity: float, entry: float, stop: float) -> int:

        cfg = self.cfg
        risk_per_share = entry - stop

        if risk_per_share <= 0:
            return 0

        if cfg.position_sizing == "fixed_dollar":
            return max(int(cfg.fixed_dollar_amount / entry), 0)

        # "fixed_percent" and "atr_risk" both risk a fixed % of current
        # equity, sized off the stop distance - two labels, same math.
        dollar_risk = equity * cfg.risk_per_trade
        return max(int(dollar_risk / risk_per_share), 0)


##############################################################################
# Trade simulation - entry/exit mechanics for a single signal
##############################################################################

class TradeSimulator:

    def __init__(self, cfg: BacktestConfig):
        self.cfg = cfg

    # --- Entry -------------------------------------------------------------
    def _entry(self, signal: Signal, raw_df: pd.DataFrame, signal_index: int):
        """Returns (entry_index, entry_price) or None if unfillable."""
        cfg = self.cfg
        n = len(raw_df)

        if cfg.entry_method == "next_open":
            entry_index = signal_index + 1
            if entry_index >= n:
                return None
            entry_price = float(raw_df["Open"].iloc[entry_index])
        else:
            entry_index = signal_index
            entry_price = signal.entry

        entry_price *= (1 + cfg.slippage_pct)
        return entry_index, entry_price

    # --- Dispatch ----------------------------------------------------------
    def simulate(
        self,
        signal: Signal,
        raw_df: pd.DataFrame,
        signal_index: int,
    ) -> SimulatedTrade | None:

        entered = self._entry(signal, raw_df, signal_index)
        if entered is None:
            return None
        entry_index, entry_price = entered

        if self.cfg.exit_mode == "atr_close":
            return self._simulate_atr_close(signal, raw_df, entry_index, entry_price)
        return self._simulate_target_stop(signal, raw_df, entry_index, entry_price)

    # --- Spec exit: close < entry - mult x ATR -----------------------------
    def _simulate_atr_close(
        self,
        signal: Signal,
        raw_df: pd.DataFrame,
        entry_index: int,
        entry_price: float,
    ) -> SimulatedTrade | None:
        """
        Hold until the CLOSE falls below entry - mult x ATR(at entry).
        The trigger is detected on a bar's close; the fill happens on the
        next bar's open (exit_fill="next_open") so neither leg peeks at a
        price it could not have transacted at. Optionally also exits after
        max_holding_days.
        """
        cfg = self.cfg
        n = len(raw_df)

        atr = signal.atr
        risk_per_share = cfg.atr_stop_multiple * atr
        if risk_per_share <= 0:
            return None  # no valid ATR -> cannot define the stop

        stop_level = entry_price - risk_per_share

        mfe = mae = 0.0
        exit_price = None
        exit_reason = "time_stop"
        exit_index = n - 1
        exit_at_close = False

        # An entry at the open is exposed to that same day's close.
        first_check = entry_index if cfg.entry_method == "next_open" else entry_index + 1
        for j in range(first_check, n):

            high = float(raw_df["High"].iloc[j])
            low = float(raw_df["Low"].iloc[j])
            close = float(raw_df["Close"].iloc[j])

            mfe = max(mfe, (high - entry_price) / risk_per_share)
            mae = max(mae, (entry_price - low) / risk_per_share)

            time_stopped = (
                cfg.max_holding_days is not None
                and (j - entry_index) >= cfg.max_holding_days
            )

            if close < stop_level or time_stopped:
                reason = "atr_stop" if close < stop_level else "time_stop"
                exit_index, exit_price = self._exit_fill(raw_df, j)
                exit_at_close = cfg.exit_fill == "close" or j + 1 >= n
                exit_reason = reason
                break

        if exit_price is None:  # never triggered -> exit at last available close
            exit_index = n - 1
            exit_price = float(raw_df["Close"].iloc[exit_index])
            exit_reason = "time_stop"
            exit_at_close = True

        return self._make_trade(
            signal, raw_df, entry_index, entry_price, exit_index, exit_price,
            stop=stop_level, target=None, risk_per_share=risk_per_share,
            exit_reason=exit_reason, mfe=mfe, mae=mae,
            exit_at_close=exit_at_close,
        )

    def _exit_fill(self, raw_df: pd.DataFrame, trigger_index: int):
        """Where the exit actually fills given the trigger bar."""
        n = len(raw_df)
        if self.cfg.exit_fill == "next_open" and trigger_index + 1 < n:
            idx = trigger_index + 1
            price = float(raw_df["Open"].iloc[idx]) * (1 - self.cfg.slippage_pct)
            return idx, price
        price = float(raw_df["Close"].iloc[trigger_index]) * (1 - self.cfg.slippage_pct)
        return trigger_index, price

    # --- Original exit: pattern stop + R target / trailing / time stop -----
    def _simulate_target_stop(
        self,
        signal: Signal,
        raw_df: pd.DataFrame,
        entry_index: int,
        entry_price: float,
    ) -> SimulatedTrade | None:

        cfg = self.cfg
        n = len(raw_df)

        stop = signal.stop
        risk_per_share = entry_price - stop
        if risk_per_share <= 0:
            return None

        if cfg.target_type == "2R":
            target = entry_price + risk_per_share * 2
        elif cfg.target_type == "3R":
            target = entry_price + risk_per_share * 3
        else:  # "trailing"
            target = None

        trailing_stop = stop
        mfe = mae = 0.0
        exit_price = None
        exit_reason = "time_stop"

        horizon = cfg.max_holding_days if cfg.max_holding_days is not None else n
        last_index = min(entry_index + horizon, n - 1)
        exit_index = last_index

        for j in range(entry_index + 1, last_index + 1):

            low = float(raw_df["Low"].iloc[j])
            high = float(raw_df["High"].iloc[j])

            mfe = max(mfe, (high - entry_price) / risk_per_share)
            mae = max(mae, (entry_price - low) / risk_per_share)

            if cfg.target_type == "trailing":
                trailing_stop = max(
                    trailing_stop, high - cfg.trailing_atr_multiple * risk_per_share
                )
                if low <= trailing_stop:
                    exit_price, exit_reason, exit_index = trailing_stop, "trailing_stop", j
                    break
            else:
                if low <= stop:
                    exit_price, exit_reason, exit_index = stop, "stop", j
                    break
                if high >= target:
                    exit_price, exit_reason, exit_index = target, "target", j
                    break

        if exit_price is None:
            exit_index = last_index
            exit_price = float(raw_df["Close"].iloc[last_index])
            exit_reason = "time_stop"

        exit_price *= (1 - cfg.slippage_pct)

        return self._make_trade(
            signal, raw_df, entry_index, entry_price, exit_index, exit_price,
            stop=stop, target=target, risk_per_share=risk_per_share,
            exit_reason=exit_reason, mfe=mfe, mae=mae,
            exit_at_close=exit_reason == "time_stop",
        )

    # --- Shared record construction ----------------------------------------
    def _make_trade(
        self, signal, raw_df, entry_index, entry_price, exit_index, exit_price,
        stop, target, risk_per_share, exit_reason, mfe, mae,
        exit_at_close=False,
    ) -> SimulatedTrade:

        cfg = self.cfg
        gross_return = (exit_price - entry_price) / entry_price
        # Percentage-cost fallback used by the per-signal breakdowns; the
        # authoritative dollar P/L for taken trades is set in the portfolio.
        net_return = gross_return - (cfg.commission_pct * 2)
        r_multiple = (exit_price - entry_price) / risk_per_share

        return SimulatedTrade(
            ticker=signal.ticker,
            pattern=signal.pattern,
            score=signal.score,
            confidence=signal.confidence,
            signal_date=signal.date,
            entry_date=raw_df.index[entry_index],
            exit_date=raw_df.index[exit_index],
            entry_price=entry_price,
            exit_price=exit_price,
            stop=stop,
            target=target if target is not None else float("nan"),
            exit_reason=exit_reason,
            holding_days=exit_index - entry_index,
            mfe=mfe,
            mae=mae,
            gross_return=gross_return,
            net_return=net_return,
            r_multiple=r_multiple,
            atr_at_entry=signal.atr,
            features=dict(signal.features),
            exit_at_close=exit_at_close,
        )


def signals_to_trades(
    signals: list[Signal],
    raw_df: pd.DataFrame,
    cfg: BacktestConfig,
) -> list[SimulatedTrade]:
    """
    Converts a ticker's raw signal log into trade records, one per
    signal, EXCEPT that a new trade for a given pattern is skipped while
    a previous trade in that same ticker/pattern is still open -
    otherwise a pattern that fires for several consecutive days would
    open a new "trade" every single day, which isn't a realistic
    simulation of how you'd act on repeated signals.
    """

    simulator = TradeSimulator(cfg)
    date_to_index = {date: i for i, date in enumerate(raw_df.index)}
    open_until_by_pattern: dict[str, int] = {}
    trades: list[SimulatedTrade] = []

    for sig in signals:

        idx = date_to_index.get(sig.date)
        if idx is None:
            continue

        if open_until_by_pattern.get(sig.pattern, -1) > idx:
            continue

        trade = simulator.simulate(sig, raw_df, idx)
        if trade is None:
            continue

        exit_idx = date_to_index.get(trade.exit_date, idx)
        open_until_by_pattern[sig.pattern] = exit_idx
        trades.append(trade)

    return trades


##############################################################################
# Portfolio-level simulation - capital, max_open_positions, equity curve
##############################################################################

@dataclass
class PortfolioStats:
    cash_remaining: float
    open_positions_at_end: int
    avg_capital_utilization: float
    # Reject-reason accounting for the capital-utilization report.
    rejects: dict = field(default_factory=dict)


class PortfolioSimulator:
    """
    Replays every candidate trade against a single capital pool, day by
    day, respecting max_open_positions. When more candidate trades want
    to open on a day than there's room for, the highest-score signals get
    priority.

    THIS is where money is actually spent: it sizes each position, charges
    commission on the buy and again on the sell, and writes the realized
    dollar P/L back onto each trade it takes. Open positions are marked to
    market at each ticker's own close, so the equity curve reflects real
    daily volatility, not just entry/exit events.
    """

    def __init__(self, cfg: BacktestConfig, sector_map=None):
        self.cfg = cfg
        self.sizer = PositionSizer(cfg)
        # Optional SectorIndustryMap - required only for the sector cap.
        self.sector_map = sector_map
        self._returns_cache: dict = {}

    def _sector(self, ticker: str) -> str:
        if self.sector_map is None:
            return "Unknown"
        return self.sector_map.get(ticker)[0]

    # --- Correlation-cluster diversification ------------------------------
    def _ret(self, ticker, close_prices):
        cache = self._returns_cache
        if ticker not in cache:
            s = close_prices.get(ticker)
            cache[ticker] = s.pct_change() if s is not None else None
        return cache[ticker]

    def _too_correlated(self, ticker, open_tickers, date, close_prices) -> bool:
        thr = self.cfg.corr_cluster_threshold
        if thr is None or not open_tickers:
            return False
        cw = self.cfg.corr_window
        cand = self._ret(ticker, close_prices)
        if cand is None:
            return False
        cand_w = cand.loc[:date].iloc[-cw:]
        if len(cand_w) < cw // 2:
            return False
        hits = 0
        for ot in open_tickers:
            other = self._ret(ot, close_prices)
            if other is None:
                continue
            aligned = pd.concat([cand_w, other.loc[:date].iloc[-cw:]], axis=1, join="inner").dropna()
            if len(aligned) < cw // 2:
                continue
            c = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
            if pd.notna(c) and abs(c) >= thr:
                hits += 1
                if hits >= self.cfg.max_per_corr_cluster:
                    return True
        return False

    # --- Commission -------------------------------------------------------
    def _commission(self, notional: float) -> float:
        if self.cfg.commission_flat is not None:
            return float(self.cfg.commission_flat)
        return notional * self.cfg.commission_pct

    # --- Sizing -----------------------------------------------------------
    def _shares_to_buy(self, cash: float, equity: float, free_slots: int, trade) -> int:
        """
        Returns a share count that never spends more cash than we have
        (including the buy commission) and never uses leverage.
        """
        entry = trade.entry_price

        if self.cfg.position_sizing == "equal_weight":
            # Split *available cash* evenly across the remaining free slots.
            allocation = cash / max(free_slots, 1)
            budget = allocation - self._commission(allocation)
            shares = max(int(budget / entry), 0)
        else:
            shares = self.sizer.shares_for(equity, entry, trade.stop)

        # Hard cash guard: shrink until cost + commission fits in cash.
        while shares > 0:
            cost = shares * entry
            if cost + self._commission(cost) <= cash:
                break
            shares -= 1
        return shares

    def _effective_max(self, date, regime_by_date) -> int:
        """Position cap for `date`, scaled by that day's regime exposure."""
        cap = self.cfg.max_open_positions
        scale = self.cfg.regime_position_scale
        if not scale or regime_by_date is None:
            return cap
        # Entries fill at the open; only completed benchmark bars are known.
        known = regime_by_date.index < date if self.cfg.entry_method == "next_open" else regime_by_date.index <= date
        prior = regime_by_date.loc[known]
        regime = prior.iloc[-1] if len(prior) else None
        frac = scale.get(regime, 1.0)
        return max(int(round(cap * frac)), 0)

    def run(
        self,
        trades: list[SimulatedTrade],
        close_prices: dict[str, pd.Series],
        regime_by_date: "pd.Series | None" = None,
    ) -> tuple[pd.Series, list[SimulatedTrade], pd.DataFrame, PortfolioStats]:

        cfg = self.cfg

        if not trades:
            empty_curve = pd.Series(dtype=float)
            empty_daily = pd.DataFrame(
                columns=["PortfolioValue", "Cash", "PositionsValue",
                         "OpenPositions", "Utilization"]
            )
            return empty_curve, [], empty_daily, PortfolioStats(cfg.initial_capital, 0, 0.0)

        timeline = self._build_timeline(trades, close_prices)

        trades_by_entry: dict = {}
        trades_by_exit: dict = {}
        for t in trades:
            trades_by_entry.setdefault(t.entry_date, []).append(t)
            trades_by_exit.setdefault(t.exit_date, []).append(t)

        cash = cfg.initial_capital
        open_positions: dict = {}  # id(trade) -> (trade, shares)
        open_tickers: set = set()          # for one_position_per_ticker
        sector_counts: dict = {}           # for max_positions_per_sector
        rejects: dict = {}
        accepted: list[SimulatedTrade] = []

        equity_curve: dict = {}
        daily_rows: list[dict] = []
        utilization_samples: list[float] = []

        def _reject(reason: str) -> None:
            rejects[reason] = rejects.get(reason, 0) + 1

        iterator = tqdm(
            timeline, desc="Backtest", unit="day", disable=not cfg.show_progress
        )

        for date in iterator:

            def close_trade(t):
                nonlocal cash
                key = id(t)
                if key in open_positions:
                    _, shares = open_positions.pop(key)
                    proceeds = shares * t.exit_price
                    cash += proceeds - self._commission(proceeds)
                    open_tickers.discard(t.ticker)
                    sec = self._sector(t.ticker)
                    sector_counts[sec] = sector_counts.get(sec, 0) - 1

            # Open exits fund open entries; terminal/close exits happen later.
            for t in trades_by_exit.get(date, []):
                if not getattr(t, "exit_at_close", False) or cfg.entry_method == "close":
                    close_trade(t)

            # 2) Open new positions (highest score first) into free slots,
            #    respecting per-ticker and per-sector diversification caps.
            candidates = sorted(
                trades_by_entry.get(date, []), key=lambda t: t.score, reverse=True
            )
            effective_max = self._effective_max(date, regime_by_date)
            for t in candidates:

                if len(open_positions) >= effective_max:
                    _reject("portfolio_full")
                    continue

                if cfg.one_position_per_ticker and t.ticker in open_tickers:
                    _reject("duplicate_ticker")
                    continue

                sector = self._sector(t.ticker)
                if (
                    cfg.max_positions_per_sector is not None
                    and sector_counts.get(sector, 0) >= cfg.max_positions_per_sector
                ):
                    _reject("sector_limit")
                    continue

                if self._too_correlated(t.ticker, open_tickers, date, close_prices):
                    _reject("correlation_cluster")
                    continue

                positions_value = self._positions_value(open_positions, close_prices, date)
                equity_estimate = cash + positions_value
                free_slots = effective_max - len(open_positions)

                shares = self._shares_to_buy(cash, equity_estimate, free_slots, t)
                if shares <= 0:
                    _reject("cash_limit")
                    continue

                cost = shares * t.entry_price
                buy_commission = self._commission(cost)
                if cost + buy_commission > cash:
                    _reject("cash_limit")
                    continue

                cash -= cost + buy_commission
                open_positions[id(t)] = (t, shares)
                open_tickers.add(t.ticker)
                sector_counts[sector] = sector_counts.get(sector, 0) + 1

                # Record everything needed for the trade log / dollar stats.
                sell_commission = self._commission(shares * t.exit_price)
                t.shares = shares
                t.position_size = cost
                t.commission_paid = buy_commission + sell_commission
                t.gross_pl = shares * (t.exit_price - t.entry_price)
                t.net_pl = t.gross_pl - t.commission_paid
                t.return_pct = (t.net_pl / cost * 100.0) if cost else 0.0
                accepted.append(t)

            for t in trades_by_exit.get(date, []):
                if getattr(t, "exit_at_close", False):
                    close_trade(t)

            # 3) Mark to market and record the day.
            positions_value = self._positions_value(open_positions, close_prices, date)
            equity = cash + positions_value
            equity_curve[date] = equity
            utilization = positions_value / equity if equity > 0 else 0.0
            utilization_samples.append(utilization)
            daily_rows.append({
                "Date": date,
                "PortfolioValue": equity,
                "Cash": cash,
                "PositionsValue": positions_value,
                "OpenPositions": len(open_positions),
                "Utilization": utilization,
            })

            if cfg.show_progress and hasattr(iterator, "set_postfix"):
                iterator.set_postfix({
                    "date": date.strftime("%Y-%m-%d"),
                    "open": len(open_positions),
                    "trades": len(accepted),
                    "value": f"${equity:,.0f}",
                }, refresh=False)

        curve = pd.Series(equity_curve).sort_index()
        daily = pd.DataFrame(daily_rows).set_index("Date").sort_index()

        open_at_end = len(open_positions)
        rejects["accepted"] = len(accepted)
        rejects["generated"] = len(trades)
        stats = PortfolioStats(
            cash_remaining=float(cash),
            open_positions_at_end=open_at_end,
            avg_capital_utilization=float(np.mean(utilization_samples)) if utilization_samples else 0.0,
            rejects=rejects,
        )
        return curve, accepted, daily, stats

    # --- Helpers ----------------------------------------------------------
    def _build_timeline(self, trades, close_prices) -> pd.DatetimeIndex:
        """Union of real trading days between first entry and last exit."""
        start = cfg_start = self.cfg.start_date
        if cfg_start is None:
            start = min(t.entry_date for t in trades)
        end = self.cfg.end_date or max(t.exit_date for t in trades)
        all_days = pd.DatetimeIndex([])
        for series in close_prices.values():
            idx = series.index
            all_days = all_days.union(idx[(idx >= start) & (idx <= end)])
        if len(all_days) == 0:  # fall back to business days if no price index overlaps
            all_days = pd.bdate_range(start, end)
        return all_days

    def _positions_value(self, open_positions, close_prices, date) -> float:
        return sum(
            shares * self._price_on(close_prices, tr.ticker, date, tr.entry_price)
            for tr, shares in open_positions.values()
        )


    @staticmethod
    def _price_on(close_prices, ticker, date, fallback):
        series = close_prices.get(ticker)
        if series is None:
            return fallback
        if date in series.index:
            return float(series.loc[date])
        prior = series.loc[:date]
        if len(prior):
            return float(prior.iloc[-1])
        return fallback


##############################################################################
# Performance statistics
##############################################################################

class PerformanceStats:

    @staticmethod
    def from_trades_and_curve(
        trades: list[SimulatedTrade],
        equity_curve: pd.Series,
        initial_capital: float,
        portfolio_stats: "PortfolioStats | None" = None,
    ) -> dict:

        if not trades:
            return {"total_trades": 0}

        funded = all(t.shares > 0 for t in trades)
        # Portfolio percentages must use the same flat fees as dollar P/L.
        returns = np.array([
            t.net_pl / (t.shares * t.entry_price) if funded else t.net_return
            for t in trades
        ])
        r_multiples = np.array([t.r_multiple for t in trades if t.r_multiple is not None])

        wins = returns[returns > 0]
        losses = returns[returns <= 0]
        outcome = np.array([t.net_pl for t in trades]) if funded else returns
        win_rate = float(np.mean(outcome > 0))

        gross_profit = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(abs(losses.sum())) if len(losses) else 0.0
        profit_factor = PerformanceStats._profit_factor(gross_profit, gross_loss)

        expectancy = float(np.mean(r_multiples)) if len(r_multiples) else None

        daily_returns = (
            equity_curve.pct_change().dropna() if len(equity_curve) > 1 else pd.Series(dtype=float)
        )
        sharpe = PerformanceStats._sharpe(daily_returns)
        sortino = PerformanceStats._sortino(daily_returns)
        volatility = PerformanceStats._annualized_vol(daily_returns)
        max_dd = PerformanceStats._max_drawdown(equity_curve)
        cagr = PerformanceStats._cagr(equity_curve)
        ann_return = PerformanceStats._annualized_arithmetic(daily_returns)
        calmar = cagr / abs(max_dd) if (cagr is not None and max_dd not in (None, 0)) else None

        final_equity = float(equity_curve.iloc[-1]) if len(equity_curve) else initial_capital
        net_profit = final_equity - initial_capital
        total_return_pct = (net_profit / initial_capital * 100.0) if initial_capital else None

        max_dd_dollars = PerformanceStats._max_drawdown_dollars(equity_curve)

        stats = {
            # --- Overall performance ---
            "total_trades": len(trades),
            "net_profit": round(net_profit, 2),
            "total_return_pct": round(total_return_pct, 3) if total_return_pct is not None else None,
            "cagr_pct": round(cagr * 100, 3) if cagr is not None else None,
            "annualized_return_pct": round(ann_return * 100, 3) if ann_return is not None else None,
            "final_equity": round(final_equity, 2),

            # --- Risk ---
            "max_drawdown": round(max_dd_dollars, 2) if max_dd_dollars is not None else None,
            "max_drawdown_pct": round(max_dd * 100, 3) if max_dd is not None else None,
            "volatility_pct": round(volatility * 100, 3) if volatility is not None else None,
            "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
            "sortino_ratio": round(sortino, 3) if sortino is not None else None,
            "calmar_ratio": round(calmar, 3) if calmar is not None else None,

            # --- Trading statistics ---
            "winning_trades": int(np.sum(outcome > 0)),
            "losing_trades": int(np.sum(outcome <= 0)),
            "win_rate": round(win_rate, 4),
            "profit_factor": PerformanceStats._round_pf(profit_factor),
            "expectancy_R": round(expectancy, 3) if expectancy is not None else None,
            "avg_return_pct": round(float(np.mean(returns)) * 100, 3),
            "median_return_pct": round(float(np.median(returns)) * 100, 3),
            "avg_winner_pct": round(float(wins.mean()) * 100, 3) if len(wins) else None,
            "avg_loser_pct": round(float(losses.mean()) * 100, 3) if len(losses) else None,
            "largest_winner_pct": round(float(wins.max()) * 100, 3) if len(wins) else None,
            "largest_loser_pct": round(float(losses.min()) * 100, 3) if len(losses) else None,
            "avg_holding_days": round(float(np.mean([t.holding_days for t in trades])), 2),
            "avg_R": round(float(np.mean(r_multiples)), 3) if len(r_multiples) else None,
            "median_R": round(float(np.median(r_multiples)), 3) if len(r_multiples) else None,
            "largest_R": round(float(r_multiples.max()), 3) if len(r_multiples) else None,
            "smallest_R": round(float(r_multiples.min()), 3) if len(r_multiples) else None,
        }

        # Dollar-based trade statistics (only meaningful for taken trades,
        # which carry non-zero net_pl set by the portfolio simulator).
        stats.update(PerformanceStats._dollar_trade_stats(trades))

        # Portfolio statistics
        if portfolio_stats is not None:
            stats["cash_remaining"] = round(portfolio_stats.cash_remaining, 2)
            stats["open_positions_at_end"] = portfolio_stats.open_positions_at_end
            stats["avg_capital_utilization"] = round(portfolio_stats.avg_capital_utilization, 4)

        return stats

    # --- dollar-denominated trade stats -----------------------------------
    @staticmethod
    def _dollar_trade_stats(trades: list[SimulatedTrade]) -> dict:
        net = np.array([t.net_pl for t in trades])
        if not np.any(net):  # all zero -> these were never taken by a portfolio
            return {}
        wins = net[net > 0]
        losses = net[net <= 0]
        gp = float(wins.sum()) if len(wins) else 0.0
        gl = float(abs(losses.sum())) if len(losses) else 0.0
        pf = PerformanceStats._profit_factor(gp, gl)
        return {
            "avg_win": round(float(wins.mean()), 2) if len(wins) else None,
            "avg_loss": round(float(losses.mean()), 2) if len(losses) else None,
            "largest_winner": round(float(wins.max()), 2) if len(wins) else None,
            "largest_loser": round(float(losses.min()), 2) if len(losses) else None,
            "profit_factor_dollars": PerformanceStats._round_pf(pf),
            "expectancy_dollars": round(float(net.mean()), 2),
            "total_commission_paid": round(float(sum(t.commission_paid for t in trades)), 2),
        }

    # --- primitives -------------------------------------------------------
    @staticmethod
    def _profit_factor(gross_profit, gross_loss):
        if gross_loss > 0:
            return gross_profit / gross_loss
        if gross_profit > 0:
            return float("inf")
        return None

    @staticmethod
    def _round_pf(pf):
        if isinstance(pf, float) and pf != float("inf"):
            return round(pf, 3)
        return pf

    @staticmethod
    def _sharpe(daily_returns, risk_free=0.0, periods_per_year=252):
        if len(daily_returns) < 2 or daily_returns.std() == 0:
            return None
        excess = daily_returns - risk_free / periods_per_year
        return float(excess.mean() / daily_returns.std() * np.sqrt(periods_per_year))

    @staticmethod
    def _sortino(daily_returns, risk_free=0.0, periods_per_year=252):
        if len(daily_returns) < 2:
            return None
        downside = daily_returns[daily_returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            return None
        excess = daily_returns - risk_free / periods_per_year
        return float(excess.mean() / downside.std() * np.sqrt(periods_per_year))

    @staticmethod
    def _annualized_vol(daily_returns, periods_per_year=252):
        if len(daily_returns) < 2:
            return None
        return float(daily_returns.std() * np.sqrt(periods_per_year))

    @staticmethod
    def _annualized_arithmetic(daily_returns, periods_per_year=252):
        if len(daily_returns) < 2:
            return None
        return float(daily_returns.mean() * periods_per_year)

    @staticmethod
    def _max_drawdown(equity_curve):
        if len(equity_curve) < 2:
            return None
        running_max = equity_curve.cummax()
        drawdown = (equity_curve - running_max) / running_max
        return float(drawdown.min())

    @staticmethod
    def _max_drawdown_dollars(equity_curve):
        if len(equity_curve) < 2:
            return None
        running_max = equity_curve.cummax()
        return float((equity_curve - running_max).min())

    @staticmethod
    def _cagr(equity_curve):
        if len(equity_curve) < 2:
            return None
        n_years = (equity_curve.index[-1] - equity_curve.index[0]).days / 365.25
        if n_years <= 0 or equity_curve.iloc[0] <= 0:
            return None
        return float((equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / n_years) - 1)


##############################################################################
# Breakdown analyzers (per-signal scanner validation - runs over ALL signals)
##############################################################################

def _bucket_stats(subset: list[SimulatedTrade]) -> dict:

    if not subset:
        return {"Trades": 0, "WinRate": None, "AvgReturnPct": None, "AvgR": None, "ProfitFactor": None}

    returns = [t.net_return for t in subset]
    r_mults = [t.r_multiple for t in subset if t.r_multiple is not None]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = PerformanceStats._profit_factor(gross_profit, gross_loss)

    return {
        "Trades": len(subset),
        "WinRate": round(len(wins) / len(subset), 4),
        "AvgReturnPct": round(float(np.mean(returns)) * 100, 3),
        "AvgR": round(float(np.mean(r_mults)), 3) if r_mults else None,
        "ProfitFactor": PerformanceStats._round_pf(profit_factor),
    }


def pattern_breakdown(trades: list[SimulatedTrade]) -> pd.DataFrame:
    rows = []
    for pattern in sorted(set(t.pattern for t in trades)):
        subset = [t for t in trades if t.pattern == pattern]
        rows.append({"Pattern": pattern, **_bucket_stats(subset)})
    return pd.DataFrame(rows)


SCORE_BUCKETS = [(90, 100), (80, 89.999), (70, 79.999), (60, 69.999), (0, 59.999)]


def score_bucket_breakdown(trades: list[SimulatedTrade]) -> pd.DataFrame:
    rows = []
    for lo, hi in SCORE_BUCKETS:
        subset = [t for t in trades if lo <= t.score <= hi]
        label = f"{lo:.0f}-{min(hi, 100):.0f}"
        rows.append({"ScoreRange": label, **_bucket_stats(subset)})
    return pd.DataFrame(rows)


CONFIDENCE_BUCKETS = [(0.90, 1.00), (0.80, 0.8999), (0.70, 0.7999), (0.60, 0.6999), (0.0, 0.5999)]


def confidence_bucket_breakdown(trades: list[SimulatedTrade]) -> pd.DataFrame:
    rows = []
    for lo, hi in CONFIDENCE_BUCKETS:
        subset = [t for t in trades if lo <= t.confidence <= hi]
        label = f"{lo*100:.0f}-{min(hi,1.0)*100:.0f}"
        rows.append({"ConfidenceRange": label, **_bucket_stats(subset)})
    return pd.DataFrame(rows)


def time_breakdown(
    trades: list[SimulatedTrade],
    benchmark_close: pd.Series | None = None,
) -> dict[str, pd.DataFrame]:

    empty = {
        "by_year": pd.DataFrame(), "by_quarter": pd.DataFrame(),
        "by_month": pd.DataFrame(), "by_dow": pd.DataFrame(), "by_regime": pd.DataFrame(),
    }

    if not trades:
        return empty

    df = pd.DataFrame({
        "date": [t.entry_date for t in trades],
        "return": [t.net_return for t in trades],
    })
    df["year"] = df["date"].dt.year
    df["quarter"] = df["date"].dt.to_period("Q").astype(str)
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["dow"] = df["date"].dt.day_name()

    def agg(group_col):
        g = df.groupby(group_col)["return"].agg(
            Trades="count", AvgReturn="mean", WinRate=lambda s: (s > 0).mean(),
        )
        return g.reset_index()

    result = {
        "by_year": agg("year"),
        "by_quarter": agg("quarter"),
        "by_month": agg("month"),
        "by_dow": agg("dow"),
    }

    if benchmark_close is not None and len(benchmark_close):
        ema200 = benchmark_close.ewm(span=200, adjust=False).mean()

        def classify(date):
            prior_px = benchmark_close.loc[:date]
            prior_ma = ema200.loc[:date]
            if len(prior_px) == 0 or len(prior_ma) == 0:
                return "Unknown"
            px = float(prior_px.iloc[-1])
            ma = float(prior_ma.iloc[-1])
            if px > ma * 1.02:
                return "Bull"
            if px < ma * 0.98:
                return "Bear"
            return "Sideways"

        df["regime"] = df["date"].apply(classify)
        result["by_regime"] = agg("regime")
    else:
        result["by_regime"] = pd.DataFrame()

    return result


##############################################################################
# Report export
##############################################################################

# Column order for the spec-compliant completed-trade log.
TRADE_LOG_COLUMNS = [
    "Date", "Ticker", "Entry Date", "Exit Date", "Entry Price", "Exit Price",
    "ATR at Entry", "Position Size", "Commission Paid", "Gross P/L", "Net P/L",
    "Return %", "Holding Days", "Exit Reason",
]


def _trade_log_dataframe(trades: list[SimulatedTrade]) -> pd.DataFrame:
    rows = []
    for t in trades:
        rows.append({
            "Date": t.signal_date,
            "Ticker": t.ticker,
            "Entry Date": t.entry_date,
            "Exit Date": t.exit_date,
            "Entry Price": round(t.entry_price, 4),
            "Exit Price": round(t.exit_price, 4),
            "ATR at Entry": round(t.atr_at_entry, 4),
            "Position Size": t.shares,
            "Commission Paid": round(t.commission_paid, 2),
            "Gross P/L": round(t.gross_pl, 2),
            "Net P/L": round(t.net_pl, 2),
            "Return %": round(t.return_pct, 3),
            "Holding Days": t.holding_days,
            "Exit Reason": t.exit_reason,
        })
    return pd.DataFrame(rows, columns=TRADE_LOG_COLUMNS)


class ReportExporter:

    def __init__(self, output_dir="backtest_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_csvs(
        self,
        signals: list[Signal],
        trades: list[SimulatedTrade],
        accepted_trades: list[SimulatedTrade],
        summary_stats: dict,
        pattern_stats: pd.DataFrame,
        daily_portfolio: pd.DataFrame,
    ):
        pd.DataFrame([asdict(s) for s in signals]).to_csv(self.output_dir / "signals.csv", index=False)
        pd.DataFrame([asdict(t) for t in trades]).to_csv(self.output_dir / "trades.csv", index=False)
        pd.DataFrame([summary_stats]).to_csv(self.output_dir / "summary.csv", index=False)
        pattern_stats.to_csv(self.output_dir / "pattern_statistics.csv", index=False)

        # Spec deliverables: completed-trade log and daily portfolio value.
        _trade_log_dataframe(accepted_trades).to_csv(
            self.output_dir / "trade_log.csv", index=False
        )
        if daily_portfolio is not None and len(daily_portfolio):
            daily_portfolio.to_csv(self.output_dir / "daily_portfolio_value.csv")

    def export_charts(
        self,
        equity_curve: pd.Series,
        trades: list[SimulatedTrade],
        score_buckets: pd.DataFrame,
        confidence_buckets: pd.DataFrame,
    ):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if len(equity_curve) > 1:
            fig, ax = plt.subplots(figsize=(10, 4))
            equity_curve.plot(ax=ax, title="Equity Curve")
            ax.set_ylabel("Portfolio Value ($)")
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            fig.savefig(self.output_dir / "equity_curve.png", dpi=120)
            plt.close(fig)

            running_max = equity_curve.cummax()
            drawdown = (equity_curve - running_max) / running_max * 100
            fig, ax = plt.subplots(figsize=(10, 4))
            drawdown.plot(ax=ax, title="Drawdown (%)", color="red")
            fig.tight_layout()
            fig.savefig(self.output_dir / "drawdown_curve.png", dpi=120)
            plt.close(fig)

            monthly = equity_curve.resample("ME").last().pct_change().dropna() * 100
            if len(monthly) >= 2:
                heat = monthly.to_frame("ret")
                heat["year"] = heat.index.year
                heat["month"] = heat.index.month
                pivot = heat.pivot(index="year", columns="month", values="ret")
                fig, ax = plt.subplots(figsize=(10, 4))
                im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto")
                ax.set_xticks(range(len(pivot.columns)))
                ax.set_xticklabels(pivot.columns)
                ax.set_yticks(range(len(pivot.index)))
                ax.set_yticklabels(pivot.index)
                ax.set_title("Monthly Returns (%)")
                fig.colorbar(im, ax=ax)
                fig.tight_layout()
                fig.savefig(self.output_dir / "monthly_returns_heatmap.png", dpi=120)
                plt.close(fig)

        if trades:
            returns_pct = [t.net_return * 100 for t in trades]
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.hist(returns_pct, bins=40)
            ax.set_title("Distribution of Returns (%)")
            fig.tight_layout()
            fig.savefig(self.output_dir / "returns_distribution.png", dpi=120)
            plt.close(fig)

            wins = [r for r in returns_pct if r > 0]
            losses = [r for r in returns_pct if r <= 0]
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.hist([wins, losses], bins=20, label=["Wins", "Losses"], color=["green", "red"])
            ax.legend()
            ax.set_title("Win/Loss Histogram")
            fig.tight_layout()
            fig.savefig(self.output_dir / "win_loss_histogram.png", dpi=120)
            plt.close(fig)

        if len(score_buckets):
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(score_buckets["ScoreRange"], score_buckets["WinRate"].fillna(0))
            ax.set_title("Score vs Win Rate")
            fig.tight_layout()
            fig.savefig(self.output_dir / "score_vs_winrate.png", dpi=120)
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(score_buckets["ScoreRange"], score_buckets["AvgReturnPct"].fillna(0))
            ax.set_title("Score vs Average Return")
            fig.tight_layout()
            fig.savefig(self.output_dir / "score_vs_avgreturn.png", dpi=120)
            plt.close(fig)

        if len(confidence_buckets):
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(confidence_buckets["ConfidenceRange"], confidence_buckets["WinRate"].fillna(0))
            ax.set_title("Confidence vs Win Rate")
            fig.tight_layout()
            fig.savefig(self.output_dir / "confidence_vs_winrate.png", dpi=120)
            plt.close(fig)


##############################################################################
# Multiprocessing worker (module-level so it's picklable)
##############################################################################

def _classify_regime(benchmark_close: pd.Series) -> pd.Series:
    """
    Four-state benchmark regime (Strong Bull / Weak Bull / Sideways / Bear)
    from price vs its 200-EMA and the EMA slope. Point-in-time (EMA uses
    only past data). Kept inline so the engine has no research-layer import.
    """
    ema200 = benchmark_close.ewm(span=200, adjust=False).mean()
    slope = ema200.diff(20)
    dist = (benchmark_close / ema200 - 1.0) * 100.0
    regime = pd.Series("Sideways", index=benchmark_close.index)
    regime[(dist > 5) & (slope > 0)] = "Strong Bull"
    regime[(dist > 0) & (dist <= 5) & (slope > 0)] = "Weak Bull"
    regime[dist < -3] = "Bear"
    return regime


def _apply_regime_gate(trades, benchmark_close, blocked, entry_method="next_open") -> list:
    """Drop trades whose entry-date benchmark regime is in `blocked`."""
    if not blocked or benchmark_close is None or not len(benchmark_close):
        return trades
    regime = _classify_regime(benchmark_close)
    blocked = set(blocked)
    kept = []
    for t in trades:
        known = regime.index < t.entry_date if entry_method == "next_open" else regime.index <= t.entry_date
        prior = regime.loc[known]
        r = prior.iloc[-1] if len(prior) else "Unknown"
        if r not in blocked:
            kept.append(t)
    return kept


def _run_single_ticker(ticker, raw_df, detectors, cfg, feature_extractor=None):
    if cfg.end_date is not None:
        raw_df = raw_df.loc[:cfg.end_date]
    screener = WalkForwardScreener(detectors, cfg, feature_extractor)
    with timer("scan_ticker"):
        signals = screener.scan_ticker(ticker, raw_df)
    with timer("signals_to_trades"):
        trades = signals_to_trades(signals, raw_df, cfg)
    return ticker, signals, trades


##############################################################################
# Result container
##############################################################################

@dataclass
class BacktestResult:

    signals: list[Signal]
    trades: list[SimulatedTrade]
    accepted_trades: list[SimulatedTrade]
    equity_curve: pd.Series
    summary: dict
    pattern_stats: pd.DataFrame
    score_buckets: pd.DataFrame
    confidence_buckets: pd.DataFrame
    time_breakdown: dict
    config: BacktestConfig
    daily_portfolio: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_stats: PortfolioStats | None = None

    def export(self, output_dir="backtest_results"):
        exporter = ReportExporter(output_dir)
        exporter.export_csvs(
            self.signals, self.trades, self.accepted_trades,
            self.summary, self.pattern_stats, self.daily_portfolio,
        )
        exporter.export_charts(
            self.equity_curve, self.trades, self.score_buckets, self.confidence_buckets
        )
        return str(Path(output_dir).resolve())

    def print_report(self) -> None:
        """Human-readable console report of the headline statistics."""
        print(_format_report(self))


##############################################################################
# Console report formatting
##############################################################################

def _fmt(value, kind="raw"):
    if value is None:
        return "n/a"
    if kind == "money":
        return f"${value:,.2f}"
    if kind == "pct":
        return f"{value:.2f}%"
    return f"{value}"


def _format_report(result: "BacktestResult") -> str:
    s = result.summary
    lines = []
    add = lines.append

    add("=" * 60)
    add("BACKTEST PERFORMANCE REPORT")
    add("=" * 60)
    cfg = result.config
    period = f"{cfg.start_date.date() if cfg.start_date else 'begin'} -> " \
             f"{cfg.end_date.date() if cfg.end_date else 'end'}"
    add(f"Period: {period}   Initial capital: {_fmt(cfg.initial_capital, 'money')}")

    if s.get("total_trades", 0) == 0:
        add("No trades were taken.")
        return "\n".join(lines)

    add("")
    add("-- Overall Performance --")
    add(f"  Net Profit            : {_fmt(s.get('net_profit'), 'money')}")
    add(f"  Total Return          : {_fmt(s.get('total_return_pct'), 'pct')}")
    add(f"  CAGR                  : {_fmt(s.get('cagr_pct'), 'pct')}")
    add(f"  Annualized Return     : {_fmt(s.get('annualized_return_pct'), 'pct')}")
    add(f"  Final Portfolio Value : {_fmt(s.get('final_equity'), 'money')}")

    add("")
    add("-- Risk --")
    add(f"  Max Drawdown          : {_fmt(s.get('max_drawdown'), 'money')}")
    add(f"  Max Drawdown %        : {_fmt(s.get('max_drawdown_pct'), 'pct')}")
    add(f"  Volatility (ann.)     : {_fmt(s.get('volatility_pct'), 'pct')}")
    add(f"  Sharpe Ratio          : {_fmt(s.get('sharpe_ratio'))}")
    add(f"  Sortino Ratio         : {_fmt(s.get('sortino_ratio'))}")
    add(f"  Calmar Ratio          : {_fmt(s.get('calmar_ratio'))}")

    add("")
    add("-- Trading Statistics --")
    add(f"  Number of Trades      : {s.get('total_trades')}")
    add(f"  Winning Trades        : {s.get('winning_trades')}")
    add(f"  Losing Trades         : {s.get('losing_trades')}")
    add(f"  Win Rate              : {_fmt((s.get('win_rate') or 0) * 100, 'pct')}")
    add(f"  Average Win           : {_fmt(s.get('avg_win'), 'money')}")
    add(f"  Average Loss          : {_fmt(s.get('avg_loss'), 'money')}")
    add(f"  Profit Factor         : {_fmt(s.get('profit_factor_dollars') or s.get('profit_factor'))}")
    add(f"  Expectancy / trade    : {_fmt(s.get('expectancy_dollars'), 'money')}")
    add(f"  Avg Holding (days)    : {_fmt(s.get('avg_holding_days'))}")
    add(f"  Largest Winner        : {_fmt(s.get('largest_winner'), 'money')}")
    add(f"  Largest Loser         : {_fmt(s.get('largest_loser'), 'money')}")

    add("")
    add("-- Portfolio Statistics --")
    add(f"  Cash Remaining        : {_fmt(s.get('cash_remaining'), 'money')}")
    add(f"  Open Positions (end)  : {s.get('open_positions_at_end')}")
    add(f"  Avg Capital Util.     : {_fmt((s.get('avg_capital_utilization') or 0) * 100, 'pct')}")
    add(f"  Total Commission Paid : {_fmt(s.get('total_commission_paid'), 'money')}")
    add("=" * 60)
    return "\n".join(lines)


##############################################################################
# Top-level engine
##############################################################################

class BacktestEngine:

    def __init__(self, detectors, cfg: BacktestConfig | None = None,
                 feature_extractor=None, sector_map=None):
        self.detectors = detectors
        self.cfg = cfg or BacktestConfig()
        self.portfolio_sim = PortfolioSimulator(self.cfg, sector_map)
        # When set (a research.FeatureExtractor), every signal/trade carries
        # its entry-time feature vector for the research database.
        self.feature_extractor = feature_extractor

    def run(
        self,
        data: dict[str, pd.DataFrame],
        benchmark: pd.DataFrame | None = None,
    ) -> BacktestResult:

        raw_data = {
            ticker: df.loc[:self.cfg.end_date, ["Open", "High", "Low", "Close", "Volume"]].copy()
            if self.cfg.end_date is not None else df[["Open", "High", "Low", "Close", "Volume"]].copy()
            for ticker, df in data.items()
        }

        all_signals: list[Signal] = []
        all_trades: list[SimulatedTrade] = []
        close_prices: dict[str, pd.Series] = {}

        # Workers own independent timing state; parent reports only the outer
        # multiprocessing phase, not worker scan_ticker/signals_to_trades totals.
        _scan_phase_start = time.perf_counter()
        if self.cfg.use_multiprocessing:
            with ProcessPoolExecutor(max_workers=self.cfg.max_workers) as executor:
                futures = [
                    executor.submit(
                        _run_single_ticker, ticker, df, self.detectors,
                        self.cfg, self.feature_extractor,
                    )
                    for ticker, df in raw_data.items()
                ]
                for future in tqdm(
                    futures, desc="Scanning", unit="ticker", disable=not self.cfg.show_progress
                ):
                    ticker, signals, trades = future.result()
                    all_signals.extend(signals)
                    all_trades.extend(trades)
                    close_prices[ticker] = raw_data[ticker]["Close"]
            _record_elapsed("scan_phase.multiprocessing", _scan_phase_start)
        else:
            for ticker, df in tqdm(
                raw_data.items(), desc="Scanning", unit="ticker",
                disable=not self.cfg.show_progress, total=len(raw_data),
            ):
                _, signals, trades = _run_single_ticker(
                    ticker, df, self.detectors, self.cfg, self.feature_extractor
                )
                all_signals.extend(signals)
                all_trades.extend(trades)
                close_prices[ticker] = df["Close"]
            _record_elapsed("scan_phase.sequential", _scan_phase_start)

        benchmark_close = benchmark["Close"] if benchmark is not None else None

        # Drawdown control: optionally refuse new entries in blocked regimes
        # (e.g. Bear). Validated to reduce max drawdown out-of-sample.
        portfolio_trades = _apply_regime_gate(
            all_trades, benchmark_close, self.cfg.block_entry_regimes, self.cfg.entry_method
        )

        # Graded regime exposure: scale the daily position cap by regime.
        regime_by_date = (
            _classify_regime(benchmark_close)
            if (benchmark_close is not None and self.cfg.regime_position_scale)
            else None
        )

        with timer("portfolio_sim.run"):
            equity_curve, accepted_trades, daily_portfolio, portfolio_stats = \
                self.portfolio_sim.run(portfolio_trades, close_prices, regime_by_date)

        # BUG FIX: headline performance is measured on the trades actually
        # taken by the portfolio, so it matches the equity curve. The
        # per-signal breakdowns below still run over *all* signals - that is
        # a deliberate, separate diagnostic of the raw scanner's edge.
        summary = PerformanceStats.from_trades_and_curve(
            accepted_trades, equity_curve, self.cfg.initial_capital, portfolio_stats
        )

        return BacktestResult(
            signals=all_signals,
            trades=all_trades,
            accepted_trades=accepted_trades,
            equity_curve=equity_curve,
            summary=summary,
            pattern_stats=pattern_breakdown(all_trades),
            score_buckets=score_bucket_breakdown(all_trades),
            confidence_buckets=confidence_bucket_breakdown(all_trades),
            time_breakdown=time_breakdown(all_trades, benchmark_close),
            config=self.cfg,
            daily_portfolio=daily_portfolio,
            portfolio_stats=portfolio_stats,
        )
