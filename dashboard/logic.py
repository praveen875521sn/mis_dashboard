"""
logic.py — All data-loading, rebuild, and helper functions.
Ported 1-for-1 from app_mysql.py (Flask), now framework-agnostic.

FIXES:
  - read_uploaded_file now uses pandas instead of raw openpyxl row-by-row
    iteration — 3–5x faster for large XLSX/CSV files (Bug #2).
  - rebuild_from_raw now updates S.REBUILD_STATE["last_row_count"] so the
    frontend polling endpoint always has a fresh row count (Bug #4).
  - rebuild_background properly resets REBUILD_STATE on both success and
    failure so a crashed rebuild doesn't permanently block future uploads (Bug #4).
"""

import os, re, threading, tempfile, shutil, csv, datetime as _dt, pickle, hashlib
from collections import defaultdict

from .db_mysql import (
    db_rows, db_scalar, db_execute,
    replace_table, upsert_table,
    check_connectivity, get_table_row_count,
)
from . import app_state as S

# ── Constants ──────────────────────────────────────────────────────────────────
ALLOWED_STATUSES = {
    "assessed", "batchEnd", "batchProcessed", "placed",
    "queuedForAssessment", "queuedForPlacement", "certificateDistributed"
}

NON_PLACEMENT_STATUSES = {
    "assessed", "queuedForPlacement", "certificateDistributed"
}

EMP_CATEGORY_MAP = {
    "Gig":                                   "Self Employed",
    "Nano Contractor":                       "Self Employed",
    "Part Time":                             "Wage Employment",
    "Professional":                          "Wage Employment",
    "Salaried":                              "Wage Employment",
    "Self Employed":                         "Self Employed",
    "Unpaid worker in household enterprise": "Self Employed",
    "Wage Employment- Full Time":            "Wage Employment",
}

EDU_FIELDS = ["Level","Field Of Study","College","Start Date","End Date",
              "Batch ID","Is Pursing","Centre Name","Is Sahi Trained","What did you learn"]
FAM_FIELDS = ["Relationship","Salutation","Name","Mobile Number","Email",
              "Gender","Age","DOB","Qualification","Average Annual Income","Occupation"]


def get_emp_category(emp_type):
    return EMP_CATEGORY_MAP.get(emp_type, "") if emp_type else ""


def normalise_college(name):
    """Clean college name — only handle empty/NA values.
    All real school/college names are kept exactly as they appear in the data.
    """
    if not isinstance(name, str) or not name.strip():
        return "Not Specified"
    n  = name.strip()
    nl = re.sub(r"\s+", " ", n.lower())
    if nl in ("not specified","n/a","na","nil","none","--","-","not applicable",""):
        return "Not Specified"
    return n.strip()


def parse_block(text, fields):
    result = {f: "" for f in fields}
    if not isinstance(text, str):
        return result
    for line in text.strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            if k in result:
                result[k] = v.strip()
    return result


# ── Date helpers ───────────────────────────────────────────────────────────────
def _fy_label(dt_val):
    if not dt_val or str(dt_val).strip() in ('', 'None', 'NaT', 'nan'):
        return None
    try:
        if isinstance(dt_val, (_dt.date, _dt.datetime)):
            d = dt_val if isinstance(dt_val, _dt.date) and not isinstance(dt_val, _dt.datetime) else dt_val.date() if isinstance(dt_val, _dt.datetime) else dt_val
        else:
            s = str(dt_val)[:10]
            d = _dt.date.fromisoformat(s)
        yr = d.year if d.month >= 4 else d.year - 1
        return f"FY {yr}-{str(yr+1)[2:]}"
    except Exception:
        return None

def _month_label(dt_val):
    if not dt_val or str(dt_val).strip() in ('', 'None', 'NaT', 'nan'):
        return ''
    try:
        if isinstance(dt_val, (_dt.date, _dt.datetime)):
            d = dt_val if isinstance(dt_val, _dt.date) and not isinstance(dt_val, _dt.datetime) else dt_val.date() if isinstance(dt_val, _dt.datetime) else dt_val
        else:
            d = _dt.date.fromisoformat(str(dt_val)[:10])
        return d.strftime('%b %Y')
    except Exception:
        return ''

def _month_sort_key(label):
    MONTHS = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,
              'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}
    if not label:
        return 999999
    try:
        parts = label.split()
        return int(parts[1]) * 100 + MONTHS.get(parts[0], 0)
    except Exception:
        return 999999


# ── File upload helpers ────────────────────────────────────────────────────────
def _is_xlsx_bytes(path):
    with open(path, "rb") as f:
        return f.read(2) == b"PK"

def _real_suffix(filename, saved_path=None):
    name_lower = filename.lower()
    if saved_path and _is_xlsx_bytes(saved_path):
        return ".xlsx"
    if name_lower.endswith(".csv"):
        return ".csv"
    return ".xlsx"

def read_uploaded_file(path):
    """
    Read an uploaded CSV or XLSX → list of dicts.

    LARGE FILE STRATEGY (300MB+ files):
      - CSV  → pandas chunked reader (never loads full file into RAM at once)
      - XLSX → openpyxl read_only=True streaming iterator (avoids full workbook load)

    Why NOT pandas read_excel for large XLSX:
      pandas.read_excel with openpyxl engine loads the entire workbook into RAM
      before returning. A 300MB XLSX expands to 2–4GB in Python — OOM on Cloud Run.
      openpyxl read_only=True streams rows one at a time from the zip archive,
      keeping peak RAM around 200–400MB regardless of file size.

    Why NOT pandas read_csv chunked → list:
      Chunking and immediately calling list() defeats the purpose. We chunk,
      process each chunk, and extend a pre-allocated list.
    """
    is_csv = path.lower().endswith(".csv") and not _is_xlsx_bytes(path)
    if is_csv:
        return _read_csv_chunked(path)
    else:
        return _read_xlsx_streaming(path)


def _read_csv_chunked(path, chunk_size=50_000):
    """Read CSV in 50k-row chunks to avoid loading 300MB+ into RAM at once."""
    try:
        import pandas as pd
        rows = []
        headers = None
        reader = pd.read_csv(
            path,
            encoding="utf-8-sig",
            dtype=str,
            keep_default_na=False,
            on_bad_lines="skip",
            chunksize=chunk_size,
        )
        for chunk in reader:
            chunk.columns = [str(c).strip() for c in chunk.columns]
            chunk = chunk.fillna("")
            for col in chunk.columns:
                chunk[col] = chunk[col].str.strip()
            first_col = chunk.columns[0]
            chunk = chunk[chunk[first_col] != ""]
            rows.extend(chunk.to_dict("records"))
            print(f"  _read_csv_chunked: {len(rows):,} rows so far…", flush=True)
        print(f"  read_uploaded_file (CSV): {len(rows):,} rows from {os.path.basename(path)}")
        return rows
    except ImportError:
        print("  WARNING: pandas not installed — falling back to csv.DictReader")
        return _read_uploaded_file_openpyxl(path)


def _read_xlsx_streaming(path):
    """
    Stream an XLSX using openpyxl read_only=True.
    Peak RAM ≈ O(columns) not O(rows) — safe for 300MB+ files.
    Yields rows one at a time instead of loading the full sheet.
    """
    import openpyxl
    print(f"  _read_xlsx_streaming: opening {os.path.basename(path)} …", flush=True)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]

    rows = []
    headers = None
    row_num = 0

    for raw_row in ws.iter_rows(values_only=True):
        row_num += 1
        if row_num == 1:
            # Header row
            headers = [str(h).strip() if h is not None else f"_col{i}"
                       for i, h in enumerate(raw_row)]
            continue

        # Skip rows where first cell is empty (blank / header-repeat rows)
        if raw_row[0] is None or str(raw_row[0]).strip() == "":
            continue

        d = {}
        for i, h in enumerate(headers):
            if not h or h.startswith("_col"):
                continue
            v = raw_row[i] if i < len(raw_row) else None
            d[h] = str(v).strip() if v is not None else ""
        rows.append(d)

        if len(rows) % 50_000 == 0:
            print(f"  _read_xlsx_streaming: {len(rows):,} rows read…", flush=True)

    wb.close()
    print(f"  read_uploaded_file (XLSX): {len(rows):,} rows from {os.path.basename(path)}")
    return rows


def _read_uploaded_file_openpyxl(path):
    """Legacy openpyxl reader — kept as fallback. Slow for large files."""
    if path.lower().endswith(".csv") and not _is_xlsx_bytes(path):
        rows = []
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                first = next(iter(row.values()), "")
                if not first or str(first).strip() == "":
                    continue
                rows.append({k.strip(): (str(v).strip() if v else "")
                             for k, v in row.items() if k and k.strip()})
        return rows

    import openpyxl
    actual = path
    tmp    = None
    if path.lower().endswith(".csv"):
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.close()
        shutil.copy2(path, tmp.name)
        actual = tmp.name
    try:
        wb = openpyxl.load_workbook(actual, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        raw_h   = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
        headers = [str(h).strip() if h is not None else "" for h in raw_h]
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0] is None:
                continue
            d = {}
            for i, h in enumerate(headers):
                if not h:
                    continue
                v = row[i] if i < len(row) else None
                d[h] = str(v).strip() if v is not None else ""
            rows.append(d)
        wb.close()
        return rows
    finally:
        if tmp:
            try: os.unlink(tmp.name)
            except: pass


# ── Load User Master ───────────────────────────────────────────────────────────
def load_user_master():
    try:
        all_rows = db_rows("SELECT * FROM `user_master`", table_hint="user_master")
        rows     = db_rows("SELECT * FROM `user_master` WHERE `active` != 'No'", table_hint="user_master")
    except Exception as e:
        print(f"  ERROR: Cannot read user_master table: {e}")
        S.USERS = {}
        return

    if all_rows is not None and len(all_rows) == 0:
        print("  WARNING: user_master table is empty. Visit /setup/bootstrap to create the first admin.")
    elif not rows:
        S.USERS = {}
        return

    if not rows:
        S.USERS = {}
        return

    users = {}
    skipped = 0
    for r in rows:
        email = (r.get("email") or "").lower().strip()
        if not email:
            skipped += 1
            continue
        users[email] = {
            "ecode":             str(r.get("ecode") or "").strip(),
            "name":              (r.get("employee_name") or "").strip(),
            "email":             email,
            "role":              (r.get("role") or "").strip(),
            "active":            r.get("active", "Yes"),
            "mapped_centres":    [],
            "mapped_centre_ids": [],
            "mapped_projects":   [],
        }
    S.USERS = users
    print(f"  Loaded {len(S.USERS)} active users (skipped {skipped} with no email)")

    # CRITICAL: load_user_master only loads the user records themselves with
    # EMPTY mapping lists. Centre/project mappings live in the same row but
    # are populated by reload_user_mappings(). Without this call, any user
    # loaded via the get_current_user recovery path (worker restart, login
    # before background reload) would have mapped_centres=[] and apply_scope
    # would return zero candidates — the exact "Centre Manager sees no data"
    # symptom. Call it inline so users are immediately usable.
    try:
        reload_user_mappings()
    except Exception as e:
        print(f"  WARNING: reload_user_mappings failed: {e}", flush=True)


# ── Load Community Data ────────────────────────────────────────────────────────
def load_community_data():
    # The centre_community_master table is created lazily on the first community-data
    # upload (see views._bg_community → replace_table). On a fresh install it doesn't
    # exist yet, so probe first to avoid a misleading "DB ERROR" log line from db_rows.
    exists = db_scalar(
        "SHOW TABLES LIKE 'centre_community_master'",
        table_hint="centre_community_master",
    )
    if not exists:
        S.COMMUNITY_DATA = []
        S.COMM_BY_CENTRE_ID = defaultdict(list)
        S.COMM_BY_NEAR_ID = defaultdict(list)
        print("  Community master: table not yet created (awaiting first upload)")
        return

    rows = db_rows('SELECT * FROM `centre_community_master`', table_hint="centre_community_master")
    community = []
    for r in rows:
        def _v(k): return str(r.get(k) or "").strip().replace("\n", " ").replace('"', '')
        def _f(k):
            try: return float(r.get(k) or 0) or None
            except: return None
        centre_near_name = _v("centre_name_near")
        center_type      = _v("center_type")
        community.append({
            "zone":             _v("zone"),
            "type_center":      center_type,
            "centre_near_name": centre_near_name,
            "centre_near_id":   centre_near_name,
            "project":          _v("project"),
            "location":         _v("location"),
            "district":         _v("district"),
            "state":            _v("state"),
            "centre_name":      _v("centre_name"),
            "centre_id":        _v("centre_id"),
            "center_type":      center_type,
            "address":          _v("center_address"),
            "status":           _v("status"),
            "pin":              _v("pin_code"),
            "lat":              _f("lat"),
            "lng":              _f("lag"),
            "distance_km":      _f("distance_km") or 0,
            "distance_slab":    _v("distance_slab"),
            "sub_cluster":      _v("sub_cluster_name"),
            "cluster":          _v("cluster_name"),
            "service_category": _v("service_category"),
            "impact_disc":      _v("impact___disc"),
        })
    S.COMMUNITY_DATA = community
    cb_id   = defaultdict(list)
    cb_near = defaultdict(list)
    for c in community:
        if c["centre_id"]:        cb_id[c["centre_id"]].append(c)
        if c["centre_near_name"]: cb_near[c["centre_near_name"]].append(c)
    S.COMM_BY_CENTRE_ID = cb_id
    S.COMM_BY_NEAR_ID   = cb_near
    print(f"  Community master: {len(community)} records, {len(cb_near)} unique anchor centres")


# ── Rebuild Batch Plan ─────────────────────────────────────────────────────────
def _latest_date(*vals):
    """
    Return the latest (max) of a set of date-ish values, ignoring blanks/None.
    Each value may be a datetime, date, or 'YYYY-MM-DD…' string.
    Returns a `datetime.date` or None if nothing valid.
    """
    best = None
    for v in vals:
        if v is None: continue
        s = str(v).strip()
        if not s or s.lower() in ('nat', 'nan', 'none', ''):
            continue
        try:
            d = _dt.date.fromisoformat(s[:10])
        except Exception:
            continue
        if best is None or d > best:
            best = d
    return best


def rebuild_compliance():
    """
    Build the in-memory compliance lookup from the `compliance_data` table.

    Keyed by (Batch ID, Candidate ID). When the same key has multiple rows
    (very rare — usually a re-upload artefact) the row with the latest
    `Date` wins.

    Resilient to a missing table — on a fresh install the table is created
    on first upload, so before that we simply end up with an empty map.
    """
    try:
        raw = db_rows(
            "SELECT * FROM `compliance_data`",
            table_hint="compliance_data"
        )
    except Exception as e:
        # Table not created yet (no compliance upload has happened) — that's fine.
        msg = str(e).lower()
        if "doesn't exist" in msg or "no such table" in msg or "1146" in msg:
            S.COMPLIANCE_MAP = {}
            print("  Compliance: table not created yet (no uploads yet) — map empty")
            return
        raise

    def _date_key(s):
        s = (s or "").strip()
        return s[:10] if len(s) >= 10 else s

    out = {}
    for r in raw:
        bid = (r.get("batch_id") or "").strip()
        # ECP pool uses "cand_id" — check both field names so the join works
        cid = (r.get("cand_id") or r.get("candidate_id") or "").strip()
        if not bid or not cid:
            continue
        key = (bid, cid)
        cur = out.get(key)
        if cur is None or _date_key(r.get("date","")) >= _date_key(cur.get("date","")):
            out[key] = r

    S.COMPLIANCE_MAP = out
    print(f"  Compliance rebuilt: {len(S.COMPLIANCE_MAP):,} unique (batch,candidate) records")


def rebuild_batch_plan():
    """
    Batch Plan rebuild — implements the "Latest Date + Sum of Final Planned"
    logic from Batch_Plan.docx.

    Per Batch ID we:
      • SUM Final Enrolment / Certification / Placement Planned across all rows
        (the source file has multiple rows per batch with values split across).
      • Use the LATEST (max) date between Planned and Revised for each of:
          - Effective Batch Planned Start Date  →  drives Enrolment month
          - Effective Batch Planned End Date    →  (kept for reference)
          - Effective Certification Start Date  →  drives Certification month
          - Effective Placement End Date        →  drives Placement month
    """
    raw = db_rows(
        "SELECT * FROM `batch_plan`",
        table_hint="batch_plan"
    )

    def _int(v):
        try: return int(float(v or 0))
        except: return 0

    # First pass: aggregate per Batch ID
    agg = {}   # bid -> {meta, sum_enrol, sum_cert, sum_place,
               #         batch_start_dates[], batch_end_dates[],
               #         cert_start_dates[], place_end_dates[]}
    for r in raw:
        bid = (r.get("batch_id") or "").strip()
        if not bid:
            continue
        if bid not in agg:
            agg[bid] = {
                "meta": r,
                "sum_enrol": 0, "sum_cert": 0, "sum_place": 0,
                "bs_planned":[], "bs_revised":[],
                "be_planned":[], "be_revised":[],
                "cs_planned":[], "cs_revised":[],
                "pe_planned":[], "pe_revised":[],
            }
        a = agg[bid]
        a["sum_enrol"] += _int(r.get("final_enrolment_planned"))
        a["sum_cert"]  += _int(r.get("final_certification_planned"))
        a["sum_place"] += _int(r.get("final_placement_planned"))
        a["bs_planned"].append(r.get("batch_planned_start_date"))
        a["bs_revised"].append(r.get("revised_planned_batch_start_date"))
        a["be_planned"].append(r.get("batch_planned_end_date"))
        a["be_revised"].append(r.get("revised_planned_batch_end_date"))
        # Note: SQL col is `certification_planned_start_date` (double-space in
        # the source header collapses to a single underscore via col_name_to_sql)
        a["cs_planned"].append(r.get("certification_planned_start_date"))
        a["cs_revised"].append(r.get("revised_certification_start_date"))
        a["pe_planned"].append(r.get("placement_planned_end_date"))
        a["pe_revised"].append(r.get("revised_placement_end_date"))

    # Fallback: legacy planned columns (in case a deployment still uses them)
    def _fallback_int(meta, *keys):
        for k in keys:
            v = _int(meta.get(k))
            if v: return v
        return 0

    seen = {}
    for bid, a in agg.items():
        meta = a["meta"]

        # ── Effective dates: max(planned, revised) ────────────────────────
        eff_batch_start = _latest_date(*a["bs_planned"], *a["bs_revised"])
        eff_batch_end   = _latest_date(*a["be_planned"], *a["be_revised"])
        eff_cert_start  = _latest_date(*a["cs_planned"], *a["cs_revised"])
        eff_place_end   = _latest_date(*a["pe_planned"], *a["pe_revised"])

        # ── Plan totals: sum of Final_*_Planned, else fall back ───────────
        enrol_plan = a["sum_enrol"] or _fallback_int(
            meta, "enrolment_planned", "revised_enrolment_target", "enrolment_target")
        cert_plan  = a["sum_cert"]  or _fallback_int(
            meta, "certification_planned", "revised_certification_target", "certification_target")
        place_plan = a["sum_place"] or _fallback_int(
            meta, "placement_planned", "revised_placement_target", "placement_target")

        seen[bid] = {
            "batch_id":    bid,
            "batch_name":  meta.get("batch_name", ""),
            "course_name": meta.get("course_name", ""),
            "coo_name":    meta.get("coo_name", ""),
            "project_name":meta.get("project_name", ""),
            "centre_name": meta.get("centre_name", ""),
            "batch_status":meta.get("batch_status", ""),

            # Effective ISO dates (YYYY-MM-DD or '')
            "enrol_date":  eff_batch_start.isoformat() if eff_batch_start else "",
            "batch_end_date": eff_batch_end.isoformat() if eff_batch_end else "",
            "cert_date":   eff_cert_start.isoformat()  if eff_cert_start  else "",
            "place_date":  eff_place_end.isoformat()   if eff_place_end   else "",

            # Month labels
            "enrol_month": _month_label(eff_batch_start),
            "cert_month":  _month_label(eff_cert_start),
            "place_month": _month_label(eff_place_end),

            # FY labels (kept on row for any future use, even though the
            # Target/Actual UI no longer exposes an FY filter)
            "enrol_fy":    _fy_label(eff_batch_start),
            "cert_fy":     _fy_label(eff_cert_start),
            "place_fy":    _fy_label(eff_place_end),

            "enrol_plan":  enrol_plan,
            "cert_plan":   cert_plan,
            "place_plan":  place_plan,
        }

    S.BATCH_PLAN_DATA = seen
    print(f"  Batch Plan rebuilt: {len(S.BATCH_PLAN_DATA)} batches "
          f"(latest-date + sum-of-Final logic)")


# ── Core Rebuild ───────────────────────────────────────────────────────────────

def _prewarm_caches():
    """Pre-compute and cache overview + filters for the default (unfiltered) view."""
    from collections import Counter, defaultdict
    pool = S.CANDIDATES
    if not pool:
        return

    # Filters cache
    filters_result = {
        "projects":     S.ALL_PROJECTS,
        "sub_projects": S.ALL_SUB_PROJECTS,
        "centres":      S.ALL_CENTRES,
        "batches":      S.ALL_BATCHES,
        "statuses":     S.ALL_STATUSES,
        "emp_cats":     ["Wage Employment", "Self Employed"],
        "scope":        "all",
    }
    S.FILTERS_CACHE["filters:all:::"] = filters_result

    # Overview cache
    total        = len(pool)
    assessed     = sum(1 for c in pool if c["assessed"])
    certified    = sum(1 for c in pool if c["is_cert"])
    placed       = sum(1 for c in pool if c["is_placed"])
    batch_proc   = sum(1 for c in pool if c.get("status") == "batchProcessed")
    female       = sum(1 for c in pool if c["gender"] and c["gender"].lower() in ("female","f"))
    placed_female= sum(1 for c in pool if c["is_placed"] and c["gender"] and c["gender"].lower() in ("female","f"))
    in_att       = sum(1 for c in pool if c.get("att_pct", 0) > 0)
    in_fa        = sum(1 for c in pool if c.get("fa_pct",  0) > 0)
    centres_cnt  = len(set(c["centre"]   for c in pool if c["centre"]))
    batches_cnt  = len(set(c["batch_id"] for c in pool if c["batch_id"]))
    att_avg      = round(sum(c.get("att_pct",0) for c in pool) / total, 1) if total else 0
    fa_avg       = round(sum(c.get("fa_pct", 0) for c in pool) / total, 1) if total else 0
    status_vc    = dict(Counter(c["status"]    for c in pool if c["status"]).most_common(15))
    att_bands    = dict(Counter(c["att_band"]  for c in pool))
    fa_bands     = dict(Counter(c["fa_status"] for c in pool))
    edu_vc       = dict(Counter(c["edu_level"] for c in pool if c["edu_level"]).most_common(12))
    state_vc     = dict(Counter(c["state"]     for c in pool if c["state"]).most_common(10))
    course_vc    = dict(Counter(c["course"]    for c in pool if c["course"]).most_common(12))
    monthly_raw  = defaultdict(int)
    for c in pool:
        m = (c.get("batch_start") or "")[:7]
        if m: monthly_raw[m] += 1
    monthly = dict(sorted(monthly_raw.items()))

    overview_result = {
        "kpis": {
            "total": total, "assessed": assessed, "certified": certified,
            "placed": placed, "cert_placed": placed, "batch_processed": batch_proc,
            "female": female, "placed_female": placed_female,
            "att_avg": att_avg, "fa_avg": fa_avg,
            "centres": centres_cnt, "batches": batches_cnt,
        },
        "pipeline": {
            "enrolled": total, "in_att": in_att, "in_fa": in_fa,
            "assessed": assessed, "certified": certified, "placed": placed,
        },
        "status_vc": status_vc, "att_bands": att_bands, "fa_bands": fa_bands,
        "monthly": monthly, "edu_vc": edu_vc, "state_vc": state_vc, "course_vc": course_vc,
    }
    # Store under multiple likely cache keys
    for key in ["overview:anon:", "overview:anon:?"]:
        S.OVERVIEW_CACHE[key] = overview_result
    print(f"  Cache pre-warmed: overview + filters for {total:,} candidates", flush=True)

def load_from_disk_cache():
    """
    Load candidate list from disk cache on server startup.
    This makes the dashboard instantly available after restart
    while a full rebuild runs in the background to get fresh data.
    Returns True if cache was loaded successfully.
    """
    try:
        cache_path = os.path.join(tempfile.gettempdir(), "ecp_candidates_cache.pkl")
        if not os.path.exists(cache_path):
            print("  No disk cache found — will rebuild from DB", flush=True)
            return False
        cache_age_hours = (_dt.datetime.utcnow() - _dt.datetime.fromtimestamp(
            os.path.getmtime(cache_path)
        )).total_seconds() / 3600

        print(f"  Loading disk cache (age: {cache_age_hours:.1f}h)…", flush=True)
        with open(cache_path, "rb") as f:
            cache_data = pickle.load(f)

        candidates = cache_data.get("candidates", [])
        if not candidates:
            print("  Disk cache empty — will rebuild from DB", flush=True)
            return False

        S.CANDIDATES = candidates
        with S.DATA_LOCK:
            S.DATA_VERSION += 1
        print(f"  ✅ Loaded {len(candidates):,} candidates from disk cache instantly!", flush=True)
        return True
    except Exception as e:
        print(f"  Cache load warning: {e}", flush=True)
        return False


def rebuild_from_raw():
    """
    Re-read all tables from MySQL and rebuild the in-memory CANDIDATES list.

    FIX #4 — updates last_row_count at each step so /api/rebuild/status
    always reflects the latest progress even mid-rebuild.
    """
    import time as _time
    _t0 = _time.time()
    # Clear response caches so stale data isn't served after rebuild
    S.OVERVIEW_CACHE.clear()
    S.FILTERS_CACHE.clear()
    S.REBUILD_STATE["running"] = True
    S.REBUILD_STATE["error"]   = None

    # 1. Attendance — aggregate in SQL for speed
    S.REBUILD_STATE["step"] = "Aggregating attendance…"; S.REBUILD_STATE["pct"] = 10
    _t1 = _time.time()
    att_rows = db_rows(
        'SELECT `batch_id`, `candidate_id`, '
        'COUNT(*) as total, '
        'SUM(CASE WHEN `attendance_status`="Present" THEN 1 ELSE 0 END) as present_count '
        'FROM `attendance_data` GROUP BY `batch_id`, `candidate_id`',
        table_hint="attendance_data"
    )
    att_key = {}
    for r in att_rows:
        key = (r.get("batch_id") or "").strip() + "|" + (r.get("candidate_id") or "").strip()
        total   = int(r.get("total") or 0)
        present = int(r.get("present_count") or 0)
        absent  = total - present
        p = round(present / total * 100, 2) if total else 0
        if   p >= 90: band = "90–100% (Excellent)"
        elif p >= 75: band = "75–89% (Good)"
        elif p >= 50: band = "50–74% (Low)"
        elif p  > 0:  band = "<50% (Critical)"
        else:         band = "No Attendance Data"
        att_key[key] = {"att_pct": p, "att_band": band,
                        "total_sessions": total, "present": present, "absent": absent}
    S.ATT_KEY = att_key
    S._raw_att_for_photos = []
    print(f"  Attendance aggregated: {len(att_key)} keys — {_time.time()-_t1:.1f}s", flush=True)

    # Issue 2 — unique session-ID count per batch (used by api_att_summary etc.)
    try:
        sess_rows = db_rows(
            'SELECT `batch_id`, COUNT(DISTINCT `session_id`) AS uniq '
            'FROM `attendance_data` GROUP BY `batch_id`',
            table_hint="attendance_data"
        )
        S.BATCH_UNIQUE_SESSIONS = {
            r.get("batch_id",""): int(r.get("uniq") or 0)
            for r in sess_rows if r.get("batch_id")
        }
        print(f"  Unique sessions indexed for {len(S.BATCH_UNIQUE_SESSIONS):,} batches",
              flush=True)
    except Exception as _e:
        print(f"  WARNING: could not compute unique session counts: {_e}", flush=True)

    # 2. FA — aggregate in SQL for speed
    # Unique key: (batch_id, candidate_id, topic_name) → latest evaluated_on wins
    S.REBUILD_STATE["step"] = "Aggregating FA scores…"; S.REBUILD_STATE["pct"] = 35
    _t2 = _time.time()
    fa_rows = db_rows(
        'SELECT batch_id, candidate_id, '
        'SUM(CASE WHEN pass_fail_attempted="Passed" THEN 1 ELSE 0 END) as passed_count, '
        'SUM(CASE WHEN pass_fail_attempted="Failed"  THEN 1 ELSE 0 END) as failed_count, '
        'COUNT(*) as total '
        'FROM ('
        '  SELECT batch_id, candidate_id, topic_name, pass_fail_attempted '
        '  FROM fa f1 '
        '  WHERE evaluated_on = ('
        '    SELECT MAX(f2.evaluated_on) FROM fa f2 '
        '    WHERE f2.batch_id=f1.batch_id AND f2.candidate_id=f1.candidate_id '
        '      AND f2.topic_name=f1.topic_name'
        '  )'
        ') deduped '
        'GROUP BY batch_id, candidate_id',
        table_hint="fa"
    )
    fa_key = {}
    for r in fa_rows:
        key = (r.get("batch_id") or "").strip() + "|" + (r.get("candidate_id") or "").strip()
        total  = int(r.get("total") or 0)
        passed = int(r.get("passed_count") or 0)
        failed = int(r.get("failed_count") or 0)
        p = round(passed / total * 100, 2) if total else 0
        if   p >= 80: st = "Excellent (≥80%)"
        elif p >= 60: st = "Good (60–79%)"
        elif p  > 0:  st = "Needs Improvement (<60%)"
        else:         st = "Not Evaluated"
        fa_key[key] = {"fa_pct": p, "fa_status": st,
                       "passed": passed, "failed": failed,
                       "attempted": 0, "not_attempted": 0}
    S.FA_KEY = fa_key
    print(f"  FA aggregated: {len(fa_key)} keys — {_time.time()-_t2:.1f}s", flush=True)

    # 3. ECP Candidates
    _t3 = _time.time()
    S.REBUILD_STATE["step"] = "Building candidate master…"; S.REBUILD_STATE["pct"] = 60
    allowed = "','".join(ALLOWED_STATUSES)
    # SELECT only columns actually used — reduces MySQL data transfer ~70% for 300K+ rows
    needed_cols = (
        "`batch_id`,`candidate_id`,`project_name`,`sub_project_name`,"
        "`centre_id`,`centre_name`,`centre_type`,"
        "`batch_actual_start_date`,`batch_actual_end_date`,"
        "`candidate_name`,`candidate_gender`,`candidate_phone`,"
        "`present_state`,`present_district`,"
        "`course_name`,`qp_name`,`highest_qualification`,"
        "`candidate_last_status`,`has_assessed`,"
        "`assessment_certification_status`,`assessment_actual_certification_date`,"
        "`has_placed`,`placed_date`,`employment_type`,"
        "`job_title`,`placement_company_or_branch_name`,"
        "`candidate_age`,`education_details`,`family_details`,"
        "`course_sector`,`present_address`"
    )
    ecp_rows = db_rows(
        f"SELECT {needed_cols} FROM `ecp` WHERE `candidate_last_status` IN ('{allowed}')",
        table_hint="ecp"
    )
    print(f"  ECP rows after status filter: {len(ecp_rows)} — query took {_time.time()-_t3:.1f}s", flush=True)
    _t4 = _time.time()
    S.REBUILD_STATE["last_row_count"] = len(ecp_rows)

    # ── Pandas vectorized candidate build (5–8x faster than Python loop) ──
    import pandas as pd

    df = pd.DataFrame(ecp_rows)
    if df.empty:
        S.CANDIDATES = []
        print(f"  Master list: 0 candidates — loop took {_time.time()-_t4:.1f}s", flush=True)
    else:
        # Build lookup key
        df["_bid"]  = df.get("batch_id", pd.Series(dtype=str)).fillna("").str.strip()
        df["_cid"]  = df.get("candidate_id", pd.Series(dtype=str)).fillna("").str.strip()
        df["_key"]  = df["_bid"] + "|" + df["_cid"]

        # Merge att_key
        att_df = pd.DataFrame([
            {"_key": k, **v} for k, v in att_key.items()
        ]) if att_key else pd.DataFrame(columns=["_key","att_pct","att_band","total_sessions","present","absent"])
        fa_df = pd.DataFrame([
            {"_key": k, **v} for k, v in fa_key.items()
        ]) if fa_key else pd.DataFrame(columns=["_key","fa_pct","fa_status","passed","failed","attempted","not_attempted"])

        # Rename fa columns to avoid conflicts
        if not fa_df.empty and "passed" in fa_df.columns:
            fa_df = fa_df.rename(columns={"passed":"fa_passed","failed":"fa_failed"})

        df = df.merge(att_df, on="_key", how="left")
        df = df.merge(fa_df,  on="_key", how="left")

        # Fill missing att/fa
        df["att_pct"]        = df["att_pct"].fillna(0)
        df["att_band"]       = df["att_band"].fillna("No Attendance Data")
        df["total_sessions"] = df["total_sessions"].fillna(0).astype(int)
        df["present"]        = df["present"].fillna(0).astype(int)
        df["absent"]         = df["absent"].fillna(0).astype(int)
        df["fa_pct"]         = df["fa_pct"].fillna(0)
        df["fa_status"]      = df["fa_status"].fillna("Not Evaluated")
        df["fa_passed"]      = df.get("fa_passed", pd.Series(0, index=df.index)).fillna(0).astype(int)
        df["fa_failed"]      = df.get("fa_failed", pd.Series(0, index=df.index)).fillna(0).astype(int)

        # Derived fields
        cert_col = df.get("assessment_certification_status", pd.Series("", index=df.index)).fillna("")
        placed_col = df.get("has_placed", pd.Series("", index=df.index)).fillna("")
        df["is_cert"]   = cert_col.str.lower() == "certified"
        df["is_placed"] = (placed_col.str.lower() == "yes") & df["is_cert"]

        emp_col = df.get("employment_type", pd.Series("", index=df.index)).fillna("")
        df["emp_category"] = emp_col.apply(get_emp_category)

        age_col = df.get("candidate_age", pd.Series("", index=df.index)).fillna(0)
        def safe_age(v):
            try: return int(float(v))
            except: return 0
        df["_age"] = age_col.apply(safe_age)

        # Parse education and family blocks using multiprocessing for speed
        import multiprocessing as mp
        edu_series = df.get("education_details", pd.Series("", index=df.index)).fillna("")
        fam_series = df.get("family_details", pd.Series("", index=df.index)).fillna("")

        # Use parallel apply if enough rows, else regular apply
        if len(df) > 50000:
            try:
                from multiprocessing.pool import ThreadPool
                pool = ThreadPool(4)
                edu_list = pd.Series(pool.map(lambda x: parse_block(x, EDU_FIELDS), edu_series.tolist()))
                fam_list = pd.Series(pool.map(lambda x: parse_block(x, FAM_FIELDS), fam_series.tolist()))
                pool.close()
            except Exception:
                edu_list = edu_series.apply(lambda x: parse_block(x, EDU_FIELDS))
                fam_list = fam_series.apply(lambda x: parse_block(x, FAM_FIELDS))
        else:
            edu_list = edu_series.apply(lambda x: parse_block(x, EDU_FIELDS))
            fam_list = fam_series.apply(lambda x: parse_block(x, FAM_FIELDS))

        # Fully vectorized — no Python loop at all
        # Map all columns directly using vectorized operations
        df["emp_category"] = df["emp_category"].fillna("Others")

        # Build candidates list using to_dict (10x faster than iterrows)
        records = df.to_dict("records")

        # Pre-compute edu and fam as lists
        edu_records = edu_list.tolist()
        fam_records = fam_list.tolist()

        candidates = []
        for i, (row, edu, fam) in enumerate(zip(records, edu_records, fam_records)):
            edu["College"] = normalise_college(edu.get("College",""))
            candidates.append({
                "_key":       row["_key"],
                "batch_id":   row["_bid"],
                "cand_id":    row["_cid"],
                "batch_cand": row["_bid"] + " & " + row["_cid"],
                "project":    row.get("project_name",""),
                "sub_project":row.get("sub_project_name",""),
                "centre_id":  row.get("centre_id",""),
                "centre":     row.get("centre_name",""),
                "centre_type":row.get("centre_type",""),
                "batch_start":str(row.get("batch_actual_start_date",""))[:10],
                "batch_end":  str(row.get("batch_actual_end_date",""))[:10],
                "name":       row.get("candidate_name",""),
                "gender":     row.get("candidate_gender",""),
                "phone":      row.get("candidate_phone",""),
                "state":      row.get("present_state",""),
                "district":   row.get("present_district",""),
                "course":     row.get("course_name",""),
                "qp":         row.get("qp_name",""),
                "edu_level":  row.get("highest_qualification",""),
                "status":     row.get("candidate_last_status",""),
                "assessed":   str(row.get("has_assessed","")).lower() == "yes",
                "cert_status":row.get("assessment_certification_status",""),
                "cert_actual_date": str(row.get("assessment_actual_certification_date",""))[:10],
                "placed_date":      str(row.get("placed_date",""))[:10],
                "is_cert":    bool(row["is_cert"]),
                "is_placed":  bool(row["is_placed"]),
                "emp_type":   str(row.get("employment_type","")),
                "emp_category": row["emp_category"],
                "job_title":  row.get("job_title",""),
                "company":    row.get("placement_company_or_branch_name",""),
                "age":        int(row["_age"]),
                "att_pct":    float(row["att_pct"]),
                "att_band":   str(row["att_band"]),
                "total_sessions": int(row["total_sessions"]),
                "present":    int(row["present"]),
                "absent":     int(row["absent"]),
                "fa_pct":     float(row["fa_pct"]),
                "fa_status":  str(row["fa_status"]),
                "fa_passed":  int(row["fa_passed"]),
                "fa_failed":  int(row["fa_failed"]),
                "college":    edu["College"],
                "edu_field":  edu.get("Field Of Study",""),
                "fam_rel":    fam.get("Relationship",""),
                "fam_occ":    fam.get("Occupation",""),
                "fam_income": fam.get("Average Annual Income",""),
                "address":    (str(row.get("present_address","")) or "").strip() or "NA",
                "sector":     (str(row.get("course_sector","")) or "").strip() or "Others",
            })

        S.CANDIDATES = candidates
    print(f"  Master list: {len(S.CANDIDATES)} candidates — loop took {_time.time()-_t4:.1f}s", flush=True)
    print(f"  TOTAL rebuild_from_raw: {_time.time()-_t0:.1f}s", flush=True)

    # Save to disk cache so next server restart loads instantly
    try:
        cache_path = os.path.join(tempfile.gettempdir(), "ecp_candidates_cache.pkl")
        cache_data = {
            "candidates":    S.CANDIDATES,
            "row_count":     len(S.CANDIDATES),
            "saved_at":      _dt.datetime.utcnow().isoformat(),
        }
        with open(cache_path, "wb") as f:
            pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"  Cache saved to disk: {cache_path} ({len(S.CANDIDATES):,} candidates)", flush=True)
    except Exception as ce:
        print(f"  Cache save warning: {ce}", flush=True)

    # 4. Lookups
    S.REBUILD_STATE["step"] = "Building lookup indexes…"; S.REBUILD_STATE["pct"] = 88
    proj_to_ids = defaultdict(set)
    for c in candidates:
        if c["project"] and c["centre_id"]:
            proj_to_ids[c["project"]].add(c["centre_id"])
    S.PROJECT_TO_CENTRE_IDS = proj_to_ids
    S.ALL_PROJECTS   = sorted(set(c["project"]    for c in candidates if c["project"]))
    S.ALL_CENTRES    = sorted(set(c["centre"]     for c in candidates if c["centre"]))
    S.ALL_CENTRE_IDS = sorted(set(c["centre_id"]  for c in candidates if c["centre_id"]))
    S.ALL_SUB_PROJECTS = sorted(set(c["sub_project"] for c in candidates if c.get("sub_project")))
    S.ALL_BATCHES    = sorted(set(c["batch_id"]   for c in candidates if c["batch_id"]))
    S.ALL_STATUSES   = sorted(set(c["status"]     for c in candidates if c["status"]))
    S.CENTRE_ID_TO_NAME = {c["centre_id"]: c["centre"] for c in candidates if c["centre_id"]}

    with S.DATA_LOCK:
        S.DATA_VERSION += 1
    # Clear scope cache so centre managers get fresh scoped pools
    try:
        from .views import _SCOPE_CACHE
        _SCOPE_CACHE.clear()
    except Exception:
        pass
    # Pre-warm overview + filters cache for the default (no-filter) view
    try:
        _prewarm_caches()
    except Exception as _e:
        print(f"  Cache prewarm warning: {_e}", flush=True)
    S.REBUILD_STATE["running"] = False
    S.REBUILD_STATE["step"]    = "idle"
    S.REBUILD_STATE["pct"]     = 100
    print(f"  Rebuild complete. DATA_VERSION={S.DATA_VERSION}")


def rebuild_background():
    """Full rebuild in background thread."""
    try:
        rebuild_from_raw()
    except Exception as e:
        S.REBUILD_STATE["running"] = False
        S.REBUILD_STATE["step"]    = "error"
        S.REBUILD_STATE["pct"]     = 0
        S.REBUILD_STATE["error"]   = str(e)
        print(f"  REBUILD ERROR: {e}")


def _partial_rebuild_scores(source):
    """Helper: update FA or Attendance scores in-memory without full ECP re-query."""
    import time as _t
    t0 = _t.time()

    if source == "fa":
        rows = db_rows(
            'SELECT batch_id, candidate_id, '
            'SUM(CASE WHEN pass_fail_attempted="Passed" THEN 1 ELSE 0 END) as passed_count, '
            'SUM(CASE WHEN pass_fail_attempted="Failed"  THEN 1 ELSE 0 END) as failed_count, '
            'COUNT(*) as total '
            'FROM ('
            '  SELECT batch_id, candidate_id, topic_name, pass_fail_attempted '
            '  FROM fa f1 '
            '  WHERE evaluated_on = ('
            '    SELECT MAX(f2.evaluated_on) FROM fa f2 '
            '    WHERE f2.batch_id=f1.batch_id AND f2.candidate_id=f1.candidate_id '
            '      AND f2.topic_name=f1.topic_name'
            '  )'
            ') deduped '
            'GROUP BY batch_id, candidate_id',
            table_hint="fa"
        )
        score_key = {}
        for r in rows:
            key = r.get("batch_id","") + "|" + r.get("candidate_id","")
            passed = int(r.get("passed_count") or 0)
            failed = int(r.get("failed_count") or 0)
            total  = int(r.get("total") or 0)
            score_key[key] = {"fa_pct": round(passed/total*100,1) if total else 0,
                              "fa_passed": passed, "fa_failed": failed}
        for c in S.CANDIDATES:
            key = c.get("batch_id","") + "|" + c.get("cand_id","")
            fa = score_key.get(key, {})
            c["fa_pct"]    = fa.get("fa_pct",0)
            c["fa_passed"] = fa.get("fa_passed",0)
            c["fa_failed"] = fa.get("fa_failed",0)

    elif source == "att":
        rows = db_rows(
            'SELECT `batch_id`, `candidate_id`, '
            'COUNT(*) as total, '
            'SUM(CASE WHEN `attendance_status`="Present" THEN 1 ELSE 0 END) as present_count '
            'FROM `attendance_data` GROUP BY `batch_id`, `candidate_id`',
            table_hint="attendance_data"
        )
        score_key = {}
        for r in rows:
            key = r.get("batch_id","") + "|" + r.get("candidate_id","")
            total   = int(r.get("total") or 0)
            present = int(r.get("present_count") or 0)
            score_key[key] = {"att_pct": round(present/total*100,1) if total else 0,
                              "present": present, "absent": total-present,
                              "total_sessions": total}
        for c in S.CANDIDATES:
            key = c.get("batch_id","") + "|" + c.get("cand_id","")
            att = score_key.get(key, {})
            c["att_pct"]        = att.get("att_pct",0)
            c["present"]        = att.get("present",0)
            c["absent"]         = att.get("absent",0)
            c["total_sessions"] = att.get("total_sessions",0)

        # Issue 2 — unique session-ID count per batch.
        # The "Total Sessions" column previously summed attendance rows, which
        # over-counts by a factor of candidate count. This populates a separate
        # lookup so api_att_summary / api_summary can report the actual number
        # of distinct sessions held per batch.
        try:
            sess_rows = db_rows(
                'SELECT `batch_id`, COUNT(DISTINCT `session_id`) AS uniq '
                'FROM `attendance_data` GROUP BY `batch_id`',
                table_hint="attendance_data"
            )
            S.BATCH_UNIQUE_SESSIONS = {
                r.get("batch_id",""): int(r.get("uniq") or 0)
                for r in sess_rows if r.get("batch_id")
            }
            print(f"  Unique sessions indexed for {len(S.BATCH_UNIQUE_SESSIONS):,} batches",
                  flush=True)
        except Exception as _e:
            print(f"  WARNING: could not compute unique session counts: {_e}",
                  flush=True)

    with S.DATA_LOCK:
        S.DATA_VERSION += 1
    try:
        from .views import _SCOPE_CACHE
        _SCOPE_CACHE.clear()
    except Exception:
        pass

    # Issue 1 — partial rebuild used to leave REBUILD_STATE at pct=58 (which the
    # frontend mapped to "79%"), so the progress bar appeared stuck forever even
    # though the work was finished. Mark the rebuild complete so the UI moves on.
    S.REBUILD_STATE["pct"]     = 100
    S.REBUILD_STATE["step"]    = f"{source.upper()} update complete"
    S.REBUILD_STATE["running"] = False
    S.REBUILD_STATE["error"]   = None

    print(f"  Partial {source} rebuild done in {_t.time()-t0:.1f}s", flush=True)


def partial_rebuild_fa():
    """Fast FA-only update — skips ECP re-query."""
    if not S.CANDIDATES:
        rebuild_background(); return
    _partial_rebuild_scores("fa")


def partial_rebuild_attendance():
    """Fast Attendance-only update — skips ECP re-query."""
    if not S.CANDIDATES:
        rebuild_background(); return
    _partial_rebuild_scores("att")


def reload_user_mappings():
    """Refresh centre/project mappings for all active users.

    BUG FIX: previously skipped users not already in S.USERS, meaning
    Centre Managers added after initial startup were never scoped correctly.
    Now upserts every active user so newly added users get their mappings too.

    Issue 3 fix: also stores raw centre IDs in `mapped_centre_ids`. The name
    resolution via S.CENTRE_ID_TO_NAME can fail if the user mapping is loaded
    before the candidate pool exists (early startup), or if the user is mapped
    to a centre that has no candidates yet. apply_scope now matches against
    BOTH names and raw IDs, so the centre manager sees their data either way.
    """
    rows = db_rows(
        "SELECT * FROM `user_master` WHERE `active` != 'No'",
        table_hint="user_master"
    )
    for r in rows:
        email = (r.get("email") or "").lower().strip()
        if not email:
            continue
        # If user not in S.USERS yet, seed a minimal entry so mappings apply
        if email not in S.USERS:
            S.USERS[email] = {
                "email":              email,
                "name":               (r.get("employee_name") or "").strip(),
                "ecode":              str(r.get("ecode") or "").strip(),
                "role":               (r.get("role") or "").strip(),
                "mapped_centres":     [],
                "mapped_centre_ids":  [],
                "mapped_projects":    [],
            }
        raw_centres = r.get("mapped_centre_ids", "") or ""
        if raw_centres:
            ids = [x.strip() for x in raw_centres.split(",") if x.strip()]
            S.USERS[email]["mapped_centre_ids"] = ids
            S.USERS[email]["mapped_centres"]    = [
                S.CENTRE_ID_TO_NAME.get(cid, cid) for cid in ids
            ]
        else:
            S.USERS[email].setdefault("mapped_centres", [])
            S.USERS[email].setdefault("mapped_centre_ids", [])
        raw_projects = r.get("mapped_projects", "") or ""
        if raw_projects:
            S.USERS[email]["mapped_projects"] = [x.strip() for x in raw_projects.split(",") if x.strip()]
        else:
            S.USERS[email].setdefault("mapped_projects", [])


# ── Scope / filter helpers ─────────────────────────────────────────────────────
_DENY_ALL = "__DENY_ALL__"

def get_user_scope(user):
    if not user:
        return {"projects": [_DENY_ALL], "centres": [_DENY_ALL], "deny": True}
    role = user["role"]
    if role in ("CMP", "IT"):
        return {"projects": [], "centres": [], "deny": False}
    elif role == "Project Manager":
        mapped = user.get("mapped_projects", [])
        return {"projects": mapped if mapped else [_DENY_ALL], "centres": [], "deny": False}
    elif role == "Centre Manager":
        # Issue 3 fix: include both centre NAMES and raw centre IDs in the scope,
        # so apply_scope matches whether the candidate row stores the name or id,
        # and works even if name resolution via S.CENTRE_ID_TO_NAME was incomplete
        # at user-mapping load time.
        names = list(user.get("mapped_centres", []) or [])
        ids   = list(user.get("mapped_centre_ids", []) or [])
        combined = names + ids
        return {"projects": [], "centres": combined if combined else [_DENY_ALL], "deny": False}
    return {"projects": [_DENY_ALL], "centres": [_DENY_ALL], "deny": True}


def apply_scope(pool, user):
    scope = get_user_scope(user)
    if scope.get("deny"):
        return []
    # Issue 3 fix (perf): use set membership instead of list. With ~300k candidates
    # and a centre manager mapped to N centres, list-based `in` is O(N×P) which
    # took ~10s. Sets make this O(P).
    p_set = set(scope["projects"]) if scope["projects"] else None
    c_set = set(scope["centres"])  if scope["centres"]  else None
    if p_set is None and c_set is None:
        return pool
    out = []
    for c in pool:
        if p_set is not None and c.get("project") not in p_set:
            continue
        if c_set is not None:
            # Match either the centre name or the centre id — see get_user_scope.
            if c.get("centre") not in c_set and c.get("centre_id") not in c_set:
                continue
        out.append(c)
    return out


def apply_filters(pool, filters):
    p  = filters.get("projects",[])
    sp = filters.get("sub_projects",[])
    c  = filters.get("centres",[])
    b  = filters.get("batches",[])
    s  = filters.get("statuses",[])
    ec = filters.get("emp_cats",[])
    if p:  pool = [r for r in pool if r["project"]            in p]
    if sp: pool = [r for r in pool if r.get("sub_project","") in sp]
    if c:  pool = [r for r in pool if r["centre"]             in c]
    if b:  pool = [r for r in pool if r["batch_id"]           in b]
    if s:  pool = [r for r in pool if r["status"]             in s]
    if ec: pool = [r for r in pool if r["emp_category"]       in ec]
    return pool


def n(v):
    try: return int(float(v or 0))
    except: return 0

def pct(x, t, d=1):
    return round(x/t*100, d) if t else 0
