"""
app_state.py — In-memory globals (replaces Flask module-level globals).
All data loaded at startup or after uploads lives here.
"""
import threading
from collections import defaultdict

DATA_VERSION = 0
DATA_LOCK    = threading.Lock()

REBUILD_STATE = {
    "running": False,
    "step":    "idle",
    "pct":     100,
    "error":   None,
}

ATT_KEY  = {}
FA_KEY   = {}
CANDIDATES = []

ALL_PROJECTS     = []
ALL_CENTRES      = []
ALL_CENTRE_IDS   = []
ALL_SUB_PROJECTS = []
ALL_BATCHES      = []
ALL_STATUSES     = []

CENTRE_ID_TO_NAME    = {}
PROJ_CENTRES         = {}
CEN_BATCHES          = {}
PROJECT_TO_CENTRE_IDS = defaultdict(set)

COMMUNITY_DATA     = []
COMM_BY_CENTRE_ID  = defaultdict(list)
COMM_BY_NEAR_ID    = defaultdict(list)

BATCH_PLAN_DATA = {}
USERS = {}

# ── Compliance lookup ──────────────────────────────────────────────────────────
# Keyed by (Batch ID, Candidate ID) → dict of compliance row fields.
# Populated by logic.rebuild_compliance() after every compliance upload.
COMPLIANCE_MAP = {}

# ── Unique session counts per batch ────────────────────────────────────────────
# Populated from attendance_data: COUNT(DISTINCT session_id) GROUP BY batch_id.
# Used by api_att_summary and api_summary so the dashboard reports the actual
# number of unique sessions held for a batch, not the sum of attendance rows.
BATCH_UNIQUE_SESSIONS = {}   # batch_id → int (unique session_id count)

_raw_att_for_photos = []

# ── Server-side response cache ─────────────────────────────────────────────────
# Populated after each rebuild so api_overview and api_filters don't re-scan
# 375k candidates on every request. Cleared at start of each rebuild.
OVERVIEW_CACHE = {}   # scope_key → overview JSON dict
FILTERS_CACHE  = {}   # scope_key → filters JSON dict

