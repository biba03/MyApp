"""
config.py
==========

Global configuration for Momentum Pro Scanner.

Author: Your Name
"""

from pathlib import Path

##########################################################################
# Project
##########################################################################

PROJECT_NAME = "Momentum Pro Scanner"

ROOT = Path(__file__).resolve().parent

CACHE_DIR = ROOT / "cache"
DATA_DIR = ROOT / "data"
EXPORT_DIR = ROOT / "exports"
CHART_DIR = ROOT / "charts"
LOG_DIR = ROOT / "logs"

for folder in (
    CACHE_DIR,
    DATA_DIR,
    EXPORT_DIR,
    CHART_DIR,
    LOG_DIR,
):
    folder.mkdir(parents=True, exist_ok=True)

##########################################################################
# Download
##########################################################################

START_DATE = "2018-01-01"

AUTO_UPDATE = True

MAX_DOWNLOAD_THREADS = 8

DOWNLOAD_RETRIES = 3

REQUEST_TIMEOUT = 20

##########################################################################
# Universe
##########################################################################

UNIVERSE = "COMBINED"

SUPPORTED_UNIVERSES = [
    "SP500",
    "NASDAQ100",
    "SP400",
    "SP600",
    "COMBINED",
    "CUSTOM",
]

# QQQ/IWM are always included so MarketRegimeEngine has all three legs
# (SPY/QQQ/IWM) - without them the market-regime component is inert.
CUSTOM_TICKERS = ["QQQ", "IWM"]

##########################################################################
# Liquidity Filters
##########################################################################

MIN_PRICE = 10

MAX_PRICE = 10000

MIN_DOLLAR_VOLUME = 20_000_000

MIN_AVG_VOLUME = 500_000

##########################################################################
# Relative Strength
##########################################################################

BENCHMARK = "SPY"

RS_LOOKBACK = 126

##########################################################################
# Hard entry filters (screening gates)
##########################################################################
#
# Applied in Scanner.scan_stock BEFORE pattern detection: a stock failing
# any enabled gate is excluded outright (not merely scored lower). Each is
# individually switchable so the behaviour is tunable and testable.

# Strong relative strength: exclude anything below this RS rating (1-99).
# Only enforced when an RS rating is available (a benchmark was passed).
MIN_RS_RATING = 80

# Strong group/sector: exclude anything whose sector rank (1-99) is below
# this. Only enforced when sector ranks are available.
MIN_SECTOR_RANK = 50

# Price above the 50- and 200-period SMAs (exclude stocks below them).
REQUIRE_ABOVE_SMA50 = True
REQUIRE_ABOVE_SMA200 = True

# Overextension guard: exclude stocks trading more than this many ATRs
# above their 50 SMA (chasing extended names). Set to None to disable the
# hard filter. Currently DISABLED - the backtest showed extension was
# positively related to returns for this trend system - but the extension
# value is still computed and reported per setup (Report column "ExtATR50")
# so you can watch it. Set to a number (e.g. 5.0) to re-enable the gate.
MAX_ATR_EXTENSION_FROM_SMA50 = None

# Good dollar volume: exclude anything below MIN_DOLLAR_VOLUME as a hard
# gate (in addition to its use in the liquidity score).
REQUIRE_MIN_DOLLAR_VOLUME = True

##########################################################################
# Fundamental overlay (Minervini SEPA) - see fundamentals.py
##########################################################################
#
# Orthogonal to the price/volume features (which the backtest showed have
# ~zero predictive power), so this is the most promising place to add new
# edge. OFF by default because it needs a fundamental data feed wired up.

REQUIRE_FUNDAMENTALS = False        # apply the EPS/sales growth gate
MIN_EPS_GROWTH = 0.25               # >= 25% latest-quarter YoY EPS growth
MIN_SALES_GROWTH = 0.20             # >= 20% latest-quarter YoY revenue growth
REQUIRE_KNOWN_FUNDAMENTALS = False  # if True, exclude tickers with no data
                                    # (default False = missing data fails open)

##########################################################################
# Moving Averages
##########################################################################

EMA_PERIODS = [
    10,
    20,
    21,
    50,
    100,
    150,
    200,
]

##########################################################################
# ATR
##########################################################################

ATR_PERIOD = 14

ATR_STOP_MULTIPLIER = 1.0

##########################################################################
# Relative Volume
##########################################################################

RVOL_PERIOD = 20

##########################################################################
# Trend Template
##########################################################################

TREND_TEMPLATE = dict(

    require_price_above_150=True,

    require_price_above_200=True,

    require_150_above_200=True,

    require_200_rising=True,

    require_price_above_50=True,

)

##########################################################################
# Pattern Detection
##########################################################################

PIVOT_LEFT = 3

PIVOT_RIGHT = 3

MIN_PIVOT_HIGHS = 3

MIN_PIVOT_LOWS = 2

MAX_PULLBACK_BARS = 25

MIN_CONTRACTION = 0.20

MAX_WEDGE_APEX = 0.80

MIN_BREAKOUT_BODY = 0.55

MIN_PATTERN_SCORE = 70

##########################################################################
# Shoryuken
##########################################################################

ENABLE_SHORYUKEN = True

SHORYUKEN_MIN_SCORE = 75

##########################################################################
# VCP
##########################################################################

ENABLE_VCP = True

VCP_MIN_CONTRACTIONS = 3

VCP_MAX_DEPTH = 0.30

##########################################################################
# DTRP
##########################################################################

ENABLE_DTRP = True

MAX_DAILY_RANGE = 0.025

##########################################################################
# Pocket Pivot
##########################################################################

ENABLE_POCKET_PIVOT = True

##########################################################################
# Episodic Pivot
##########################################################################

ENABLE_EPISODIC = True

##########################################################################
# Flat Base
##########################################################################

ENABLE_FLAT_BASE = True

FLAT_BASE_MAX_DEPTH = 0.15

FLAT_BASE_LENGTH = 25

##########################################################################
# Cup & Handle
##########################################################################

ENABLE_CUP_HANDLE = True

CUP_MIN_DEPTH = 0.12

CUP_MAX_DEPTH = 0.50

HANDLE_MAX_DEPTH = 0.15

##########################################################################
# Gap
##########################################################################

MIN_GAP = 0.02

MAX_GAP = 0.12

##########################################################################
# Volume
##########################################################################

MIN_BREAKOUT_RVOL = 1.8

VOLUME_DRYUP_THRESHOLD = 0.70

##########################################################################
# Chart
##########################################################################

SAVE_CHARTS = True

CHART_WIDTH = 16

CHART_HEIGHT = 9

CHART_DPI = 150

##########################################################################
# Ranking
##########################################################################

TOP_RESULTS = 50

##########################################################################
# Score Weights
##########################################################################
#
# How RankingEngine.score() combines everything it knows about a
# setup into one number. Must sum to 1.0 - RankingEngine checks this
# and raises rather than silently normalizing, since a silent
# renormalization would hide a typo here.
#
# rs/liquidity/regime default to a neutral 50 when not supplied (e.g.
# no benchmark was passed to Scanner.scan()), so omitting them doesn't
# crash - it just means those weights contribute a wash instead of a
# real signal.

RANKING_WEIGHTS = dict(
    quality=0.25,    # setup quality
    confidence=0.0,  # rule coverage: display only
    rr=0.10,         # existing capped planned reward/risk
    rs=0.40,         # stock relative strength
    sector=0.25,     # sector strength
    liquidity=0.0,   # existing liquidity filter, no ranking points
    regime=0.0,      # market-wide context, no ranking points
)

##########################################################################
# Position Sizing
##########################################################################

ACCOUNT_SIZE = 100000

RISK_PER_TRADE = 0.01

##########################################################################
# Logging
##########################################################################

LOG_LEVEL = "INFO"

##########################################################################
# Export
##########################################################################

EXPORT_CSV = True

EXPORT_EXCEL = True

EXPORT_JSON = False

##########################################################################
# Scanner
##########################################################################

SCAN_PATTERNS = [

    "SHORYUKEN",

    "VCP",

    "DTRP",

    "POCKET_PIVOT",

    "FLAT_BASE",

    "CUP_HANDLE",

    "EPISODIC",

]

##########################################################################
# Debug
##########################################################################

DEBUG = False