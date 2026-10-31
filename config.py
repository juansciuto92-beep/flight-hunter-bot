import os
import sys
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class TimeWindow:
    date_str: str          # YYYY-MM-DD
    min_hour: int          # 0..23
    max_hour: int          # 0..23 (inclusive hour limit, e.g. 16 means <= 16:00)
    max_minute: int = 59   # Exact minute cap for the upper bound
    label: str = ""

    def is_time_allowed(self, dep_time: time) -> bool:
        lower = time(self.min_hour, 0)
        upper = time(self.max_hour, self.max_minute)
        return lower <= dep_time <= upper


# ==============================================================================
# CRITERIOS DE BÚSQUEDA SOLICITADOS
# ==============================================================================
ORIGIN_CODES = ["BUE", "EZE", "AEP"]
DESTINATION_CODES = ["MIA"]

# IDA: Buenos Aires -> Miami
# Entre el 5/2/2027 a las 18hs y el 7/2/2027 a las 16hs
OUTBOUND_WINDOWS = [
    TimeWindow(
        date_str="2027-02-05",
        min_hour=18,
        max_hour=23,
        max_minute=59,
        label="Viernes 05/02/2027 (18:00 a 23:59 hs)",
    ),
    TimeWindow(
        date_str="2027-02-06",
        min_hour=0,
        max_hour=23,
        max_minute=59,
        label="Sábado 06/02/2027 (Todo el día)",
    ),
    TimeWindow(
        date_str="2027-02-07",
        min_hour=0,
        max_hour=16,
        max_minute=0,
        label="Domingo 07/02/2027 (00:00 a 16:00 hs)",
    ),
]

# VUELTA: Miami -> Buenos Aires
# Entre el 20/2/2027 a partir de las 17hs, al 21/2/2027 todo el día
INBOUND_WINDOWS = [
    TimeWindow(
        date_str="2027-02-20",
        min_hour=17,
        max_hour=23,
        max_minute=59,
        label="Sábado 20/02/2027 (17:00 a 23:59 hs)",
    ),
    TimeWindow(
        date_str="2027-02-21",
        min_hour=0,
        max_hour=23,
        max_minute=59,
        label="Domingo 21/02/2027 (Todo el día)",
    ),
]

# Restricciones de vuelo
MAX_STOPS = 1                # Directo (0) o con 1 escala (1)
REQUIRE_CARRY_ON = True      # Incluyendo carry-on (equipaje de mano)

# Umbrales de precio en USD
MAX_PRICE_PER_LEG_USD = float(os.getenv("MAX_PRICE_PER_LEG_USD", "450"))
MAX_PRICE_ROUNDTRIP_USD = float(os.getenv("MAX_PRICE_ROUNDTRIP_USD", "900"))

# Frecuencia de ejecución
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
FALLBACK_USD_ARS_RATE = float(os.getenv("FALLBACK_USD_ARS_RATE", "1250"))

# Configuración SMTP (Gmail App Password)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_RECIPIENT = os.getenv("ALERT_RECIPIENT", SMTP_USER)

# Archivos de estado y logs
SEEN_DEALS_FILE = BASE_DIR / "seen_deals.json"
LAST_RESULTS_FILE = BASE_DIR / "last_scan_results.json"
USER_DATA_DIR = BASE_DIR / ".browser_profile"
