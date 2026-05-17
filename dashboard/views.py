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

    sc_qs_centre = Centre.objects.exclude(sub_cluster='').exclude(sub_cluster=None)
    sc_qs_master = ClusterMaster.objects.exclude(sub_cluster='')
    if cluster_filter:
        sc_qs_centre = sc_qs_centre.filter(cluster=cluster_filter)
        sc_qs_master = sc_qs_master.filter(cluster=cluster_filter)
    sub_clusters = sorted(
        set(sc_qs_centre.values_list('sub_cluster', flat=True))
        | set(sc_qs_master.values_list('sub_cluster', flat=True))
    )

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
        'selected_map_url':    selected_map_url,
        'selected_state':      selected_state,
    })


def cluster_sub_clusters_api(request):
    """Sub-clusters under a given cluster — union of Centre + ClusterMaster."""
    cluster = request.GET.get('cluster', '')
    centre_sc = Centre.objects.exclude(sub_cluster='').exclude(sub_cluster=None)
    master_sc = ClusterMaster.objects.exclude(sub_cluster='')
    if cluster:
        centre_sc = centre_sc.filter(cluster=cluster)
        master_sc = master_sc.filter(cluster=cluster)
    sub_clusters = sorted(
        set(centre_sc.values_list('sub_cluster', flat=True))
        | set(master_sc.values_list('sub_cluster', flat=True))
    )
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
    Per-sub-cluster data-coverage matrix used by the Home page coverage table.
    Only meaningful when a Cluster is selected (1A spec).

    Columns:
      Sub Cluster | Employability | SMB | SAHI | Sambhav Community

    Definitions (2A):
      Employability ✓ : ≥1 Centre exists in that sub-cluster
      SMB           ✓ : ≥1 HyperlocalJob OR NapsEligible record reachable
                        from centres in that sub-cluster
      SAHI          ✓ : ≥1 SAHIDemand row for that sub-cluster
      Sambhav       ✓ : ≥1 SambhavCommunity row for that sub-cluster
    """
    cluster = request.GET.get('cluster', '')
    if not cluster:
        return JsonResponse({'rows': [], 'show': False})

    # Sub-cluster universe = union of all 4 sources within this cluster
    sc_master = set(ClusterMaster.objects.filter(cluster=cluster)
                    .exclude(sub_cluster='').values_list('sub_cluster', flat=True))
    sc_centre = set(Centre.objects.filter(cluster=cluster)
                    .exclude(sub_cluster='').exclude(sub_cluster=None)
                    .values_list('sub_cluster', flat=True))
    sc_demand = set(SAHIDemand.objects.filter(cluster=cluster)
                    .exclude(sub_cluster='').values_list('sub_cluster', flat=True))
    sc_sambhav = set(SambhavCommunity.objects.filter(cluster=cluster)
                     .exclude(sub_cluster='').values_list('sub_cluster', flat=True))
    sub_clusters = sorted(sc_master | sc_centre | sc_demand | sc_sambhav)

    # Pre-fetch centre→sub_cluster mapping for SMB checks (one query)
    centre_to_sc = dict(
        Centre.objects.filter(cluster=cluster)
        .exclude(sub_cluster='').exclude(sub_cluster=None)
        .values_list('centre_id', 'sub_cluster')
    )
    # Sub-clusters with at least one HyperlocalJob centre
    hj_sub_clusters = set(
        centre_to_sc[cid] for cid in
        HyperlocalJob.objects.filter(centre_id__in=list(centre_to_sc.keys()))
        .values_list('centre_id', flat=True).distinct()
        if cid in centre_to_sc
    )
    # Sub-clusters with at least one NAPS QP via BatchPlan → NAPS join
    naps_qps = set(NapsEligible.objects.values_list('qp', flat=True))
    naps_sub_clusters = set(
        centre_to_sc[cid] for cid in
        BatchPlan.objects.filter(centre_id__in=list(centre_to_sc.keys()), qp__in=naps_qps)
        .values_list('centre_id', flat=True).distinct()
        if cid in centre_to_sc
    )

    rows = []
    for sc in sub_clusters:
        rows.append({
            'sub_cluster':     sc,
            'employability':   sc in sc_centre,
            'smb':             (sc in hj_sub_clusters) or (sc in naps_sub_clusters),
            'sahi':            sc in sc_demand,
            'sambhav':         sc in sc_sambhav,
        })

    totals = {
        'rows':          len(rows),
        'employability': sum(1 for r in rows if r['employability']),
        'smb':           sum(1 for r in rows if r['smb']),
        'sahi':          sum(1 for r in rows if r['sahi']),
        'sambhav':       sum(1 for r in rows if r['sambhav']),
    }

    return JsonResponse({'rows': rows, 'totals': totals, 'show': True, 'cluster': cluster})


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
    Home page summary API. Driven by Cluster + Sub Cluster only.
    SAHI card now bridges via direct match on Cluster / Sub Cluster
    (SAHIDemand and Centre share the same taxonomy now).
    """
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')

    # ── Centre set for Employability + SMB ────────────────────────────────
    centre_qs = Centre.objects.all()
    if cluster:
        centre_qs = centre_qs.filter(cluster=cluster)
    if sub_cluster:
        centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
    centre_ids = list(centre_qs.values_list('centre_id', flat=True))

    scope_active = bool(cluster or sub_cluster)

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
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')
    centre_id    = request.GET.get('centre_id', '')
    # Cert-Schedule-side filters: narrow NAPS to QPs of the selected
    # project / cert window / course — direct project→QP relationship, NOT
    # "all QPs at that project's centres".
    cs_bu_head      = request.GET.get('cs_bu_head', '')
    cs_tm_name      = request.GET.get('cs_tm_name', '')
    cs_project      = request.GET.get('cs_project', '')
    cs_cert_window  = request.GET.get('cs_cert_window', '')
    cs_qp_course    = request.GET.get('cs_qp', '')

    # Start with all NAPS records
    qs = NapsEligible.objects.all()

    cs_filter_active = any([cs_project, cs_cert_window, cs_qp_course])
    scope_via_centres = any([
        cluster, sub_cluster, centre_id,
        cs_bu_head, cs_tm_name,
    ])

    # Build the QP set in two passes:
    # 1) If cs_project / cs_cert_window / cs_qp_course is set, the QPs come
    #    directly from BatchPlan rows for that project (not from sibling
    #    QPs that happen to share a centre).
    # 2) Otherwise (centre-only or home-cluster scope), fall back to "all
    #    QPs run at the in-scope centres".
    qp_set = None
    if cs_filter_active:
        from dashboard.models import CertSchedule
        cs_qs = CertSchedule.objects.all()
        if cs_project:     cs_qs = cs_qs.filter(project=cs_project)
        if cs_cert_window: cs_qs = cs_qs.filter(cert_window=cs_cert_window)
        if cs_qp_course:   cs_qs = cs_qs.filter(course_trade=cs_qp_course)
        # Pull QP set from the SAME project's BatchPlan rows
        project_centre_ids = set(
            cs_qs.exclude(centre__isnull=True)
                 .values_list('centre__centre_id', flat=True).distinct()
        )
        bp_qs = BatchPlan.objects.filter(centre_id__in=project_centre_ids)
        if cs_project:
            bp_qs = bp_qs.filter(project_name=cs_project)
        qp_set = set(bp_qs.exclude(qp='').values_list('qp', flat=True))
        # If a specific centre is picked too, intersect with that centre's QPs
        if centre_id:
            centre_qps = set(
                BatchPlan.objects.filter(centre_id=centre_id, project_name=cs_project)
                .exclude(qp='').values_list('qp', flat=True)
            ) if cs_project else set(
                BatchPlan.objects.filter(centre_id=centre_id)
                .exclude(qp='').values_list('qp', flat=True)
            )
            qp_set &= centre_qps

    elif scope_via_centres:
        centre_qs = Centre.objects.all()
        if cluster:
            centre_qs = centre_qs.filter(cluster=cluster)
        if sub_cluster:
            centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
        if cs_bu_head: centre_qs = centre_qs.filter(bu_head=cs_bu_head)
        if cs_tm_name: centre_qs = centre_qs.filter(tm_name=cs_tm_name)
        if centre_id: centre_qs = centre_qs.filter(centre_id=centre_id)
        centre_ids = list(centre_qs.values_list('centre_id', flat=True))
        qp_set = set(
            BatchPlan.objects.filter(centre_id__in=centre_ids)
            .exclude(qp='').values_list('qp', flat=True)
        )

    if qp_set is not None:
        qs = qs.filter(qp__in=qp_set)

    # Additional search/filter params
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
    category = request.GET.get('category', '')
    qs = CommunityCollege.objects.all()
    if centre_id:
        qs = qs.filter(centre__centre_id=centre_id)
    if category:
        qs = qs.filter(category__iexact=category)
    data = list(qs.values(
        'sno', 'category', 'name_place', 'address',
        'phone_hours', 'centre_name', 'distance_km', 'rating'
    ).order_by('distance_km'))
    return JsonResponse({'results': data, 'count': len(data)})


def community_college_categories_api(request):
    """Return distinct categories for the given centre (or all centres)."""
    centre_id = request.GET.get('centre_id', '')
    qs = CommunityCollege.objects.all()
    if centre_id:
        qs = qs.filter(centre__centre_id=centre_id)
    categories = sorted(set(
        qs.exclude(category='').values_list('category', flat=True)
    ))
    return JsonResponse({'categories': categories})


# ── API: Cert Schedule (SMB) ──────────────────────────────────────────────────

def smb_cert_filter_options_api(request):
    """Cascading filter options for SMB → Cert Schedule.

    Pyramid: BU Head → TM Name → Project → Cert Window → Centre → QP (Course).
    Each filter narrows the next.
    Also respects Home filters: cluster / sub_cluster.
    """
    from dashboard.models import CertSchedule

    bu_head      = request.GET.get('bu_head', '')
    tm_name      = request.GET.get('tm_name', '')
    project      = request.GET.get('project', '')
    cert_window  = request.GET.get('cert_window', '')
    centre_id    = request.GET.get('centre_id', '')
    # Home cross-filters
    cluster      = request.GET.get('cluster', '')
    sub_cluster  = request.GET.get('sub_cluster', '')

    # ── Resolve centre universe based on Home + BU Head + TM Name ──
    centre_qs = Centre.objects.all()
    if cluster:     centre_qs = centre_qs.filter(cluster=cluster)
    if sub_cluster: centre_qs = centre_qs.filter(sub_cluster=sub_cluster)
    home_scope_active = bool(cluster or sub_cluster)

    if bu_head:
        centre_qs = centre_qs.filter(bu_head=bu_head)
    if tm_name:
        centre_qs = centre_qs.filter(tm_name=tm_name)
    scoped_centre_ids = list(centre_qs.values_list('centre_id', flat=True))

    # Cert rows scoped by centre membership (always scope when Home filters or BU/TM are set)
    if home_scope_active or bu_head or tm_name:
        cs = CertSchedule.objects.filter(centre_id__in=scoped_centre_ids)
    else:
        cs = CertSchedule.objects.all()

    # Project depends on the scope (centre)
    projects = sorted(set(cs.exclude(project='').values_list('project', flat=True)))

    # Cert Window depends on project too
    win_qs = cs
    if project: win_qs = win_qs.filter(project=project)
    cert_windows = sorted(set(win_qs.exclude(cert_window='').values_list('cert_window', flat=True)))

    # Centre dropdown — narrows by project, cert_window
    centre_filter_qs = cs
    if project:     centre_filter_qs = centre_filter_qs.filter(project=project)
    if cert_window: centre_filter_qs = centre_filter_qs.filter(cert_window=cert_window)
    cs_centre_ids = set(centre_filter_qs.exclude(centre__isnull=True)
                                       .values_list('centre__centre_id', flat=True).distinct())
    centres_qs = centre_qs.filter(centre_id__in=cs_centre_ids) if cs_centre_ids \
                 else Centre.objects.none()
    centres = list(centres_qs.values('centre_id', 'centre_name').order_by('centre_name'))

    # QP / Course depends on everything above
    qp_qs = centre_filter_qs
    if centre_id: qp_qs = qp_qs.filter(centre__centre_id=centre_id)
    qps = sorted(set(qp_qs.exclude(course_trade='').values_list('course_trade', flat=True)))

    # TM Names depend on bu_head + Home scope
    tm_qs = Centre.objects.all()
    if cluster:     tm_qs = tm_qs.filter(cluster=cluster)
    if sub_cluster: tm_qs = tm_qs.filter(sub_cluster=sub_cluster)
    if bu_head:
        tm_qs = tm_qs.filter(bu_head=bu_head)
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
        'cert_windows': cert_windows,
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


# ── API: hyperlocal jobs ──────────────────────────────────────────────────────

def hyperlocal_jobs_api(request):
    centre_id = request.GET.get('centre_id', '')
    qp = request.GET.get('qp', '')
    qs = HyperlocalJob.objects.all()
    if centre_id:
        qs = qs.filter(centre__centre_id=centre_id)
    if qp:
        qs = qs.filter(course__icontains=qp)
    data = list(qs.values(
        'course', 'sector', 'discovered_employer', 'phone',
        'employer_address', 'suitable_roles', 'centre_name',
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
    bp_for_proj = BatchPlan.objects.filter(centre_id__in=filtered_centre_ids)
    projects = sorted(set(bp_for_proj.exclude(project_name='').values_list('project_name', flat=True)))

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

    staff_qs = ManpowerStaff.objects.filter(centre_id__in=filtered_centre_ids)
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
