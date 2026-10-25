"""
alerts.py

Turns scan results into alerts. Ships with console and file (JSON
log) backends that work with no setup; email is wired up but disabled
until you fill in real SMTP credentials.
"""

from __future__ import annotations

import json
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import config


##############################################################################
# Alert
##############################################################################

@dataclass(slots=True)
class Alert:

    ticker: str

    pattern: str

    score: float

    entry: float

    stop: float

    target: float

    rr: float

    rs_rating: float | None

    created_at: str


def alert_from_ranked_stock(ranked_stock) -> Alert:

    return Alert(

        ticker=ranked_stock.ticker,

        pattern=ranked_stock.pattern,

        score=round(ranked_stock.score, 2),

        entry=round(ranked_stock.entry, 2),

        stop=round(ranked_stock.stop, 2),

        target=round(ranked_stock.target, 2),

        rr=round(ranked_stock.rr, 2),

        rs_rating=ranked_stock.rs_rating,

        created_at=datetime.now().isoformat(timespec="seconds"),

    )


##############################################################################
# Backends
##############################################################################

class AlertBackend(ABC):

    @abstractmethod
    def send(self, alerts: list[Alert]) -> None:
        ...


class ConsoleBackend(AlertBackend):
    """
    Zero-setup default: just prints. Good for notebook use.
    """

    def send(self, alerts: list[Alert]) -> None:

        if not alerts:

            print("No new setups.")

            return

        print(f"\n{len(alerts)} new setup(s):")

        for alert in alerts:

            rs = f"RS {alert.rs_rating}" if alert.rs_rating is not None else "RS n/a"

            print(
                f"  {alert.ticker:<6} {alert.pattern:<14} "
                f"score={alert.score:<6} {rs:<8} "
                f"entry={alert.entry} stop={alert.stop} target={alert.target} "
                f"rr={alert.rr}"
            )


class FileBackend(AlertBackend):
    """
    Appends every alert batch to a JSON-lines log
    (config.LOG_DIR/alerts.jsonl) so alerts survive across sessions
    and can be reviewed or fed into another tool later.
    """

    def __init__(self, path: Path | None = None):

        self.path = Path(path) if path else (config.LOG_DIR / "alerts.jsonl")

        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, alerts: list[Alert]) -> None:

        if not alerts:

            return

        with open(self.path, "a") as f:

            for alert in alerts:

                f.write(json.dumps(asdict(alert)) + "\n")


class EmailBackend(AlertBackend):
    """
    Disabled by default - fill in real SMTP credentials (an app
    password, not your login password, for most providers) before
    using this. Raises rather than silently failing if you try to use
    it without configuring it, so a misconfigured backend doesn't
    just look like "no alerts today".
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        to_address: str,
        enabled: bool = False,
    ):

        self.smtp_host = smtp_host

        self.smtp_port = smtp_port

        self.username = username

        self.password = password

        self.to_address = to_address

        self.enabled = enabled

    def send(self, alerts: list[Alert]) -> None:

        if not alerts:

            return

        if not self.enabled:

            raise RuntimeError(
                "EmailBackend is not enabled. Set enabled=True and fill in "
                "real SMTP credentials in alerts.py before using it - "
                "otherwise alerts will silently never arrive."
            )

        body = "\n".join(
            f"{a.ticker} {a.pattern} score={a.score} entry={a.entry} "
            f"stop={a.stop} target={a.target} rr={a.rr}"
            for a in alerts
        )

        message = EmailMessage()

        message["Subject"] = f"Shoryuken Scanner: {len(alerts)} new setup(s)"

        message["From"] = self.username

        message["To"] = self.to_address

        message.set_content(body)

        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as smtp:

            smtp.login(self.username, self.password)

            smtp.send_message(message)


##############################################################################
# Manager
##############################################################################

class AlertManager:
    """
    Fans a batch of RankedStock results out to one or more backends,
    and (optionally) only alerts on tickers/patterns it hasn't already
    alerted on, so re-running a scan on the same setups doesn't spam
    every backend again.
    """

    def __init__(
        self,
        backends: list[AlertBackend] | None = None,
        dedupe: bool = True,
    ):

        self.backends = backends if backends is not None else [ConsoleBackend()]

        self.dedupe = dedupe

        self._seen: set[tuple[str, str]] = set()

    def notify(self, ranked_stocks) -> list[Alert]:

        alerts = []

        for stock in ranked_stocks:

            key = (stock.ticker, stock.pattern)

            if self.dedupe and key in self._seen:

                continue

            self._seen.add(key)

            alerts.append(alert_from_ranked_stock(stock))

        for backend in self.backends:

            backend.send(alerts)

        return alerts
