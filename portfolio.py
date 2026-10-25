"""
portfolio.py

Position sizing and open-position tracking.

Turns a RankedStock signal into an actual share count sized to risk a
fixed fraction of account equity, and tracks open/closed positions so
exposure limits (e.g. from MarketRegimeEngine) can be enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import config


##############################################################################
# Position
##############################################################################

@dataclass(slots=True)
class Position:

    ticker: str

    pattern: str

    shares: int

    entry: float

    stop: float

    target: float

    opened_at: datetime

    closed_at: datetime | None = None

    exit_price: float | None = None

    exit_reason: str | None = None  # "stop" / "target" / "manual"

    @property
    def risk_per_share(self) -> float:

        return self.entry - self.stop

    @property
    def dollar_risk(self) -> float:

        return self.risk_per_share * self.shares

    @property
    def dollar_cost(self) -> float:

        return self.entry * self.shares

    @property
    def is_open(self) -> bool:

        return self.closed_at is None

    @property
    def pnl(self) -> float | None:

        if self.exit_price is None:

            return None

        return (self.exit_price - self.entry) * self.shares

    @property
    def r_multiple(self) -> float | None:

        if self.exit_price is None or self.risk_per_share <= 0:

            return None

        return (self.exit_price - self.entry) / self.risk_per_share


##############################################################################
# Position sizing
##############################################################################

class PositionSizer:
    """
    Fixed-fractional position sizing: risk a constant percentage of
    account equity on every trade, sized off the setup's own stop
    distance rather than a flat share count.
    """

    def __init__(
        self,
        account_size: float = config.ACCOUNT_SIZE,
        risk_per_trade: float = config.RISK_PER_TRADE,
    ):

        self.account_size = account_size

        self.risk_per_trade = risk_per_trade

    def shares_for(
        self,
        entry: float,
        stop: float,
        risk_multiplier: float = 1.0,
    ) -> int:
        """
        risk_multiplier lets a caller scale position size down in a
        weak/bearish MarketRegime (e.g. MarketRegime.risk_multiplier)
        without touching the stop-loss distance itself.
        """

        risk_per_share = entry - stop

        if risk_per_share <= 0:

            return 0

        dollar_risk = self.account_size * self.risk_per_trade * risk_multiplier

        shares = int(dollar_risk / risk_per_share)

        return max(shares, 0)


##############################################################################
# Portfolio
##############################################################################

class Portfolio:
    """
    Tracks open and closed positions and enforces a maximum number of
    concurrent positions / total exposure so a scan's top-ranked
    signals don't all get taken blindly regardless of what's already
    on the book.
    """

    def __init__(
        self,
        account_size: float = config.ACCOUNT_SIZE,
        max_positions: int = 10,
        max_exposure: float = 1.0,
    ):

        self.account_size = account_size

        self.max_positions = max_positions

        self.max_exposure = max_exposure

        self.positions: list[Position] = []

        self.sizer = PositionSizer(account_size)

    ####################################################################
    # Queries
    ####################################################################

    @property
    def open_positions(self) -> list[Position]:

        return [p for p in self.positions if p.is_open]

    @property
    def closed_positions(self) -> list[Position]:

        return [p for p in self.positions if not p.is_open]

    @property
    def current_exposure(self) -> float:
        """
        Fraction of account currently deployed (sum of open positions'
        cost basis / account size).
        """

        deployed = sum(p.dollar_cost for p in self.open_positions)

        return deployed / self.account_size if self.account_size else 0.0

    @property
    def is_holding(self):

        return {p.ticker for p in self.open_positions}

    ####################################################################
    # Opening positions
    ####################################################################

    def can_open(self, ticker: str) -> bool:

        if ticker in self.is_holding:

            return False

        if len(self.open_positions) >= self.max_positions:

            return False

        if self.current_exposure >= self.max_exposure:

            return False

        return True

    def open_position(
        self,
        ranked_stock,
        risk_multiplier: float = 1.0,
        opened_at: datetime | None = None,
    ) -> Position | None:
        """
        Accepts a RankedStock (from ranking.py) and opens a sized
        position if there's room in the portfolio. Returns None if
        the portfolio is already full/at max exposure, or the setup
        has no valid risk (entry <= stop).
        """

        if not self.can_open(ranked_stock.ticker):

            return None

        shares = self.sizer.shares_for(
            ranked_stock.entry,
            ranked_stock.stop,
            risk_multiplier,
        )

        if shares <= 0:

            return None

        position = Position(

            ticker=ranked_stock.ticker,

            pattern=ranked_stock.pattern,

            shares=shares,

            entry=ranked_stock.entry,

            stop=ranked_stock.stop,

            target=ranked_stock.target,

            opened_at=opened_at or datetime.now(),

        )

        self.positions.append(position)

        return position

    ####################################################################
    # Closing positions
    ####################################################################

    def close_position(
        self,
        position: Position,
        exit_price: float,
        exit_reason: str = "manual",
        closed_at: datetime | None = None,
    ):

        position.exit_price = exit_price

        position.exit_reason = exit_reason

        position.closed_at = closed_at or datetime.now()

    def check_exits(self, latest_prices: dict[str, tuple[float, float]]):
        """
        For every open position, check whether the latest bar's
        (low, high) would have hit its stop or target, and close it
        if so. Stop is checked before target when both are touched
        in the same bar (conservative assumption).

        latest_prices: {ticker: (low, high)}
        """

        closed = []

        for position in self.open_positions:

            bar = latest_prices.get(position.ticker)

            if bar is None:

                continue

            low, high = bar

            if low <= position.stop:

                self.close_position(position, position.stop, "stop")

                closed.append(position)

            elif high >= position.target:

                self.close_position(position, position.target, "target")

                closed.append(position)

        return closed

    ####################################################################
    # Reporting
    ####################################################################

    def summary(self) -> dict:

        closed = self.closed_positions

        wins = [p for p in closed if (p.pnl or 0) > 0]

        return {

            "open_positions": len(self.open_positions),

            "closed_positions": len(closed),

            "win_rate": len(wins) / len(closed) if closed else None,

            "total_pnl": sum(p.pnl for p in closed if p.pnl is not None),

            "current_exposure": round(self.current_exposure, 3),

        }
