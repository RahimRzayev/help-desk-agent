from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
POLICIES_DIR = DATA_DIR / "policies"
BOOKINGS_FILE = DATA_DIR / "bookings.json"

# Fixed "current date" from the data README, so answers are the same every run.
NOW = datetime.fromisoformat("2026-06-10T09:00:00+02:00")

STAFF_CONTACT = "help@citywheels.example or +48 000 000 000"
