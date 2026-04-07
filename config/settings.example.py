# config/settings.example.py
#
# Copy to config/settings.py and fill in your credentials.
# IMPORTANT: `config/settings.py` is intentionally git-ignored.

# --- Credentials (DO NOT COMMIT) ---
# Groww API token. Keep the "Bearer ..." prefix if you already have it.
GROWW_API_KEY = "Bearer <YOUR_GROWW_TOKEN>"

# OpenAI API key for the AI advisor features (if enabled in your workflow).
OPENAI_API_KEY = "<YOUR_OPENAI_API_KEY>"

# --- Watchlist ---
# NSE trading symbols as used by the Groww quote endpoint.
WATCHLIST = [
    "SBIN",
    "RELIANCE",
]

# Nifty index symbol on Groww
NIFTY_SYMBOL = "NIFTY"

# --- Groww API ---
GROWW_BASE_URL    = "https://api.groww.in/v1"
GROWW_EXCHANGE    = "NSE"
GROWW_SEGMENT     = "CASH"
POLL_INTERVAL_SEC = 10

# --- Risk parameters ---
MAX_LOSS_PER_TRADE_RS = 2000
MAX_DAILY_LOSS_RS     = 5000
POSITION_SIZE_RS      = 50000
SL_ATR_MULTIPLIER     = 1.5
TARGET_ATR_MULTIPLIER = 2.5
MIN_RR_RATIO          = 1.5

# --- Indicator settings ---
CANDLE_INTERVAL_SEC = 60
RSI_PERIOD          = 14
EMA_FAST            = 9
EMA_SLOW            = 21
ATR_PERIOD          = 14
VOLUME_AVG_PERIODS  = 20

# --- Signal settings ---
SCAN_EVERY_SEC   = 30
MIN_VOLUME_RATIO = 1.4
AI_COOLDOWN_SEC  = 120
NO_TRADE_AFTER   = "15:00"

