"""Independent Qullamaggie candidate gate; reporting only, no network or writes."""
import numpy as np
import pandas as pd


def qullamaggie_candidates(audit):
    """Use the existing ATR calculation and cap validity, without leadership gates."""
    columns = ['Ticker', 'ATRPct', 'MarketCapUSD', 'PassCapData']
    missing = set(columns) - set(audit.columns)
    if missing:
        raise ValueError(f'Missing audit columns: {sorted(missing)}')
    atr = pd.to_numeric(audit.ATRPct, errors='coerce')
    cap = pd.to_numeric(audit.MarketCapUSD, errors='coerce')
    valid = audit.PassCapData.map(lambda v: isinstance(v, (bool, np.bool_)) and bool(v))
    passed = valid & np.isfinite(atr) & atr.ge(3) & np.isfinite(cap) & cap.ge(500_000_000)
    return set(audit.loc[passed, 'Ticker'])
