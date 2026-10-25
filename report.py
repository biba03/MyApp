"""
Generate scan report.
"""

import pandas as pd


class Report:

    @staticmethod
    def dataframe(results, market=None, asof=None):

        results = list(results)
        rows = []

        for r in results:

            rows.append({

                "Ticker": r.ticker,

                "Pattern": r.pattern,

                "Score": round(r.score,2),

                "RawDetectorScore": (r.metadata or {}).get("RawDetectorScore"),

                "SelectionScoreBasis": "Live composite",

                "Quality": round(r.quality,2),

                "Confidence": round(r.confidence*100,1),

                "RS": r.rs_rating if r.rs_rating is not None else None,

                "SectorRank": r.sector_rank,

                "IndustryRank": r.industry_rank,

                "Liquidity": round(r.liquidity_score, 1) if r.liquidity_score is not None else None,

                "ExtATR50": r.atr_extension_50sma,

                "Regime": round(r.regime_score, 1) if r.regime_score is not None else None,

                "TrendTemplate": r.trend_template,

                "Stage": r.stage,

                "AccumDays": r.accum_days,

                "DistDays": r.dist_days,

                "Entry": round(r.entry,2),

                "Stop": round(r.stop,2),

                "Target": round(r.target,2),

                "RR": round(r.rr,2),

            })

        from score_diagnostics import ranking_breakdown, timing_diagnostics
        # Add explanation fields without replacing existing scores or trading values.
        for row, result in zip(rows, results):
            row.update(ranking_breakdown(result))
            for field in ('PatternTriggerPrice','PatternTriggerKind','PatternTriggerSource','DetectorReferencePrice','DetectorReferenceIncludesSignalBar'):
                row[field] = (result.metadata or {}).get(field)
            if market is not None:
                row.update(timing_diagnostics(market.get(result.ticker), asof))
        return pd.DataFrame(rows)