import json
from collections import defaultdict
from datetime import date

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .models import (BatchPlan, Centre, ClusterMaster, CommunityCollege,
                     DemandSupply, HyperlocalJob, ITIDiplomaMaster,
                     ManpowerStaff, NapsEligible,
                     SAHIDemand, SambhavCommunity, SFInterventionCollege)

# ── helpers ───────────────────────────────────────────────────────────────────

MONTHS_ORDER = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
MONTH_LABELS = {
    4: 'Apr', 5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Aug', 9: 'Sep',
    10: 'Oct', 11: 'Nov', 12: 'Dec', 1: 'Jan', 2: 'Feb', 3: 'Mar',
}


def fy_years(fy_str):
    parts = fy_str.split('-')
    y1 = int(parts[0])
    return y1, y1 + 1


def month_in_fy(d, fy_str):
    if d is None:
        return False
    y1, y2 = fy_years(fy_str)
    if d.month >= 4:
        return d.year == y1
    return d.year == y2


def get_available_fys():
    fys = set()
    for bp in BatchPlan.objects.all():
        for d in (
            bp.batch_planned_start_date,
            bp.batch_actual_start_date,
            bp.assessment_actual_certification_date,
            bp.placed_date,
        ):
            if d:
                fy_y = d.year if d.month >= 4 else d.year - 1
                fys.add(f'{fy_y}-{str(fy_y + 1)[2:]}')
    if not fys:
        fys.add('2026-27')
    return sorted(fys, reverse=True)


def fy_to_date_range(fy):
    """'2026-27' → (date(2026,4,1), date(2027,3,31)). Returns (None, None) if unparseable."""
    from datetime import date
    try:
        start_year = int(fy.split('-')[0])
        return date(start_year, 4, 1), date(start_year + 1, 3, 31)
    except (ValueError, AttributeError):
        return None, None


def filter_batchplan_by_fy(qs, fy):
    """Return BatchPlan rows whose planned-start, actual-start, certification or
    placement date falls within the given FY window. A batch is 'in this FY' if
    ANY of its date fields lands in that window."""
    from django.db.models import Q
    start, end = fy_to_date_range(fy)
    if not start:
        return qs
    cond = (
        Q(batch_planned_start_date__gte=start,                batch_planned_start_date__lte=end) |
        Q(batch_actual_start_date__gte=start,                 batch_actual_start_date__lte=end) |
        Q(assessment_actual_certification_date__gte=start,    assessment_actual_certification_date__lte=end) |
        Q(placed_date__gte=start,                             placed_date__lte=end)
    )
    return qs.filter(cond)


def pct(actual, target):
    if target > 0:
        return round(actual * 100 / target)
    return 0


def normalise_eid(raw):
    """Normalise employee IDs: '411067.0' → '411067', strip whitespace."""
    s = str(raw or '').strip()
    if s.endswith('.0') and s[:-2].isdigit():
        return s[:-2]
    return s


def build_staff_status(candidates_qs, manpower_qs, centre_ids=None):
    """
    Build Trainer + Mobilizer status from Manpower_Master_1 × Trainer_Target / Mobilsier_Target.

    NEW LOGIC (target-based):
      MOBILIZER → row per Mobilizer in Manpower (filtered to centre_ids if given).
        Match by Ecode = MobiliserTarget.mobiliser_id.
        Matched   → show this month's E Target / E Act / % achieved (rolled up).
        Unmatched → "Idle (Target not assigned)".
      TRAINER → row per Trainer in Manpower (filtered to centre_ids if given).
        Match by Ecode = TrainerTarget.trainer_id.
        Matched   → show day-wise hours (May 1-31 etc. dynamic).
        Unmatched → "Idle (Target not assigned)".

    `candidates_qs` is kept for signature compat but unused.
    `centre_ids` (optional) restricts the manpower roster (e.g. on Centre detail).
    """
    from collections import defaultdict
    from dashboard.models import MobiliserTarget, TrainerTarget, TrainerTargetDay

    # ── Roster (from Manpower master, filtered by centres) ──────────────────
    mp_qs = manpower_qs
    if centre_ids:
        mp_qs = mp_qs.filter(centre_id__in=centre_ids)
    mp_list = list(mp_qs)

    def _role_norm(r):
        return (r or '').strip().lower()

    trainers   = [s for s in mp_list if 'trainer'   in _role_norm(s.role)]
    mobilizers = [s for s in mp_list if 'mobilizer' in _role_norm(s.role)]

    # ── Mobilizer roll-up by Ecode ──────────────────────────────────────────
    mob_targets_by_eid = defaultdict(lambda: {'e_target': 0, 'c_target': 0,
                                              'p_target': 0, 'e_act': 0,
                                              'batches': 0, 'month_label': ''})
    for mt in MobiliserTarget.objects.all():
        d = mob_targets_by_eid[mt.mobiliser_id]
        d['e_target'] += mt.e_target
        d['c_target'] += mt.c_target
        d['p_target'] += mt.p_target
        d['e_act']    += mt.e_act
        d['batches']  += 1
        if mt.target_month_label:
            d['month_label'] = mt.target_month_label

    mob_month_label = ''
    if mob_targets_by_eid:
        # pick any non-empty label
        for d in mob_targets_by_eid.values():
            if d['month_label']:
                mob_month_label = d['month_label']; break

    mobilizer_rows = []
    for s in mobilizers:
        try:
            eid_int = int(str(s.ecode).strip())
        except (TypeError, ValueError):
            eid_int = None
        info = mob_targets_by_eid.get(eid_int)
        if info:
            etarget, eact = info['e_target'], info['e_act']
            pct_val = (eact / etarget * 100) if etarget else 0
            status, status_class = 'Active', 'occupied'
            row = {
                'eid':         str(s.ecode),
                'name':        s.employee_name,
                'centre':      s.center_name_ops or '—',
                'status':      status,
                'status_class': status_class,
                'e_target':    etarget,
                'e_act':       eact,
                'pct':         round(pct_val, 1),
                'batches':     info['batches'],
                'in_target':   True,
            }
        else:
            row = {
                'eid':         str(s.ecode),
                'name':        s.employee_name,
                'centre':      s.center_name_ops or '—',
                'status':      'Idle (Target not assigned)',
                'status_class': 'idle',
                'e_target':    0,
                'e_act':       0,
                'pct':         0,
                'batches':     0,
                'in_target':   False,
            }
        mobilizer_rows.append(row)

    mobilizer_rows.sort(key=lambda r: (r['in_target'] is False, r['centre'], r['name']))

    # ── Trainer roll-up by Ecode (with day-wise hours) ──────────────────────
    # Collect all distinct date columns observed in Trainer_Target → these are the
    # day headers in the table.
    all_dates = sorted(set(TrainerTargetDay.objects.values_list('date', flat=True).distinct()))

    # Hours per (trainer_id, date)
    hours_by_eid_date = defaultdict(float)
    targets_by_eid    = defaultdict(list)  # trainer_id -> list of TrainerTarget rows
    for tt in TrainerTarget.objects.prefetch_related('days'):
        targets_by_eid[tt.trainer_id].append(tt)
        for d in tt.days.all():
            hours_by_eid_date[(tt.trainer_id, d.date)] += d.hours

    trainer_rows = []
    for s in trainers:
        try:
            eid_int = int(str(s.ecode).strip())
        except (TypeError, ValueError):
            eid_int = None
        targets = targets_by_eid.get(eid_int, [])
        if targets:
            day_hours = [round(hours_by_eid_date.get((eid_int, d), 0), 1) for d in all_dates]
            total_hours = round(sum(day_hours), 1)
            days_worked = sum(1 for h in day_hours if h > 0)
            row = {
                'eid':          str(s.ecode),
                'name':         s.employee_name,
                'centre':       s.center_name_ops or '—',
                'status':       'Active',
                'status_class': 'occupied',
                'day_hours':    day_hours,
                'total_hours':  total_hours,
                'days_worked':  days_worked,
                'in_target':    True,
            }
        else:
            row = {
                'eid':          str(s.ecode),
                'name':         s.employee_name,
                'centre':       s.center_name_ops or '—',
                'status':       'Idle (Target not assigned)',
                'status_class': 'idle',
                'day_hours':    [0] * len(all_dates),
                'total_hours':  0,
                'days_worked':  0,
                'in_target':    False,
            }
        trainer_rows.append(row)

    trainer_rows.sort(key=lambda r: (r['in_target'] is False, r['centre'], r['name']))

    return {
        # Trainer
        'trainer_rows':       trainer_rows,
        'trainer_active':     sum(1 for r in trainer_rows if r['in_target']),
        'trainer_idle':       sum(1 for r in trainer_rows if not r['in_target']),
        'trainer_dates':      [d.strftime('%d') for d in all_dates],  # ['01','02',…]
        'trainer_month':      all_dates[0].strftime('%b %Y') if all_dates else '',
        # Mobilizer
        'mobilizer_rows':     mobilizer_rows,
        'mobilizer_active':   sum(1 for r in mobilizer_rows if r['in_target']),
        'mobilizer_idle':     sum(1 for r in mobilizer_rows if not r['in_target']),
        'mobilizer_month':    mob_month_label,
    }


def build_mom_rows(batches_qs, fy):
    """
    Month-on-Month rows for one FY.

    Per Q1A: actuals come from BatchPlan's fy_e_act / fy_c_act / fy_p_act count
    columns (the curated FY-26-27 totals on each row).
    Per Q2A: the whole batch's count is bucketed into the month of the
    corresponding actual date (Batch Actual Start / Assessment Actual / Placed).
    Batches with a count but no date land in 'undated' (excluded from the chart,
    surfaced separately).

    Targets: bucketed by planned dates × planned counts (unchanged).
    """
    enrol_target = defaultdict(int)
    cert_target  = defaultdict(int)
    place_target = defaultdict(int)
    enrol_actual = defaultdict(int)
    cert_actual  = defaultdict(int)
    place_actual = defaultdict(int)

    for bp in batches_qs:
        # Targets
        d = bp.batch_planned_start_date
        if d and month_in_fy(d, fy):
            enrol_target[d.month] += bp.final_enrolment_planned
        d = bp.certification_planned_start_date
        if d and month_in_fy(d, fy):
            cert_target[d.month] += bp.final_certification_planned
        d = bp.placement_planned_end_date
        if d and month_in_fy(d, fy):
            place_target[d.month] += bp.final_placement_planned

        # Actuals: per-batch FY count, bucketed by actual date
        d = bp.batch_actual_start_date
        if d and month_in_fy(d, fy) and bp.fy_e_act:
            enrol_actual[d.month] += bp.fy_e_act
        d = bp.assessment_actual_certification_date
        if d and month_in_fy(d, fy) and bp.fy_c_act:
            cert_actual[d.month] += bp.fy_c_act
        d = bp.placed_date
        if d and month_in_fy(d, fy) and bp.fy_p_act:
            place_actual[d.month] += bp.fy_p_act

    rows = []
    for m in MONTHS_ORDER:
        et = enrol_target[m]; ea = enrol_actual[m]
        ct = cert_target[m]; ca = cert_actual[m]
        pt = place_target[m]; pa = place_actual[m]
        rows.append({
            'month_num': m,
            'display': MONTH_LABELS[m],
            'enrol_target': et, 'enrol_actual': ea, 'enrol_pct': pct(ea, et),
            'cert_target': ct, 'cert_actual': ca, 'cert_pct': pct(ca, ct),
            'place_target': pt, 'place_actual': pa, 'place_pct': pct(pa, pt),
        })
    return rows


# ── HOME PAGE ─────────────────────────────────────────────────────────────────

def home(request):
    cluster_filter      = request.GET.get('cluster', '')
    sub_cluster_filter  = request.GET.get('sub_cluster', '')
    coverage_filter     = request.GET.get('coverage', '')

    # Cluster list — union of Center Master + Cluster Master (so empty-centre clusters
    # like Indore / Goa / Dewas, which exist in Cluster Master, still appear).
    clusters_centre = set(
        Centre.objects.exclude(cluster='').exclude(cluster=None)
        .values_list('cluster', flat=True)
    )
    clusters_master = set(
        ClusterMaster.objects.exclude(cluster='')
        .values_list('cluster', flat=True)
    )
    clusters = sorted(clusters_centre | clusters_master)
    # Module-Coverage also narrows the Cluster dropdown
    clusters = _filter_clusters_by_coverage(clusters, coverage_filter)

    sc_qs_centre = Centre.objects.exclude(sub_cluster='').exclude(sub_cluster=None)
    sc_qs_master = ClusterMaster.objects.exclude(sub_cluster='')
    if cluster_filter:
        sc_qs_centre = sc_qs_centre.filter(cluster=cluster_filter)
        sc_qs_master = sc_qs_master.filter(cluster=cluster_filter)
    sub_clusters = sorted(
        set(sc_qs_centre.values_list('sub_cluster', flat=True))
        | set(sc_qs_master.values_list('sub_cluster', flat=True))
    )
    # Apply the Module-Coverage filter (dropdown narrower only — doesn't scope metrics)
    sub_clusters = _filter_sub_clusters_by_coverage(sub_clusters, coverage_filter, cluster_filter)

    # Map URL for the currently selected sub-cluster (if any)
    selected_map_url = ''
    selected_state   = ''
    if sub_cluster_filter:
        cm_row = ClusterMaster.objects.filter(sub_cluster=sub_cluster_filter).first()
        if cm_row:
            selected_map_url = cm_row.map_url
            selected_state   = cm_row.state

    return render(request, 'dashboard/home.html', {
        'clusters':            clusters,
        'sub_clusters':        sub_clusters,
        'cluster_filter':      cluster_filter,
        'sub_cluster_filter':  sub_cluster_filter,
        'coverage_filter':     coverage_filter,
        'coverage_options':    COVERAGE_OPTIONS,
        'selected_map_url':    selected_map_url,
        'selected_state':      selected_state,
    })


# ── Sub-cluster module-coverage helpers ───────────────────────────────────────
#
# A sub-cluster's "coverage profile" is which of the 4 modules have data for it:
#   • Employability ✓  : ≥1 Centre exists in that sub-cluster
#   • SMB           ✓  : ≥1 Centre in that sub-cluster runs a BatchPlan QP that
#                        is marked NAPS Eligible='Yes' in the NAPS Eligible
#                        master.  (Hyperlocal Jobs no longer contribute.)
#   • SAHI          ✓  : ≥1 SAHIDemand row for that sub-cluster
#   • Sambhav       ✓  : ≥1 SambhavCommunity row for that sub-cluster

# Coverage codes used by the Home page's "Module Coverage" dropdown.  Each is an
# EXACT match — e.g. "E-SMB" means the sub-cluster has Employability + SMB and
# nothing else (no SAHI, no Sambhav).
COVERAGE_PATTERNS = {
    'E':             {'employability': True,  'smb': False, 'sahi': False, 'sambhav': False},
    'E-SMB':         {'employability': True,  'smb': True,  'sahi': False, 'sambhav': False},
    'E-SMB-SAHI':    {'employability': True,  'smb': True,  'sahi': True,  'sambhav': False},
    'E-SMB-SAHI-SC': {'employability': True,  'smb': True,  'sahi': True,  'sambhav': True},
    'SAHI':          {'employability': False, 'smb': False, 'sahi': True,  'sambhav': False},
}

COVERAGE_OPTIONS = [
    ('E-SMB-SAHI-SC', 'Employability-SMB-SAHI-Sambhav Community'),
    ('E-SMB-SAHI',    'Employability-SMB-SAHI'),
    ('E-SMB',         'Employability-SMB'),
    ('E',             'Employability'),
    ('SAHI',          'SAHI'),
]


def _compute_sub_cluster_coverage(cluster=''):
    """Return {sub_cluster: {employability/smb/sahi/sambhav: bool}} for a scope."""
    cm_qs      = ClusterMaster.objects.exclude(sub_cluster='')
    centre_qs  = Centre.objects.exclude(sub_cluster='').exclude(sub_cluster=None)
    demand_qs  = SAHIDemand.objects.exclude(sub_cluster='')
    sambhav_qs = SambhavCommunity.objects.exclude(sub_cluster='')
    if cluster:
        cm_qs      = cm_qs.filter(cluster=cluster)
        centre_qs  = centre_qs.filter(cluster=cluster)
        demand_qs  = demand_qs.filter(cluster=cluster)
        sambhav_qs = sambhav_qs.filter(cluster=cluster)

    sc_master  = set(cm_qs.values_list('sub_cluster', flat=True))
    sc_centre  = set(centre_qs.values_list('sub_cluster', flat=True))
    sc_demand  = set(demand_qs.values_list('sub_cluster', flat=True))
    sc_sambhav = set(sambhav_qs.values_list('sub_cluster', flat=True))
    sub_clusters = sorted(sc_master | sc_centre | sc_demand | sc_sambhav)

    centre_to_sc = dict(centre_qs.values_list('centre_id', 'sub_cluster'))
    centre_ids   = list(centre_to_sc.keys())

    # NEW SMB rule — only QPs explicitly marked NAPS Eligible='Yes' count.
    naps_yes_qps = set(
        NapsEligible.objects.filter(naps_eligible='Yes')
        .values_list('qp', flat=True)
    )
    naps_sub_clusters = set(
        centre_to_sc[cid] for cid in
        BatchPlan.objects.filter(centre_id__in=centre_ids, qp__in=naps_yes_qps)
        .values_list('centre_id', flat=True).distinct()
        if cid in centre_to_sc
    )

    return {
        sc: {
            'employability': sc in sc_centre,
            'smb':           sc in naps_sub_clusters,
            'sahi':          sc in sc_demand,
            'sambhav':       sc in sc_sambhav,
        }
        for sc in sub_clusters
    }


def _filter_sub_clusters_by_coverage(sub_clusters, coverage_code, cluster=''):
    """Apply an EXACT-match Module Coverage filter to a sub-cluster list."""
    if not coverage_code or coverage_code not in COVERAGE_PATTERNS:
        return sub_clusters
    target  = COVERAGE_PATTERNS[coverage_code]
    cov_map = _compute_sub_cluster_coverage(cluster)
    return [sc for sc in sub_clusters if cov_map.get(sc) == target]


def _coverage_matching_sub_clusters(coverage_code):
    """
    Return the GLOBAL set of sub-clusters matching the EXACT coverage pattern,
    or None when no coverage is selected (= no scoping).

    Used by every metric API to scope data when Module Coverage is active.
    """
    if not coverage_code or coverage_code not in COVERAGE_PATTERNS:
        return None
    target  = COVERAGE_PATTERNS[coverage_code]
    cov_map = _compute_sub_cluster_coverage('')   # always global for metric scoping
    return {sc for sc, cov in cov_map.items() if cov == target}


def _sub_cluster_to_cluster_map():
    """sub_cluster → cluster lookup, built from Centre + ClusterMaster."""
    sc_to_cluster = dict(
        ClusterMaster.objects.exclude(sub_cluster='').exclude(cluster='')
        .values_list('sub_cluster', 'cluster')
    )
    for sc, cl in (
        Centre.objects.exclude(sub_cluster='').exclude(cluster='').exclude(cluster=None)
        .values_list('sub_cluster', 'cluster')
    ):
        sc_to_cluster.setdefault(sc, cl)
    return sc_to_cluster


def _filter_clusters_by_coverage(clusters, coverage_code):
    """
    Narrow a cluster list to only those that have at least one sub-cluster
    matching the given EXACT-match Module Coverage code.
    """
    if not coverage_code or coverage_code not in COVERAGE_PATTERNS:
        return clusters
    target  = COVERAGE_PATTERNS[coverage_code]
    cov_map = _compute_sub_cluster_coverage('')   # global
    matching_scs = {sc for sc, cov in cov_map.items() if cov == target}

    sc_to_cluster = _sub_cluster_to_cluster_map()
    matching_clusters = {
        sc_to_cluster[sc] for sc in matching_scs if sc in sc_to_cluster
    }
    return [c for c in clusters if c in matching_clusters]


def clusters_api(request):
    """
    Cluster list (union of Centre + ClusterMaster), optionally narrowed by the
    Home page's Module Coverage dropdown.

      ?coverage=<code>   keep only clusters that have ≥1 sub-cluster matching
                         the EXACT coverage pattern (see COVERAGE_PATTERNS)
    """
    coverage = request.GET.get('coverage', '')

    clusters_centre = set(
        Centre.objects.exclude(cluster='').exclude(cluster=None)
        .values_list('cluster', flat=True)
    )
    clusters_master = set(
        ClusterMaster.objects.exclude(cluster='')
        .values_list('cluster', flat=True)
    )
    clusters = sorted(clusters_centre | clusters_master)
    clusters = _filter_clusters_by_coverage(clusters, coverage)
    return JsonResponse({'clusters': clusters})


def cluster_sub_clusters_api(request):
    """
    Sub-clusters under a given cluster — union of Centre + ClusterMaster.

    Optional query params:
      ?cluster=<name>     scope to a single cluster
      ?coverage=<code>    narrow to sub-clusters matching the Module-Coverage
                          dropdown (EXACT match — see COVERAGE_PATTERNS)
    """
    cluster  = request.GET.get('cluster', '')
    coverage = request.GET.get('coverage', '')

    centre_sc = Centre.objects.exclude(sub_cluster='').exclude(sub_cluster=None)
    master_sc = ClusterMaster.objects.exclude(sub_cluster='')
    if cluster:
        centre_sc = centre_sc.filter(cluster=cluster)
        master_sc = master_sc.filter(cluster=cluster)
    sub_clusters = sorted(
        set(centre_sc.values_list('sub_cluster', flat=True))
        | set(master_sc.values_list('sub_cluster', flat=True))
    )
    sub_clusters = _filter_sub_clusters_by_coverage(sub_clusters, coverage, cluster)
    return JsonResponse({'sub_clusters': sub_clusters})


def nav_counts_api(request):
    """Live counts for the navbar pills. Depends on optional 'cluster' query param."""
    from dashboard.context_processors import cluster_counts
    data = cluster_counts(request)
    return JsonResponse({
        'cluster_count':     data['nav_cluster_count'],
        'sub_cluster_count': data['nav_sub_cluster_count'],
    })


def sub_cluster_map_api(request):
    """Return the Google Maps URL + State for a selected sub-cluster."""
    sub_cluster = request.GET.get('sub_cluster', '')
    if not sub_cluster:
        return JsonResponse({'map_url': '', 'state': '', 'cluster': '', 'sub_cluster_id': ''})
    row = ClusterMaster.objects.filter(sub_cluster=sub_cluster).first()
    if not row:
        return JsonResponse({'map_url': '', 'state': '', 'cluster': '', 'sub_cluster_id': ''})
    return JsonResponse({
        'map_url':         row.map_url,
        'state':           row.state,
        'cluster':         row.cluster,
        'sub_cluster_id':  row.sub_cluster_id,
    })


def sub_cluster_coverage_api(request):
    """
    Per-sub-cluster data-coverage matrix.

    Modes:
      1) **Global** (no cluster filter) → totals only (for Home count cards).
      2) **Per-cluster** (?cluster=X) → rows + totals (for coverage table).

    A `?coverage=` Module Coverage filter further restricts the rows/totals
    to sub-clusters matching the EXACT profile.

    Definitions:
      Employability ✓ : ≥1 Centre exists in that sub-cluster
      SMB           ✓ : ≥1 Centre in that sub-cluster runs a BatchPlan QP that
                        is marked NAPS Eligible='Yes' in the NAPS Eligible
                        master.  (Hyperlocal Jobs no longer contribute.)
      SAHI          ✓ : ≥1 SAHIDemand row for that sub-cluster
      Sambhav       ✓ : ≥1 SambhavCommunity row for that sub-cluster

    Single source of truth: `_compute_sub_cluster_coverage()`.
    """
    cluster  = request.GET.get('cluster', '')
    coverage = request.GET.get('coverage', '')

    cov_map = _compute_sub_cluster_coverage(cluster)

    # Module-Coverage further restricts to matching sub-clusters
    matching_scs = _coverage_matching_sub_clusters(coverage)
    if matching_scs is not None:
        cov_map = {sc: cov for sc, cov in cov_map.items() if sc in matching_scs}

    rows = [{'sub_cluster': sc, **cov} for sc, cov in cov_map.items()]
    rows.sort(key=lambda r: r['sub_cluster'])

    totals = {
        'rows':          len(rows),
        'employability': sum(1 for r in rows if r['employability']),
        'smb':           sum(1 for r in rows if r['smb']),
        'sahi':          sum(1 for r in rows if r['sahi']),
        'sambhav':       sum(1 for r in rows if r['sambhav']),
    }

    return JsonResponse({
        'rows':    rows if cluster else [],   # rows only in per-cluster mode
        'totals':  totals,
        'show':    bool(cluster),
        'cluster': cluster,
    })


def cluster_map_data_api(request):
    """
    Geo-data for the Home page Cluster Impact Map.

    Returns one record per sub-cluster, each carrying a `locations` list of
    [lat, lng] pairs. The frontend renders one green marker per location.

    For sub-clusters whose Map URL contains explicit stops (35 of the 86),
    each stop becomes its own location. For single-place URLs (51 of the 86),
    the single `(lat, lng)` center pair is used.

    Filters (optional):
      ?cluster=<name>
      ?sub_cluster=<name>
      ?coverage=<code>      Module Coverage profile (EXACT match)
    """
    cluster     = request.GET.get('cluster', '')
    sub_cluster = request.GET.get('sub_cluster', '')
    coverage    = request.GET.get('coverage', '')

    qs = ClusterMaster.objects.exclude(lat__isnull=True).exclude(lng__isnull=True)
    if cluster:
        qs = qs.filter(cluster=cluster)
    if sub_cluster:
        qs = qs.filter(sub_cluster=sub_cluster)
    matching_scs = _coverage_matching_sub_clusters(coverage)
    if matching_scs is not None:
        qs = qs.filter(sub_cluster__in=matching_scs)

    rows, total_locations = [], 0
    for cm in qs:
        # Prefer explicit stops; fall back to the (lat,lng) center otherwise.
        locations = list(cm.stops) if cm.stops else [[cm.lat, cm.lng]]
        total_locations += len(locations)
        rows.append({
            'sub_cluster_id': cm.sub_cluster_id,
            'cluster':        cm.cluster,
            'sub_cluster':    cm.sub_cluster,
            'state':          cm.state,
            'locations':      locations,
            'map_url':        cm.map_url,
        })

    return JsonResponse({
        'rows':            rows,
        'count':           len(rows),
        'total_locations': total_locations,
    })


def sambhav_view(request):
    """Sambhav Community page — filter by Home's Cluster + Sub Cluster."""
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')

    qs = SambhavCommunity.objects.all()
    if cluster:     qs = qs.filter(cluster=cluster)
    if sub_cluster: qs = qs.filter(sub_cluster=sub_cluster)
    rows = list(qs.order_by('cluster', 'sub_cluster', 'project'))

    return render(request, 'dashboard/sambhav.html', {
        'cluster_filter':     cluster,
        'sub_cluster_filter': sub_cluster,
        'rows':               rows,
        'total':              len(rows),
        'projects':           len(set(r.project for r in rows if r.project)),
    })


def home_summary_api(request):
    """
    Home page summary API. Driven by Cluster + Sub Cluster + Module Coverage.
    SAHI card now bridges via direct match on Cluster / Sub Cluster
    (SAHIDemand and Centre share the same taxonomy now).

    When Module Coverage is selected, every queryset is further restricted to
    sub-clusters matching that EXACT coverage profile.  So e.g. coverage=
    "E-SMB-SAHI" zeros out the Sambhav card (those sub-clusters have no
    Sambhav community data by definition).
    """
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')
    coverage     = request.GET.get('coverage', '')

    matching_scs = _coverage_matching_sub_clusters(coverage)

    # ── Centre set for Employability + SMB ────────────────────────────────
    centre_qs = Centre.objects.all()
    if cluster:
        centre_qs = centre_qs.filter(cluster=cluster)
    if sub_cluster:
        centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
    if matching_scs is not None:
        centre_qs = centre_qs.filter(sub_cluster__in=matching_scs)
    centre_ids = list(centre_qs.values_list('centre_id', flat=True))

    scope_active = bool(cluster or sub_cluster or matching_scs is not None)

    # ── 1A: "Centres" = unique centres that have at least one BatchPlan row ──
    batched_ids = set(
        BatchPlan.objects.filter(centre_id__in=centre_ids)
        .values_list('centre_id', flat=True).distinct()
    ) if scope_active else set(
        BatchPlan.objects.values_list('centre_id', flat=True).distinct()
    )
    if scope_active:
        centre_count = len(set(centre_ids) & batched_ids)
    else:
        centre_count = len(batched_ids)

    batches      = BatchPlan.objects.filter(centre_id__in=centre_ids) if scope_active \
                   else BatchPlan.objects.all()
    enrol_target = sum(b.final_enrolment_planned for b in batches)
    cert_target  = sum(b.final_certification_planned for b in batches)
    place_target = sum(b.final_placement_planned for b in batches)

    if scope_active:
        centre_qps = set(
            BatchPlan.objects.filter(centre_id__in=centre_ids)
            .exclude(qp='').values_list('qp', flat=True)
        )
        qp_qs    = NapsEligible.objects.filter(qp__in=centre_qps)
        qp_count = qp_qs.count()
        naps_yes = qp_qs.filter(naps_eligible='Yes').count()
        hj_count = HyperlocalJob.objects.filter(centre_id__in=centre_ids).count()
    else:
        qp_count = NapsEligible.objects.count()
        naps_yes = NapsEligible.objects.filter(naps_eligible='Yes').count()
        hj_count = HyperlocalJob.objects.count()

    # ── SAHI card — direct match on Cluster / Sub Cluster ─────────────────
    sahi_demand_qs = SAHIDemand.objects.all()
    if cluster:
        sahi_demand_qs = sahi_demand_qs.filter(cluster=cluster)
    if sub_cluster:
        sahi_demand_qs = sahi_demand_qs.filter(sub_cluster=sub_cluster)
    if matching_scs is not None:
        sahi_demand_qs = sahi_demand_qs.filter(sub_cluster__in=matching_scs)

    sahi_clients = sahi_demand_qs.exclude(existing_client='') \
                                 .values('existing_client').distinct().count()
    sahi_total_hc       = sum(d.hc or 0 for d in sahi_demand_qs)
    sahi_monthly_demand = sum(d.monthly_demand or 0 for d in sahi_demand_qs)
    # SAHI Centres = centres in the same Cluster/Sub Cluster scope (already in centre_qs)
    sahi_centre_count   = centre_qs.count() if scope_active else Centre.objects.count()

    # ── Sambhav Community card ────────────────────────────────────────────
    sc_qs = SambhavCommunity.objects.all()
    if cluster:     sc_qs = sc_qs.filter(cluster=cluster)
    if sub_cluster: sc_qs = sc_qs.filter(sub_cluster=sub_cluster)
    if matching_scs is not None:
        sc_qs = sc_qs.filter(sub_cluster__in=matching_scs)
    sc_projects  = sc_qs.exclude(project='').values('project').distinct().count()
    sc_locations = sc_qs.count()

    return JsonResponse({
        'employability': {
            'centre_count':  centre_count,
            'enrol_target':  enrol_target,
            'cert_target':   cert_target,
            'place_target':  place_target,
        },
        'smb': {
            'qp_count':            qp_count,
            'naps_eligible_count': naps_yes,
            'hj_count':            hj_count,
        },
        'sahi': {
            'clients':         sahi_clients,
            'total_hc':        sahi_total_hc,
            'monthly_demand':  sahi_monthly_demand,
            'centre_count':    sahi_centre_count,
        },
        'sambhav': {
            'projects':  sc_projects,
            'locations': sc_locations,
        },
    })


# ── SMB PAGE ──────────────────────────────────────────────────────────────────

def smb_view(request):
    cluster_filter      = request.GET.get('cluster', '')
    sub_cluster_filter  = request.GET.get('sub_cluster', '')

    centre_qs = Centre.objects.all()
    if cluster_filter:
        centre_qs = centre_qs.filter(cluster=cluster_filter)
    if sub_cluster_filter:
        centre_qs = centre_qs.filter(sub_cluster=sub_cluster_filter)
    centres = centre_qs.order_by('centre_name')

    # Scope HJ QP dropdown to centres in this cluster
    centre_ids = list(centres.values_list('centre_id', flat=True))
    hj_qs = HyperlocalJob.objects.exclude(course='')
    if centre_ids:
        hj_qs = hj_qs.filter(centre_id__in=centre_ids)
    qps = sorted(set(hj_qs.values_list('course', flat=True)))

    return render(request, 'dashboard/smb.html', {
        'cluster_filter':      cluster_filter,
        'sub_cluster_filter':  sub_cluster_filter,
        'centres':             centres,
        'qps':                 qps,
    })


def naps_api(request):
    """
    NAPS Eligible QP Details — shows QP × NAPS Eligibility × Course details
    for the QPs that are in scope based on the SMB main filter bar (BU/TM/
    Project/Centre/QP) plus optional Home cluster/sub_cluster context.

    QPs are derived from NAPSData (the source-of-truth for which QPs are
    actually running in each centre/project) — same as the Certification
    Pipeline table — so this view is consistent with what's shown above it.
    """
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')
    centre_id    = request.GET.get('centre_id', '')
    cs_bu_head   = request.GET.get('cs_bu_head', '')
    cs_tm_name   = request.GET.get('cs_tm_name', '')
    cs_project   = request.GET.get('cs_project', '')
    cs_qp_course = request.GET.get('cs_qp', '')
    # cs_cert_window kept for backward-compat URLs but no longer used
    # since the Cert Schedule table was removed.

    qs = NapsEligible.objects.all()

    any_scope = any([
        cluster, sub_cluster, centre_id,
        cs_bu_head, cs_tm_name, cs_project, cs_qp_course
    ])

    if any_scope:
        # Resolve scope filters → centre_ids universe
        centre_qs = Centre.objects.all()
        if cluster:     centre_qs = centre_qs.filter(cluster=cluster)
        if sub_cluster: centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
        if cs_bu_head:  centre_qs = centre_qs.filter(bu_head=cs_bu_head)
        if cs_tm_name:  centre_qs = centre_qs.filter(tm_name=cs_tm_name)
        if centre_id:   centre_qs = centre_qs.filter(centre_id=centre_id)
        centre_ids = list(centre_qs.values_list('centre_id', flat=True))

        # Pull QP set from NAPSData (consistent with Certification Pipeline)
        from dashboard.models import NAPSData
        nd_qs = NAPSData.objects.filter(naps_eligible__iexact='Yes')
        if centre_ids:
            nd_qs = nd_qs.filter(centre_id__in=centre_ids)
        if cs_project:
            nd_qs = nd_qs.filter(project_name=cs_project)
        if cs_qp_course:
            nd_qs = nd_qs.filter(qp_name=cs_qp_course)

        qp_set = set(
            nd_qs.exclude(qp_name='').values_list('qp_name', flat=True).distinct()
        )

        # Fallback: also include BatchPlan-derived QPs for the scope
        # (handles centres/projects that have a BatchPlan row but no NAPSData yet)
        bp_qs = BatchPlan.objects.all()
        if centre_ids: bp_qs = bp_qs.filter(centre_id__in=centre_ids)
        if cs_project: bp_qs = bp_qs.filter(project_name=cs_project)
        if cs_qp_course: bp_qs = bp_qs.filter(qp=cs_qp_course)
        qp_set |= set(bp_qs.exclude(qp='').values_list('qp', flat=True).distinct())

        qs = qs.filter(qp__in=qp_set) if qp_set else qs.none()

    # Local table-level filters
    if request.GET.get('qp'):
        qs = qs.filter(qp__icontains=request.GET['qp'])
    if request.GET.get('naps_eligible'):
        qs = qs.filter(naps_eligible__iexact=request.GET['naps_eligible'])

    data = list(qs.values(
        'qp', 'naps_eligible', 'course_name', 'course_type',
        'sector', 'minimum_qualification', 'on_job_training'
    ).order_by('qp'))
    return JsonResponse({'results': data, 'count': len(data)})


# ── SAHI PAGE ─────────────────────────────────────────────────────────────────

def sahi_view(request):
    """SAHI page — uses new Cluster + Sub Cluster taxonomy (matches Home)."""
    cluster_filter     = request.GET.get('cluster', '')
    sub_cluster_filter = request.GET.get('sub_cluster', '')

    # Map URL for the selected sub cluster
    selected_map_url = ''
    selected_state   = ''
    if sub_cluster_filter:
        cm_row = ClusterMaster.objects.filter(sub_cluster=sub_cluster_filter).first()
        if cm_row:
            selected_map_url = cm_row.map_url
            selected_state   = cm_row.state

    return render(request, 'dashboard/sahi.html', {
        'cluster_filter':      cluster_filter,
        'sub_cluster_filter':  sub_cluster_filter,
        'selected_map_url':    selected_map_url,
        'selected_state':      selected_state,
    })


# ── SAHI APIs ─────────────────────────────────────────────────────────────────

def sahi_filter_options_api(request):
    """
    Cascading filter options for the SAHI page.
    Drives from Cluster → Sub Cluster (the new taxonomy).
    Union of Cluster Master + Center Master + SAHIDemand so all known
    clusters/sub-clusters appear, even those without centres or demand.
    """
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')

    clusters = sorted(
        set(ClusterMaster.objects.exclude(cluster='').values_list('cluster', flat=True))
        | set(Centre.objects.exclude(cluster='').exclude(cluster=None).values_list('cluster', flat=True))
        | set(SAHIDemand.objects.exclude(cluster='').values_list('cluster', flat=True))
    )

    sc_qs_master = ClusterMaster.objects.exclude(sub_cluster='')
    sc_qs_centre = Centre.objects.exclude(sub_cluster='').exclude(sub_cluster=None)
    sc_qs_demand = SAHIDemand.objects.exclude(sub_cluster='')
    if cluster:
        sc_qs_master = sc_qs_master.filter(cluster=cluster)
        sc_qs_centre = sc_qs_centre.filter(cluster=cluster)
        sc_qs_demand = sc_qs_demand.filter(cluster=cluster)
    sub_clusters = sorted(
        set(sc_qs_master.values_list('sub_cluster', flat=True))
        | set(sc_qs_centre.values_list('sub_cluster', flat=True))
        | set(sc_qs_demand.values_list('sub_cluster', flat=True))
    )

    return JsonResponse({
        'clusters':     clusters,
        'sub_clusters': sub_clusters,
    })


def sahi_demand_table_api(request):
    """
    Table 1 — Existing Client wise rows: Designation, HC, Monthly Demand.
    Filters: cluster, sub_cluster (direct match on SAHIDemand columns).
    """
    cluster     = request.GET.get('cluster', '')
    sub_cluster = request.GET.get('sub_cluster', '')

    qs = SAHIDemand.objects.all()
    if cluster:     qs = qs.filter(cluster=cluster)
    if sub_cluster: qs = qs.filter(sub_cluster=sub_cluster)

    rows = list(qs.values(
        'region', 'existing_potential', 'demand_city', 'cluster', 'sub_cluster',
        'location', 'existing_client', 'client_nature',
        'designation', 'hc', 'monthly_demand'
    ).order_by('existing_client', 'designation'))

    totals = {
        'rows':           len(rows),
        'clients':        len(set(r['existing_client'] for r in rows if r['existing_client'])),
        'total_hc':       sum((r['hc'] or 0) for r in rows),
        'monthly_demand': sum((r['monthly_demand'] or 0) for r in rows),
    }
    return JsonResponse({'rows': rows, 'totals': totals})


def sahi_centre_table_api(request):
    """
    Table 2 — Nearby Centres for the selected Cluster / Sub Cluster.

    Flow: cluster (+ optional sub_cluster) → Centre rows matching same Cluster/Sub Cluster
          → BatchPlan join: QP, Final Enrolment / Certification / Placement Planned

    One row per (Centre × QP).
    """
    cluster     = request.GET.get('cluster', '')
    sub_cluster = request.GET.get('sub_cluster', '')

    if not cluster and not sub_cluster:
        return JsonResponse({
            'rows': [], 'totals': {'centres': 0, 'qps': 0,
                                   'enrol': 0, 'cert': 0, 'place': 0},
            'mapped': False, 'message': 'Select a Cluster (or Sub Cluster) to view centres.',
        })

    centre_qs = Centre.objects.all()
    if cluster:     centre_qs = centre_qs.filter(cluster=cluster)
    if sub_cluster: centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
    centres = list(centre_qs.values('centre_id', 'centre_name').order_by('centre_name'))

    if not centres:
        scope = f'Sub Cluster "{sub_cluster}"' if sub_cluster else f'Cluster "{cluster}"'
        return JsonResponse({
            'rows': [],
            'totals': {'centres': 0, 'qps': 0, 'enrol': 0, 'cert': 0, 'place': 0},
            'mapped': True,
            'message': f'No centres found for {scope}.',
        })

    centre_ids   = [c['centre_id']   for c in centres]
    name_by_id   = {c['centre_id']: c['centre_name'] for c in centres}

    # Aggregate by (centre_id, qp) — sum planned figures across all batches
    from django.db.models import Sum
    agg_qs = (
        BatchPlan.objects.filter(centre_id__in=centre_ids)
        .values('centre_id', 'qp')
        .annotate(
            enrol=Sum('final_enrolment_planned'),
            cert =Sum('final_certification_planned'),
            place=Sum('final_placement_planned'),
        )
        .order_by('centre_id', 'qp')
    )

    rows = []
    centres_with_batches = set()
    for r in agg_qs:
        centres_with_batches.add(r['centre_id'])
        rows.append({
            'centre_id':   r['centre_id'],
            'centre_name': name_by_id.get(r['centre_id'], ''),
            'qp':          r['qp'],
            'enrol':       r['enrol'] or 0,
            'cert':        r['cert']  or 0,
            'place':       r['place'] or 0,
        })

    # Centres with no batches → still surface them with blanks
    for c in centres:
        if c['centre_id'] not in centres_with_batches:
            rows.append({
                'centre_id': c['centre_id'], 'centre_name': c['centre_name'],
                'qp': '', 'enrol': 0, 'cert': 0, 'place': 0,
            })

    # Re-sort: by centre_name, then qp
    rows.sort(key=lambda r: (r['centre_name'] or '', r['qp'] or ''))

    totals = {
        'centres': len(set(r['centre_id'] for r in rows)),
        'qps':     len(set(r['qp'] for r in rows if r['qp'])),
        'enrol':   sum(r['enrol'] for r in rows),
        'cert':    sum(r['cert']  for r in rows),
        'place':   sum(r['place'] for r in rows),
    }
    return JsonResponse({
        'rows': rows, 'totals': totals,
        'mapped': True,
        'scope': sub_cluster or cluster,
    })


def sahi_diploma_table_api(request):
    """
    Table 3 — Diploma Colleges & Institutes & Training Centres for the
    centres in the selected Cluster / Sub Cluster. Source: CommunityCollege.

    Categories: 'Diploma Colleges' / 'Diploma College' (singular variant)
                / 'Institutes & Training Centres'
    """
    cluster     = request.GET.get('cluster', '')
    sub_cluster = request.GET.get('sub_cluster', '')

    if not cluster and not sub_cluster:
        return JsonResponse({
            'rows': [], 'totals': {'rows': 0, 'centres': 0},
            'mapped': False,
            'message': 'Select a Cluster (or Sub Cluster) to view nearby diploma colleges.',
        })

    centre_qs = Centre.objects.all()
    if cluster:     centre_qs = centre_qs.filter(cluster=cluster)
    if sub_cluster: centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
    centre_ids = list(centre_qs.values_list('centre_id', flat=True))

    if not centre_ids:
        scope = f'Sub Cluster "{sub_cluster}"' if sub_cluster else f'Cluster "{cluster}"'
        return JsonResponse({
            'rows': [], 'totals': {'rows': 0, 'centres': 0},
            'mapped': False,
            'message': f'No centres found for {scope}.',
        })

    CATEGORIES = ['Diploma Colleges', 'Diploma College', 'Institutes & Training Centres']
    qs = (CommunityCollege.objects
          .filter(centre__centre_id__in=centre_ids, category__in=CATEGORIES)
          .order_by('category', 'centre__centre_name', 'name_place'))

    rows = []
    for cc in qs:
        rows.append({
            'category':    cc.category,
            'name_place':  cc.name_place,
            'address':     cc.address,
            'phone_hours': cc.phone_hours,
            'centre_name': cc.centre.centre_name if cc.centre else '',
        })

    totals = {
        'rows':    len(rows),
        'centres': len(set(r['centre_name'] for r in rows if r['centre_name'])),
        'diploma': sum(1 for r in rows if 'diploma' in r['category'].lower()),
        'institutes': sum(1 for r in rows if 'institute' in r['category'].lower()),
    }
    return JsonResponse({
        'rows': rows, 'totals': totals,
        'mapped': True,
        'scope': sub_cluster or cluster,
    })


# ── API: cascade filter options ───────────────────────────────────────────────

def filter_options_api(request):
    bu_head     = request.GET.get('bu_head', '')
    tm_name     = request.GET.get('tm_name', '')
    project     = request.GET.get('project', '')
    centre_id   = request.GET.get('centre_id', '')
    cluster     = request.GET.get('cluster', '')
    sub_cluster = request.GET.get('sub_cluster', '')

    # Top-level scope first (cluster / sub_cluster)
    base_qs = Centre.objects.all()
    if cluster:
        base_qs = base_qs.filter(cluster=cluster)
    if sub_cluster:
        base_qs = base_qs.filter(sub_cluster=sub_cluster)

    centre_qs = base_qs
    if bu_head:
        centre_qs = centre_qs.filter(bu_head=bu_head)
    if tm_name:
        centre_qs = centre_qs.filter(tm_name=tm_name)
    centre_ids = list(centre_qs.values_list('centre_id', flat=True))

    tm_qs = base_qs
    if bu_head:
        tm_qs = tm_qs.filter(bu_head=bu_head)
    tm_names = sorted(set(tm_qs.exclude(tm_name='').exclude(tm_name=None).values_list('tm_name', flat=True)))

    bp_qs = BatchPlan.objects.filter(centre_id__in=centre_ids)
    projects = sorted(set(bp_qs.exclude(project_name='').values_list('project_name', flat=True)))

    # Centre dropdown narrows when a project is selected
    centres_qs = centre_qs
    if project:
        project_centre_ids = set(
            BatchPlan.objects.filter(project_name=project)
            .values_list('centre_id', flat=True).distinct()
        )
        centres_qs = centres_qs.filter(centre_id__in=project_centre_ids)
    centres = list(centres_qs.values('centre_id', 'centre_name').order_by('centre_name'))

    qp_qs = bp_qs
    if project:
        qp_qs = qp_qs.filter(project_name=project)
    if centre_id:
        qp_qs = qp_qs.filter(centre_id=centre_id)
    qps = sorted(set(qp_qs.exclude(qp='').values_list('qp', flat=True)))

    return JsonResponse({'tm_names': tm_names, 'projects': projects, 'centres': centres, 'qps': qps})


# ── API: community colleges ───────────────────────────────────────────────────

def community_colleges_api(request):
    centre_id = request.GET.get('centre_id', '')
    category  = request.GET.get('category', '')
    source    = request.GET.get('source', '')
    qs = CommunityCollege.objects.all()
    if centre_id:
        qs = qs.filter(centre__centre_id=centre_id)
    if category:
        qs = qs.filter(category__iexact=category)
    if source:
        qs = qs.filter(source__iexact=source)
    data = list(qs.values(
        'sno', 'source', 'category', 'name_place', 'address',
        'phone_hours', 'centre_name', 'distance_km', 'rating'
    ).order_by('distance_km'))
    return JsonResponse({'results': data, 'count': len(data)})


def community_college_categories_api(request):
    """Return distinct categories AND sources for the given centre (or all centres).
    Both lists narrow when a centre is selected (and source narrows category, etc.)."""
    centre_id = request.GET.get('centre_id', '')
    source    = request.GET.get('source', '')
    qs = CommunityCollege.objects.all()
    if centre_id:
        qs = qs.filter(centre__centre_id=centre_id)
    # Categories narrow by the selected source (if any). Sources do NOT narrow
    # by category — they're a higher-level grouping that should always show the
    # full list available for the current centre.
    cat_qs = qs.filter(source__iexact=source) if source else qs
    categories = sorted(set(cat_qs.exclude(category='').values_list('category', flat=True)))
    sources    = sorted(set(qs.exclude(source='').values_list('source', flat=True)))
    return JsonResponse({'categories': categories, 'sources': sources})


# ── API: Cert Schedule (SMB) ──────────────────────────────────────────────────

def smb_cert_filter_options_api(request):
    """Cascading filter options for SMB.

    Pyramid: BU Head → TM Name → Project → Centre → QP.
    Each filter narrows the next.
    Also respects Home filters: cluster / sub_cluster.

    Projects + QPs come from the UNION of NAPSData and NAPSPlan (the same
    sources that power the visible tables) — NOT from CertSchedule. This
    avoids the bug where the same project is spelt slightly differently
    across data files (e.g. CertSchedule has 'SCB_1440Nos…' while
    NAPSData has 'SCB_1440Nos…(Non FCR)') and the picked dropdown value
    fails to match any row.
    """
    from dashboard.models import NAPSData, NAPSPlan

    bu_head      = request.GET.get('bu_head', '')
    tm_name      = request.GET.get('tm_name', '')
    project      = request.GET.get('project', '')
    centre_id    = request.GET.get('centre_id', '')
    # Home cross-filters
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')

    # ── Resolve centre universe based on Home + BU Head + TM Name ──
    centre_qs = Centre.objects.all()
    if cluster:     centre_qs = centre_qs.filter(cluster=cluster)
    if sub_cluster: centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
    home_scope_active = bool(cluster or sub_cluster)
    if bu_head:     centre_qs = centre_qs.filter(bu_head=bu_head)
    if tm_name:     centre_qs = centre_qs.filter(tm_name=tm_name)
    scoped_centre_ids = list(centre_qs.values_list('centre_id', flat=True))

    # NAPS Data + Plan rows scoped by centre membership (use ALL when no scope set)
    if home_scope_active or bu_head or tm_name:
        nd_qs = NAPSData.objects.filter(centre_id__in=scoped_centre_ids)
        np_qs = NAPSPlan.objects.filter(centre_id__in=scoped_centre_ids)
    else:
        nd_qs = NAPSData.objects.all()
        np_qs = NAPSPlan.objects.all()

    # Project = union of distinct project names across both NAPS sources
    nd_projects = set(nd_qs.exclude(project_name='').values_list('project_name', flat=True))
    np_projects = set(np_qs.exclude(project_name='').values_list('project_name', flat=True))
    projects = sorted(nd_projects | np_projects)

    # Narrow by project for subsequent filters
    if project:
        nd_qs = nd_qs.filter(project_name=project)
        np_qs = np_qs.filter(project_name=project)

    # Centre dropdown — narrows by project. Union of centres present in either NAPS source.
    nd_centre_ids = set(nd_qs.values_list('centre_id', flat=True))
    np_centre_ids = set(np_qs.values_list('centre_id', flat=True))
    naps_centre_ids = nd_centre_ids | np_centre_ids
    if naps_centre_ids:
        centres_qs = centre_qs.filter(centre_id__in=naps_centre_ids)
    else:
        centres_qs = Centre.objects.none()
    centres = list(centres_qs.values('centre_id', 'centre_name').order_by('centre_name'))

    # Narrow by centre for QP filter
    if centre_id:
        nd_qs = nd_qs.filter(centre_id=centre_id)
        np_qs = np_qs.filter(centre_id=centre_id)

    # QP = union from both NAPS sources
    nd_qps = set(nd_qs.exclude(qp_name='').values_list('qp_name', flat=True))
    np_qps = set(np_qs.exclude(qp_name='').values_list('qp_name', flat=True))
    qps = sorted(nd_qps | np_qps)

    # TM Names depend on bu_head + Home scope
    tm_qs = Centre.objects.all()
    if cluster:     tm_qs = tm_qs.filter(cluster=cluster)
    if sub_cluster: tm_qs = tm_qs.filter(sub_cluster=sub_cluster)
    if bu_head:     tm_qs = tm_qs.filter(bu_head=bu_head)
    tm_names = sorted(set(tm_qs.exclude(tm_name='').exclude(tm_name=None).values_list('tm_name', flat=True)))

    # BU Heads narrowed by Home scope only (top of the cascade)
    bu_qs = Centre.objects.all()
    if cluster:     bu_qs = bu_qs.filter(cluster=cluster)
    if sub_cluster: bu_qs = bu_qs.filter(sub_cluster=sub_cluster)
    bu_heads = sorted(set(bu_qs.exclude(bu_head='').exclude(bu_head=None).values_list('bu_head', flat=True)))

    return JsonResponse({
        'bu_heads':     bu_heads,
        'tm_names':     tm_names,
        'projects':     projects,
        'cert_windows': [],          # kept for legacy JS compat; no longer surfaced
        'centres':      centres,
        'qps':          qps,
    })


def smb_cert_schedule_api(request):
    """Return the Cert Schedule table rows with month-bucketed cert targets.

    Each row: Centre Name | Course / Trade | NAPS | <month buckets...> | Total
    The month columns are derived from the distinct Cert Start Date months
    present in the filtered data, sorted chronologically.
    Honors Home filters (cluster / sub_cluster).
    """
    from dashboard.models import CertSchedule

    bu_head     = request.GET.get('bu_head', '')
    tm_name     = request.GET.get('tm_name', '')
    project     = request.GET.get('project', '')
    cert_window = request.GET.get('cert_window', '')
    centre_id   = request.GET.get('centre_id', '')
    qp          = request.GET.get('qp', '')
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')

    qs = CertSchedule.objects.all()

    if cluster or sub_cluster or bu_head or tm_name:
        c_qs = Centre.objects.all()
        if cluster:     c_qs = c_qs.filter(cluster=cluster)
        if sub_cluster: c_qs = c_qs.filter(sub_cluster=sub_cluster)
        if bu_head: c_qs = c_qs.filter(bu_head=bu_head)
        if tm_name: c_qs = c_qs.filter(tm_name=tm_name)
        qs = qs.filter(centre_id__in=list(c_qs.values_list('centre_id', flat=True)))

    if project:     qs = qs.filter(project=project)
    if cert_window: qs = qs.filter(cert_window=cert_window)
    if centre_id:   qs = qs.filter(centre__centre_id=centre_id)
    if qp:          qs = qs.filter(course_trade=qp)

    # Collect month buckets (sorted chronologically)
    months_set = set()
    for r in qs:
        if r.cert_start_date:
            months_set.add((r.cert_start_date.year, r.cert_start_date.month))
    months = sorted(months_set)
    month_labels = [f"{MONTH_LABELS.get(m, m)} {y % 100:02d}" for (y, m) in months]
    month_key = {m: i for i, m in enumerate(months)}

    # Aggregate per (centre × course × NAPS)
    from collections import defaultdict
    grouped = defaultdict(lambda: {'monthly': [0] * len(months), 'total': 0})
    for r in qs:
        key = (r.centre_name or '', r.course_trade or '', r.naps or '')
        grouped[key]['total'] += r.cert_target
        if r.cert_start_date:
            idx = month_key[(r.cert_start_date.year, r.cert_start_date.month)]
            grouped[key]['monthly'][idx] += r.cert_target

    rows = []
    for (cname, course, naps), data in sorted(grouped.items()):
        rows.append({
            'centre_name': cname,
            'course':      course,
            'naps':        naps,
            'monthly':     data['monthly'],
            'total':       data['total'],
        })

    totals_by_month = [0] * len(months)
    for row in rows:
        for i, v in enumerate(row['monthly']):
            totals_by_month[i] += v
    grand_total = sum(totals_by_month)

    return JsonResponse({
        'months':          month_labels,
        'rows':            rows,
        'totals_by_month': totals_by_month,
        'grand_total':     grand_total,
        'row_count':       len(rows),
    })


# ── Helper: resolve SMB filter scope to centre_id list + qp filter ─────────────

def _smb_resolve_scope(request):
    """
    Read the standard SMB filter set from a request and return:
      (centre_ids: list[str] | None, qp: str, project: str)

    centre_ids is None when no scoping centre filter is applied (= all
    centres). BU Head / TM Name / Cluster / Sub Cluster / Centre are
    resolved against Centre to yield a centre_id list.

    `project` is returned as a separate filter to be applied at the
    table level against each model's own `project_name` field (since
    NAPSData and NAPSPlan have their own project_name columns that
    don't always match BatchPlan's spelling).

    `qp` is also a table-level filter (against qp_name).
    """
    bu_head     = request.GET.get('bu_head', '')
    tm_name     = request.GET.get('tm_name', '')
    project     = request.GET.get('project', '')
    centre_id   = request.GET.get('centre_id', '')
    qp          = request.GET.get('qp', '')
    cluster     = request.GET.get('cluster', '')
    sub_cluster = request.GET.get('sub_cluster', '')

    # Build centre universe (used to translate BU/TM/cluster filters into centre_ids)
    centre_qs = Centre.objects.all()
    if cluster:     centre_qs = centre_qs.filter(cluster=cluster)
    if sub_cluster: centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
    if bu_head:     centre_qs = centre_qs.filter(bu_head=bu_head)
    if tm_name:     centre_qs = centre_qs.filter(tm_name=tm_name)
    if centre_id:   centre_qs = centre_qs.filter(centre_id=centre_id)

    centre_scope_active = bool(cluster or sub_cluster or bu_head or tm_name or centre_id)
    if not centre_scope_active:
        return None, qp, project

    return list(centre_qs.values_list('centre_id', flat=True)), qp, project


def _project_centre_ids(project):
    """Return the set of centre_ids that run the given project.
    Looks across BatchPlan, NAPSData, NAPSPlan so the answer is robust
    even when a project name appears in only one of those tables.
    """
    if not project:
        return None
    from dashboard.models import NAPSData, NAPSPlan
    cids = set(BatchPlan.objects.filter(project_name=project)
               .values_list('centre_id', flat=True).distinct())
    cids |= set(NAPSData.objects.filter(project_name=project)
                .exclude(centre_id='').values_list('centre_id', flat=True).distinct())
    cids |= set(NAPSPlan.objects.filter(project_name=project)
                .exclude(centre_id='').values_list('centre_id', flat=True).distinct())
    return cids



# ── API: Certification Pipeline (aggregated from NAPSData) ────────────────────

def certification_pipeline_api(request):
    """
    Aggregates NAPSData (per-candidate) into one row per Batch ID.
    Only NAPS-eligible candidates are counted.
    Supports a table-level Slab filter (table header dropdown).
    """
    from dashboard.models import NAPSData
    from django.db.models import Count, Sum, Min

    centre_ids, qp, project = _smb_resolve_scope(request)
    slab = request.GET.get('slab', '')

    qs = NAPSData.objects.filter(naps_eligible__iexact='Yes')
    if centre_ids is not None:
        qs = qs.filter(centre_id__in=centre_ids)
    if project:
        qs = qs.filter(project_name=project)
    if qp:
        qs = qs.filter(qp_name=qp)

    # Snapshot the slab universe BEFORE applying the slab filter, so the
    # dropdown stays populated even when a slab is selected.
    available_slabs = sorted(set(
        qs.exclude(slab='').values_list('slab', flat=True)
    ))

    if slab:
        qs = qs.filter(slab=slab)

    # Aggregate per Batch ID (slab + qp + project assumed consistent within a batch)
    grouped = (
        qs.values('batch_id', 'centre_name', 'centre_id', 'project_name', 'slab', 'qp_name')
          .annotate(
              candidate_count   = Count('id'),
              estimated_revenue = Sum('estimated_revenue'),
              batch_actual_start_date = Min('batch_actual_start_date'),
              batch_actual_end_date   = Min('batch_actual_end_date'),
          )
          .order_by('centre_name', 'batch_id')
    )

    rows = []
    total_candidates = 0
    total_revenue = 0
    for g in grouped:
        rows.append({
            'centre_name':             g['centre_name'],
            'centre_id':               g['centre_id'],
            'project_name':            g['project_name'],
            'batch_id':                g['batch_id'],
            'batch_actual_start_date': g['batch_actual_start_date'].strftime('%d-%b-%Y') if g['batch_actual_start_date'] else '',
            'batch_actual_end_date':   g['batch_actual_end_date'].strftime('%d-%b-%Y') if g['batch_actual_end_date'] else '',
            'slab':                    g['slab'],
            'qp_name':                 g['qp_name'],
            'candidate_count':         g['candidate_count'],
            'estimated_revenue':       g['estimated_revenue'] or 0,
        })
        total_candidates += g['candidate_count']
        total_revenue    += (g['estimated_revenue'] or 0)

    return JsonResponse({
        'rows':             rows,
        'row_count':        len(rows),
        'total_candidates': total_candidates,
        'total_revenue':    total_revenue,
        'available_slabs':  available_slabs,
    })


# ── API: NAPS Plan FY26-27 (month-wise) ───────────────────────────────────────

def naps_plan_api(request):
    """
    NAPS Certification Plan — one row per (Centre, QP), with Final
    Certification Planned counts bucketed into Apr-Mar by Certification
    Start Date month. Total Est. Revenue is summed across all batches for
    that (Centre + QP) combination.
    """
    from dashboard.models import NAPSPlan
    from collections import defaultdict

    centre_ids, qp, project = _smb_resolve_scope(request)

    qs = NAPSPlan.objects.all()
    if centre_ids is not None:
        qs = qs.filter(centre_id__in=centre_ids)
    if project:
        qs = qs.filter(project_name=project)
    if qp:
        qs = qs.filter(qp_name=qp)

    # FY months: Apr=index 0 ... Mar=index 11
    month_to_idx = {4:0, 5:1, 6:2, 7:3, 8:4, 9:5, 10:6, 11:7, 12:8, 1:9, 2:10, 3:11}

    # Group key = (centre_name, qp_name, naps_eligible)
    groups = defaultdict(lambda: {
        'months': [0]*12,
        'estimated_revenue': 0,
        'centre_id': '',
    })

    for r in qs.values(
        'centre_name', 'centre_id', 'qp_name', 'naps_eligible',
        'certification_start_date', 'final_certification_planned', 'estimated_revenue'
    ):
        key = (r['centre_name'], r['qp_name'], r['naps_eligible'])
        bucket = groups[key]
        bucket['centre_id'] = r['centre_id']
        bucket['estimated_revenue'] += (r['estimated_revenue'] or 0)
        d = r['certification_start_date']
        if d:
            idx = month_to_idx.get(d.month)
            if idx is not None:
                bucket['months'][idx] += (r['final_certification_planned'] or 0)

    rows = []
    totals_by_month = [0]*12
    total_revenue = 0
    fy_total = 0
    for (centre_name, qp_name, naps_eligible), bucket in sorted(groups.items(), key=lambda x: (x[0][0], x[0][1])):
        row_total = sum(bucket['months'])
        rows.append({
            'centre_name':       centre_name,
            'centre_id':         bucket['centre_id'],
            'qp_name':           qp_name,
            'naps_eligible':     naps_eligible,
            'months':            bucket['months'],
            'row_total':         row_total,
            'estimated_revenue': bucket['estimated_revenue'],
        })
        for i, v in enumerate(bucket['months']):
            totals_by_month[i] += v
        total_revenue += bucket['estimated_revenue']
        fy_total += row_total

    return JsonResponse({
        'rows':            rows,
        'row_count':       len(rows),
        'totals_by_month': totals_by_month,
        'fy_total':        fy_total,
        'total_revenue':   total_revenue,
    })


# ── API: Outreach KPI counts (header strip cards) ────────────────────────────

def outreach_kpi_api(request):
    """
    Returns count cards for the SMB outreach pipeline:
      Lead Generated, Contacted, Interested, Declined, Pending,
      Employer (distinct), Number of Open Positions.

    Respects the SMB filter bar (cluster, sub_cluster, bu_head, tm_name,
    project, centre_id, qp). Project + QP are applied via OutreachStatus's
    join to HyperlocalJob — an employer is "in scope" for a project / QP
    if at least one HJ record links it.
    """
    from dashboard.models import OutreachStatus
    from django.db.models import Sum, Count

    centre_ids, qp, project = _smb_resolve_scope(request)

    qs = OutreachStatus.objects.all()
    if centre_ids is not None:
        qs = qs.filter(centre_id__in=centre_ids)
    # If a Project is selected, narrow further to centres that actually
    # run that project. (OutreachStatus has no project_name column itself,
    # so we resolve project → centre_ids via BatchPlan/NAPSData/NAPSPlan.)
    if project:
        proj_cids = _project_centre_ids(project) or set()
        qs = qs.filter(centre_id__in=proj_cids)

    # If a Project or QP is selected, restrict to employers (IDs) that appear
    # in HJ scoped to those centres + qp. We use HJ for the project lookup
    # because OutreachStatus doesn't carry project. The project filter
    # itself is only applied via centre narrowing (project → centres via
    # NAPSData/NAPSPlan/HJ); we keep the QP filter explicit.
    if qp:
        emp_ids = set(
            HyperlocalJob.objects
            .filter(course=qp)
            .exclude(discovered_employer_id='')
            .values_list('discovered_employer_id', flat=True)
        )
        qs = qs.filter(discovered_employer_id__in=emp_ids)

    # Status counts
    status_counts = {row['status']: row['c'] for row in
                     qs.values('status').annotate(c=Count('id'))}
    employer_count = qs.values('discovered_employer_id').distinct().count()
    open_positions_total = qs.aggregate(s=Sum('number_of_open_positions'))['s'] or 0
    shortlisted_total    = qs.aggregate(s=Sum('shortlisted'))['s'] or 0

    return JsonResponse({
        'lead_generated':  status_counts.get('Lead Generated', 0),
        'contacted':       status_counts.get('Contacted', 0),
        'interested':      status_counts.get('Interested', 0),
        'declined':        status_counts.get('Declined', 0),
        'pending':         status_counts.get('Pending', 0),
        'employer':        employer_count,
        'open_positions':  open_positions_total,
        'shortlisted':     shortlisted_total,
    })


# ── API: Outreach Status table ────────────────────────────────────────────────

def outreach_status_table_api(request):
    """
    Returns one row per outreach record:
      Discovered Employer | Status | Number of Open Positions | Shortlisted

    Respects the SMB main filter bar (BU/TM/Project/Centre/QP) PLUS local
    Centre and Status filters at the table header.
    Default sort: by Status using natural pipeline order
    (Lead Generated → Contacted → Interested → Declined → Pending).
    """
    from dashboard.models import OutreachStatus

    centre_ids, qp, project = _smb_resolve_scope(request)

    # Local (table-header) filters
    local_centre  = request.GET.get('local_centre_id', '')
    local_status  = request.GET.get('local_status', '')

    qs = OutreachStatus.objects.all()
    if centre_ids is not None:
        qs = qs.filter(centre_id__in=centre_ids)
    # Narrow to centres running the selected Project (via BatchPlan/NAPSData/NAPSPlan)
    if project:
        proj_cids = _project_centre_ids(project) or set()
        qs = qs.filter(centre_id__in=proj_cids)
    if local_centre:
        qs = qs.filter(centre_id=local_centre)
    if local_status:
        qs = qs.filter(status=local_status)
    if qp:
        emp_ids = set(
            HyperlocalJob.objects
            .filter(course=qp)
            .exclude(discovered_employer_id='')
            .values_list('discovered_employer_id', flat=True)
        )
        qs = qs.filter(discovered_employer_id__in=emp_ids)

    # Natural pipeline order for status sort
    status_order = {
        'Lead Generated': 1, 'Contacted': 2, 'Interested': 3,
        'Declined': 4, 'Pending': 5
    }

    rows = list(qs.values(
        'discovered_employer', 'discovered_employer_id', 'status',
        'number_of_open_positions', 'shortlisted', 'centre_name', 'centre_id'
    ))
    rows.sort(key=lambda r: (status_order.get(r['status'], 99), r['discovered_employer']))

    # Footer totals
    total_open_positions = sum((r['number_of_open_positions'] or 0) for r in rows)
    total_shortlisted    = sum((r['shortlisted'] or 0) for r in rows)

    # Provide the distinct centres + statuses present in this scope, for
    # populating the table-header dropdowns. We use the broader (centre/QP
    # scoped, but ignoring local_centre/local_status) queryset so dropdowns
    # don't collapse when a filter is already picked.
    scope_qs = OutreachStatus.objects.all()
    if centre_ids is not None:
        scope_qs = scope_qs.filter(centre_id__in=centre_ids)
    if project:
        proj_cids = _project_centre_ids(project) or set()
        scope_qs = scope_qs.filter(centre_id__in=proj_cids)
    if qp:
        scope_qs = scope_qs.filter(discovered_employer_id__in=emp_ids)
    centres_in_scope = sorted(
        {(r['centre_id'], r['centre_name']) for r in
         scope_qs.values('centre_id', 'centre_name')
         if r['centre_id']},
        key=lambda x: x[1]
    )
    statuses_in_scope = sorted(
        set(scope_qs.exclude(status='').values_list('status', flat=True)),
        key=lambda s: status_order.get(s, 99)
    )

    return JsonResponse({
        'rows':                  rows,
        'row_count':             len(rows),
        'total_open_positions':  total_open_positions,
        'total_shortlisted':     total_shortlisted,
        'available_centres':     [{'centre_id': c[0], 'centre_name': c[1]} for c in centres_in_scope],
        'available_statuses':    statuses_in_scope,
    })


# ── API: hyperlocal jobs ──────────────────────────────────────────────────────

def hyperlocal_jobs_api(request):
    """
    Returns Hyperlocal Jobs (discovered employers).

    Accepts both the legacy single-centre filter (centre_id + qp) and the
    new SMB main-filter set (bu_head / tm_name / project / cluster /
    sub_cluster). The legacy centre_id overrides the main-filter scope.
    """
    centre_ids, qp_scope, project = _smb_resolve_scope(request)
    local_centre = request.GET.get('centre_id', '')
    local_qp     = request.GET.get('qp', '')

    qs = HyperlocalJob.objects.all()

    # If a local centre is explicitly set, use just that. Otherwise use the
    # main-filter scope (BU/TM/Cluster/Sub Cluster narrows centre_ids).
    if local_centre:
        qs = qs.filter(centre__centre_id=local_centre)
    elif centre_ids is not None:
        qs = qs.filter(centre__centre_id__in=centre_ids)

    # Project narrowing: HJ has no project_name column, so resolve to centres
    if project:
        proj_cids = _project_centre_ids(project) or set()
        qs = qs.filter(centre__centre_id__in=proj_cids)

    # QP filter — local takes precedence
    qp = local_qp or qp_scope
    if qp:
        qs = qs.filter(course__icontains=qp)

    data = list(qs.values(
        'course', 'sector', 'discovered_employer', 'discovered_employer_id',
        'phone', 'employer_address', 'suitable_roles', 'centre_name',
        'distance_km', 'rating', 'naps_eligible', 'outreach_status'
    ).order_by('distance_km', 'discovered_employer'))
    return JsonResponse({'results': data, 'count': len(data)})


# ── API: Staffing — Demand (Table 1) ─────────────────────────────────────────

def staffing_demand_api(request):
    region = request.GET.get('region', '')
    city = request.GET.get('city', '')
    cluster = request.GET.get('cluster', '')
    client = request.GET.get('client', '')

    qs = DemandSupply.objects.all()
    if region:
        qs = qs.filter(region__iexact=region)
    if city:
        qs = qs.filter(city_location__iexact=city)
    if cluster:
        qs = qs.filter(industrial_estate_cluster__iexact=cluster)
    if client:
        qs = qs.filter(existing_client__iexact=client)

    data = list(qs.values(
        'id', 'region', 'city_location', 'industrial_estate_cluster',
        'existing_client', 'std_designation', 'estimated_monthly_demand',
        'new_existing'
    ).order_by('region', 'city_location', 'existing_client'))
    return JsonResponse({'results': data, 'count': len(data)})


# ── API: Staffing — Supply / Centre (Table 2) ─────────────────────────────────

def staffing_supply_api(request):
    region = request.GET.get('region', '')
    city = request.GET.get('city', '')
    cluster = request.GET.get('cluster', '')
    client = request.GET.get('client', '')

    qs = DemandSupply.objects.all()
    if region:
        qs = qs.filter(region__iexact=region)
    if city:
        qs = qs.filter(city_location__iexact=city)
    if cluster:
        qs = qs.filter(industrial_estate_cluster__iexact=cluster)
    if client:
        qs = qs.filter(existing_client__iexact=client)

    data = list(qs.values(
        'id', 'nearest_center', 'centre_id_ref', 'center_address',
        'training_program_match', 'estimated_monthly_supply',
        'training_program_naps_nats'
    ).order_by('nearest_center'))
    return JsonResponse({'results': data, 'count': len(data)})


# ── API: Staffing — ITI & Diploma Master (Table 3) ───────────────────────────

def staffing_iti_api(request):
    region = request.GET.get('region', '')
    city = request.GET.get('city', '')
    cluster = request.GET.get('cluster', '')
    client = request.GET.get('client', '')
    college_type = request.GET.get('type', '')

    qs = ITIDiplomaMaster.objects.all()

    # Cross-reference via centre if region/city/cluster/client filter is active
    if region or city or cluster or client:
        demand_qs = DemandSupply.objects.all()
        if region:
            demand_qs = demand_qs.filter(region__iexact=region)
        if city:
            demand_qs = demand_qs.filter(city_location__iexact=city)
        if cluster:
            demand_qs = demand_qs.filter(industrial_estate_cluster__iexact=cluster)
        if client:
            demand_qs = demand_qs.filter(existing_client__iexact=client)
        centre_ids = list(demand_qs.values_list('centre_id_ref', flat=True).distinct())
        qs = qs.filter(centre_id_ref__in=centre_ids)

    if college_type:
        qs = qs.filter(college_type__iexact=college_type)

    data = list(qs.values(
        'id', 'college_name', 'college_type', 'address',
        'rating', 'phone_number', 'working_hours', 'centre_name'
    ).order_by('college_type', 'college_name'))
    return JsonResponse({'results': data, 'count': len(data)})


# ── API: Staffing — SF Intervention Colleges (Table 4) ───────────────────────

def staffing_sf_colleges_api(request):
    region = request.GET.get('region', '')
    city = request.GET.get('city', '')
    cluster = request.GET.get('cluster', '')
    client = request.GET.get('client', '')

    qs = SFInterventionCollege.objects.all()

    if region or city or cluster or client:
        demand_qs = DemandSupply.objects.all()
        if region:
            demand_qs = demand_qs.filter(region__iexact=region)
        if city:
            demand_qs = demand_qs.filter(city_location__iexact=city)
        if cluster:
            demand_qs = demand_qs.filter(industrial_estate_cluster__iexact=cluster)
        if client:
            demand_qs = demand_qs.filter(existing_client__iexact=client)
        centre_ids = list(demand_qs.values_list('centre_id_ref', flat=True).distinct())
        qs = qs.filter(centre_id_ref__in=centre_ids)

    data = list(qs.values(
        'id', 'name_of_college', 'address', 'project_name', 'qp', 'centre_name'
    ).order_by('name_of_college'))
    return JsonResponse({'results': data, 'count': len(data)})


# ── API: Staffing — filter options (cascading dropdowns) ─────────────────────

def staffing_filter_options_api(request):
    regions = sorted(set(
        DemandSupply.objects.exclude(region='').values_list('region', flat=True)
    ))
    region = request.GET.get('region', '')
    city   = request.GET.get('city', '')

    qs = DemandSupply.objects.all()
    if region:
        qs = qs.filter(region__iexact=region)

    cities = sorted(set(qs.exclude(city_location='').values_list('city_location', flat=True)))

    # cluster & client narrow further by city if selected
    qs2 = qs
    if city:
        qs2 = qs2.filter(city_location__iexact=city)

    clusters = sorted(set(qs2.exclude(industrial_estate_cluster='').values_list('industrial_estate_cluster', flat=True)))
    clients  = sorted(set(qs2.exclude(existing_client='').values_list('existing_client', flat=True)))

    return JsonResponse({
        'regions':  regions,
        'cities':   cities,
        'clusters': clusters,
        'clients':  clients,
    })


# ── index view ────────────────────────────────────────────────────────────────


def build_batch_delay_rows(batches_qs):
    """Return a list of batch dicts with delay info. Actuals from BatchPlan FY columns."""
    today = date.today()
    rows = []

    for b in batches_qs.order_by('batch_planned_start_date'):
        ea = b.fy_e_act
        ca = b.fy_c_act
        pa = b.fy_p_act

        # Enrolment delay
        enrol_delayed, enrol_delay_days, enrol_delay_type = False, 0, ''
        if b.batch_planned_start_date:
            if b.batch_actual_start_date:
                d = (b.batch_actual_start_date - b.batch_planned_start_date).days
                if d > 0:
                    enrol_delayed, enrol_delay_days, enrol_delay_type = True, d, 'late_start'
            elif b.batch_planned_start_date < today:
                enrol_delayed = True
                enrol_delay_days = (today - b.batch_planned_start_date).days
                enrol_delay_type = 'overdue'

        # Certification delay
        cert_delayed, cert_delay_days, cert_delay_type = False, 0, ''
        if b.certification_planned_start_date:
            if b.assessment_actual_certification_date:
                d = (b.assessment_actual_certification_date - b.certification_planned_start_date).days
                if d > 0:
                    cert_delayed, cert_delay_days, cert_delay_type = True, d, 'late_cert'
            elif b.certification_planned_start_date < today:
                cert_delayed = True
                cert_delay_days = (today - b.certification_planned_start_date).days
                cert_delay_type = 'overdue'

        # Placement delay
        place_delayed, place_delay_days, place_delay_type = False, 0, ''
        if b.placement_planned_end_date:
            if b.placed_date:
                d = (b.placed_date - b.placement_planned_end_date).days
                if d > 0:
                    place_delayed, place_delay_days, place_delay_type = True, d, 'late_place'
            elif b.placement_planned_end_date < today:
                place_delayed = True
                place_delay_days = (today - b.placement_planned_end_date).days
                place_delay_type = 'overdue'

        rows.append({
            'batch_id': b.batch_id,
            'qp': b.qp,
            'project_name': b.project_name,
            'centre_id': b.centre_id,
            'enrol_planned_date': b.batch_planned_start_date,
            'cert_planned_date': b.certification_planned_start_date,
            'place_planned_date': b.placement_planned_end_date,
            'enrol_target': b.final_enrolment_planned,
            'enrol_actual': ea, 'enrol_pct': pct(ea, b.final_enrolment_planned),
            'cert_target': b.final_certification_planned,
            'cert_actual': ca, 'cert_pct': pct(ca, b.final_certification_planned),
            'place_target': b.final_placement_planned,
            'place_actual': pa, 'place_pct': pct(pa, b.final_placement_planned),
            'enrol_delayed': enrol_delayed, 'enrol_delay_days': enrol_delay_days, 'enrol_delay_type': enrol_delay_type,
            'cert_delayed':  cert_delayed,  'cert_delay_days':  cert_delay_days,  'cert_delay_type':  cert_delay_type,
            'place_delayed': place_delayed, 'place_delay_days': place_delay_days, 'place_delay_type': place_delay_type,
            'on_going': b.on_going,
        })
    return rows


def index(request):
    available_fys = get_available_fys()
    fy = request.GET.get('fy', available_fys[0] if available_fys else '2026-27')

    bu_head            = request.GET.get('bu_head', '')
    tm_name_filter     = request.GET.get('tm_name', '')
    project_name       = request.GET.get('project', '')
    centre_id_filter   = request.GET.get('centre', '')
    cluster_filter     = request.GET.get('cluster', '')
    sub_cluster_filter = request.GET.get('sub_cluster', '')

    # ── Base scope: always restrict to cluster / sub_cluster first ────────────
    scoped_centres_qs = Centre.objects.all()
    if cluster_filter:
        scoped_centres_qs = scoped_centres_qs.filter(cluster=cluster_filter)
    if sub_cluster_filter:
        scoped_centres_qs = scoped_centres_qs.filter(sub_cluster=sub_cluster_filter)

    # ── BU Head & TM dropdowns scoped to cluster ──────────────────────────────
    bu_heads = sorted(set(
        scoped_centres_qs.exclude(bu_head='').exclude(bu_head=None)
        .values_list('bu_head', flat=True)
    ))

    tm_qs = scoped_centres_qs
    if bu_head:
        tm_qs = tm_qs.filter(bu_head=bu_head)
    tm_names = sorted(set(
        tm_qs.exclude(tm_name='').exclude(tm_name=None).values_list('tm_name', flat=True)
    ))

    # ── Apply BU Head / TM name filter on top of cluster scope ───────────────
    all_centres_qs = scoped_centres_qs
    if bu_head:
        all_centres_qs = all_centres_qs.filter(bu_head=bu_head)
    if tm_name_filter:
        all_centres_qs = all_centres_qs.filter(tm_name=tm_name_filter)
    filtered_centre_ids = list(all_centres_qs.values_list('centre_id', flat=True))

    # ── Project / Centre / QP dropdowns scoped to filtered centres ────────────
    # Project dropdown also narrows by the selected Financial Year — a project
    # is shown only if it has at least one batch whose plan/start/cert/place
    # date falls within the FY window. Prevents stale projects (e.g. a
    # Feb-Mar 2026 batch) from appearing when FY 2026-27 is selected.
    bp_for_proj    = BatchPlan.objects.filter(centre_id__in=filtered_centre_ids)
    bp_for_proj_fy = filter_batchplan_by_fy(bp_for_proj, fy)
    projects = sorted(set(bp_for_proj_fy.exclude(project_name='').values_list('project_name', flat=True)))
    # If the user navigated with an explicit ?project=… that isn't in this FY
    # (e.g. switched FY but kept the URL), still show it in the dropdown so it
    # renders as the selected option — otherwise the user can't see what's
    # filtering their view.
    if project_name and project_name not in projects:
        projects = sorted(projects + [project_name])

    # When a Project is selected, narrow the Centre dropdown to centres that
    # actually run that project (matches the cascading API behaviour).
    centres_scope_qs = all_centres_qs
    if project_name:
        project_centre_ids = set(
            BatchPlan.objects.filter(project_name=project_name)
            .values_list('centre_id', flat=True).distinct()
        )
        centres_scope_qs = centres_scope_qs.filter(centre_id__in=project_centre_ids)
    centres = centres_scope_qs.order_by('centre_name')

    qp_qs = bp_for_proj
    if project_name:
        qp_qs = qp_qs.filter(project_name=project_name)
    if centre_id_filter:
        qp_qs = qp_qs.filter(centre_id=centre_id_filter)
    qps = sorted(set(qp_qs.exclude(qp='').values_list('qp', flat=True)))

    # Filter batches
    batches = BatchPlan.objects.filter(centre_id__in=filtered_centre_ids)
    if project_name:
        batches = batches.filter(project_name=project_name)
    if centre_id_filter:
        batches = batches.filter(centre_id=centre_id_filter)

    mom_months = build_mom_rows(batches, fy)

    total_row = {
        'enrol_target': sum(m['enrol_target'] for m in mom_months),
        'enrol_actual': sum(m['enrol_actual'] for m in mom_months),
        'cert_target': sum(m['cert_target'] for m in mom_months),
        'cert_actual': sum(m['cert_actual'] for m in mom_months),
        'place_target': sum(m['place_target'] for m in mom_months),
        'place_actual': sum(m['place_actual'] for m in mom_months),
    }

    centre_summary = []
    # When a project filter is set, only show centres that actually run that project.
    summary_centres_qs = all_centres_qs
    if project_name:
        project_centre_ids = set(
            batches.values_list('centre_id', flat=True).distinct()
        )
        summary_centres_qs = summary_centres_qs.filter(centre_id__in=project_centre_ids)
    for c in summary_centres_qs.order_by('centre_name'):
        cb = batches.filter(centre_id=c.centre_id)
        rows = build_mom_rows(cb, fy)
        et = sum(r['enrol_target'] for r in rows)
        ea = sum(r['enrol_actual'] for r in rows)
        ct = sum(r['cert_target'] for r in rows)
        ca = sum(r['cert_actual'] for r in rows)
        pt = sum(r['place_target'] for r in rows)
        pa = sum(r['place_actual'] for r in rows)
        centre_summary.append({
            'centre_id': c.centre_id,
            'centre_name': c.centre_name,
            'bu_head': c.bu_head or '',
            'tm_name': c.tm_name or '',
            'enrol_target': et, 'enrol_actual': ea, 'enrol_pct': pct(ea, et),
            'cert_target': ct, 'cert_actual': ca, 'cert_pct': pct(ca, ct),
            'place_target': pt, 'place_actual': pa, 'place_pct': pct(pa, pt),
        })

    # ── Manpower + Staff Status: narrow centres further when a Project is selected ──
    # `filtered_centre_ids` is the BU/TM/cluster scope. If the user has also picked
    # a Project, restrict to centres that actually run that project (same behaviour
    # as the Centre dropdown). Without this, Manpower + Trainer/Mobilizer Status
    # show staff from BU/TM-matched centres that don't run the selected project.
    manpower_centre_ids = filtered_centre_ids
    if project_name:
        project_centre_ids = set(
            BatchPlan.objects.filter(project_name=project_name)
            .values_list('centre_id', flat=True).distinct()
        )
        manpower_centre_ids = [cid for cid in filtered_centre_ids if cid in project_centre_ids]

    staff_qs = ManpowerStaff.objects.filter(centre_id__in=manpower_centre_ids)
    if centre_id_filter:
        staff_qs = staff_qs.filter(centre_id=centre_id_filter)
    staff_list = list(staff_qs.order_by('role', 'employee_name'))
    role_summary = defaultdict(int)
    for s in staff_list:
        role_summary[s.role] += 1

    staff_status = build_staff_status(None, staff_qs)

    # Staffing tab — filter option lists for dropdowns
    staffing_regions = sorted(set(
        DemandSupply.objects.exclude(region='').values_list('region', flat=True)
    ))
    staffing_cities = sorted(set(
        DemandSupply.objects.exclude(city_location='').values_list('city_location', flat=True)
    ))
    staffing_clusters = sorted(set(
        DemandSupply.objects.exclude(industrial_estate_cluster='').values_list('industrial_estate_cluster', flat=True)
    ))
    staffing_clients = sorted(set(
        DemandSupply.objects.exclude(existing_client='').values_list('existing_client', flat=True)
    ))

    # Build delayed batches for MIS dashboard table
    all_batch_rows = build_batch_delay_rows(batches)
    centre_name_map = {c.centre_id: c.centre_name for c in all_centres_qs}
    delayed_batches = []
    for r in all_batch_rows:
        delays = []
        if r['enrol_delayed']:
            delays.append({
                'type': 'Enrolment',
                'planned_date': r['enrol_planned_date'],
                'delay_days': r['enrol_delay_days'],
                'delay_type': r['enrol_delay_type'],
                'target': r['enrol_target'],
                'actual': r['enrol_actual'],
            })
        if r['cert_delayed']:
            delays.append({
                'type': 'Certification',
                'planned_date': r['cert_planned_date'],
                'delay_days': r['cert_delay_days'],
                'delay_type': r['cert_delay_type'],
                'target': r['cert_target'],
                'actual': r['cert_actual'],
            })
        if r['place_delayed']:
            delays.append({
                'type': 'Placement',
                'planned_date': r['place_planned_date'],
                'delay_days': r['place_delay_days'],
                'delay_type': r['place_delay_type'],
                'target': r['place_target'],
                'actual': r['place_actual'],
            })
        for d in delays:
            delayed_batches.append({
                'project_name': r['project_name'],
                'centre_name': centre_name_map.get(r['centre_id'], r['centre_id']),
                'centre_id': r['centre_id'],
                'batch_id': r['batch_id'],
                'qp': r['qp'],
                **d,
            })
    # Sort by delay_days descending, only show where actual = 0
    delayed_batches = [b for b in delayed_batches if b['actual'] == 0]
    delayed_batches.sort(key=lambda x: x['delay_days'], reverse=True)

    # Card 1 — ALL delayed batches (actual > 0 or = 0)
    all_delayed = [b for r in all_batch_rows for b in (
        ([{'type': 'Enrolment'}] if r['enrol_delayed'] else []) +
        ([{'type': 'Certification'}] if r['cert_delayed'] else []) +
        ([{'type': 'Placement'}] if r['place_delayed'] else [])
    )]
    delay_all_enrol = sum(1 for r in all_batch_rows if r['enrol_delayed'])
    delay_all_cert  = sum(1 for r in all_batch_rows if r['cert_delayed'])
    delay_all_place = sum(1 for r in all_batch_rows if r['place_delayed'])
    delay_all_total = delay_all_enrol + delay_all_cert + delay_all_place

    # Card 2 — Pending only (actual = 0)
    delay_enrol_count = sum(1 for b in delayed_batches if b['type'] == 'Enrolment')
    delay_cert_count  = sum(1 for b in delayed_batches if b['type'] == 'Certification')
    delay_place_count = sum(1 for b in delayed_batches if b['type'] == 'Placement')
    delay_total_count = len(delayed_batches)

    active_tab = request.GET.get('tab', 'employability')

    return render(request, 'dashboard/index.html', {
        'active_tab': active_tab,
        'fy': fy,
        'available_fys': available_fys,
        'cluster_filter':     cluster_filter,
        'sub_cluster_filter': sub_cluster_filter,
        'bu_heads': bu_heads,
        'bu_head': bu_head,
        'tm_names': tm_names,
        'tm_name_filter': tm_name_filter,
        'projects': projects,
        'project_name': project_name,
        'centres': centres,
        'centre_id_filter': centre_id_filter,
        'qps': qps,
        'mom_months': json.dumps(mom_months),
        'mom_months_list': mom_months,
        'total_row': total_row,
        'centre_summary': centre_summary,
        'staff_list': staff_list,
        'role_summary': dict(role_summary),
        'staffing_regions': staffing_regions,
        'staffing_cities': staffing_cities,
        'staffing_clusters': staffing_clusters,
        'staffing_clients': staffing_clients,
        'staff_status': staff_status,
        'delayed_batches': delayed_batches,
        'delay_all_total': delay_all_total,
        'delay_all_enrol': delay_all_enrol,
        'delay_all_cert':  delay_all_cert,
        'delay_all_place': delay_all_place,
        'delay_enrol_count': delay_enrol_count,
        'delay_cert_count': delay_cert_count,
        'delay_place_count': delay_place_count,
        'delay_total_count': delay_total_count,
    })

def centre_detail(request, centre_id):
    centre = get_object_or_404(Centre, centre_id=centre_id)
    available_fys = get_available_fys()
    fy = request.GET.get('fy', available_fys[0] if available_fys else '2026-27')
    project_name = request.GET.get('project', '')

    batches = BatchPlan.objects.filter(centre=centre)
    if project_name:
        batches = batches.filter(project_name=project_name)

    projects = sorted(set(
        BatchPlan.objects.filter(centre=centre).exclude(project_name='').values_list('project_name', flat=True)
    ))
    mom_months = build_mom_rows(batches, fy)

    qp_map = defaultdict(list)
    for b in batches:
        qp_map[b.qp].append(b)

    qp_rows = []
    for qp_name, qp_batches in sorted(qp_map.items()):
        qp_mom = build_mom_rows(qp_batches, fy)
        et = sum(r['enrol_target'] for r in qp_mom)
        ea = sum(r['enrol_actual'] for r in qp_mom)
        ct = sum(r['cert_target'] for r in qp_mom)
        ca = sum(r['cert_actual'] for r in qp_mom)
        pt = sum(r['place_target'] for r in qp_mom)
        pa = sum(r['place_actual'] for r in qp_mom)
        qp_rows.append({
            'qp': qp_name,
            'batch_count': len(qp_batches),
            'candidate_count': sum(b.fy_e_act for b in qp_batches),  # FY actuals as proxy
            'enrol_target': et, 'enrol_actual': ea, 'enrol_pct': pct(ea, et),
            'cert_target': ct, 'cert_actual': ca, 'cert_pct': pct(ca, ct),
            'place_target': pt, 'place_actual': pa, 'place_pct': pct(pa, pt),
            'mom_rows': qp_mom,
        })

    batch_rows = build_batch_delay_rows(batches)

    # Totals for summary cards
    total_row = {
        'enrol_target': sum(r['enrol_target'] for r in batch_rows),
        'enrol_actual': sum(r['enrol_actual'] for r in batch_rows),
        'cert_target':  sum(r['cert_target']  for r in batch_rows),
        'cert_actual':  sum(r['cert_actual']  for r in batch_rows),
        'place_target': sum(r['place_target'] for r in batch_rows),
        'place_actual': sum(r['place_actual'] for r in batch_rows),
        'enrol_delayed_count': sum(1 for r in batch_rows if r['enrol_delayed']),
        'cert_delayed_count':  sum(1 for r in batch_rows if r['cert_delayed']),
        'place_delayed_count': sum(1 for r in batch_rows if r['place_delayed']),
    }
    total_row['total_delayed_count'] = (
        total_row['enrol_delayed_count'] +
        total_row['cert_delayed_count'] +
        total_row['place_delayed_count']
    )
    total_row['enrol_pct'] = pct(total_row['enrol_actual'], total_row['enrol_target'])
    total_row['cert_pct']  = pct(total_row['cert_actual'],  total_row['cert_target'])
    total_row['place_pct'] = pct(total_row['place_actual'], total_row['place_target'])

    staff = ManpowerStaff.objects.filter(centre=centre).order_by('role', 'employee_name')
    role_summary = defaultdict(int)
    for s in staff:
        role_summary[s.role] += 1

    staff_status = build_staff_status(None, staff)

    batch_rows_json = json.dumps([
        {
            'enrol_delayed': r['enrol_delayed'],
            'cert_delayed':  r['cert_delayed'],
            'place_delayed': r['place_delayed'],
        }
        for r in batch_rows
    ])

    return render(request, 'dashboard/centre_detail.html', {
        'centre': centre,
        'fy': fy,
        'available_fys': available_fys,
        'project_name': project_name,
        'projects': projects,
        'mom_months': json.dumps(mom_months),
        'mom_months_list': mom_months,
        'total_row': total_row,
        'qp_rows': qp_rows,
        'batch_rows': batch_rows,
        'batch_rows_json': batch_rows_json,
        'staff': staff,
        'role_summary': dict(role_summary),
        'delay_enrol': total_row['enrol_delayed_count'],
        'delay_cert':  total_row['cert_delayed_count'],
        'delay_place': total_row['place_delayed_count'],
        'delay_total': total_row['total_delayed_count'],
        'staff_status': staff_status,
    })
