import pandas as pd
import numpy as np
import re
from django.core.management.base import BaseCommand
from dashboard.models import (Centre, BatchPlan, CertSchedule, ManpowerStaff,
                              CommunityCollege, HyperlocalJob, NapsEligible,
                              ClusterMaster, SambhavCommunity, NAPSData, NAPSPlan,
                              OutreachStatus, SalesPipeline, RecruitmentFunnel)


# India bounding box (lat 6–38, lng 67–98). Anything outside is treated as junk.
_RE_AT_CENTER = re.compile(r'@([-\d.]+),([-\d.]+),')
_RE_DIR_STOP  = re.compile(r'!1d([-\d.]+)!2d([-\d.]+)')   # directions URL → !1dLNG!2dLAT
_RE_PLACE_3D4D = re.compile(r'!3d([-\d.]+)!4d([-\d.]+)')   # place URL → !3dLAT!4dLNG


def parse_lat_lng(url):
    """Extract a (lat, lng) center pair from a Google Maps URL.
    Tries @lat,lng, then !3d/!4d (place), then the first !1d/!2d stop (directions).
    Returns (None, None) if nothing usable is found."""
    if not isinstance(url, str) or not url:
        return None, None
    m = _RE_AT_CENTER.search(url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if 6 < lat < 38 and 67 < lng < 98:
            return lat, lng
    m = _RE_PLACE_3D4D.search(url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        if 6 < lat < 38 and 67 < lng < 98:
            return lat, lng
    m = _RE_DIR_STOP.search(url)
    if m:
        lng, lat = float(m.group(1)), float(m.group(2))   # note ordering
        if 6 < lat < 38 and 67 < lng < 98:
            return lat, lng
    return None, None


def parse_stops(url):
    """Extract a list of [lat, lng] for every individual stop in a Google Maps
    directions URL. Returns []  when no stops are present (single-place URLs)."""
    if not isinstance(url, str) or not url:
        return []
    stops = []
    for lng, lat in _RE_DIR_STOP.findall(url):
        lat_f, lng_f = float(lat), float(lng)
        if 6 < lat_f < 38 and 67 < lng_f < 98:
            stops.append([lat_f, lng_f])
    # Deduplicate while preserving order (some URLs repeat the same point)
    seen, deduped = set(), []
    for p in stops:
        key = (round(p[0], 6), round(p[1], 6))
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def safe_date(val):
    if pd.isna(val):
        return None
    try:
        return pd.Timestamp(val).date()
    except Exception:
        return None


def safe_int(val):
    try:
        if pd.isna(val):
            return 0
        return int(val)
    except Exception:
        return 0


def safe_str(val):
    if pd.isna(val):
        return ''
    return str(val).strip()


# Maps dirty / non-standard Center Master state spellings to the clean
# state names used in Associate Data (so Supply State filtering matches).
_STATE_FIXES = {
    'gujarat':        'Gujarat',
    'karnataka':      'Karnataka',
    'maharashtra':    'Maharashtra',
    'telelanga':      'Telangana',
    'telangana':      'Telangana',
    'kolkata':        'West Bengal',
    'dadra & nagar haveli': 'The Dadra And Nagar Haveli And Daman And Diu',
}

def _normalize_state(val):
    s = safe_str(val)
    if not s:
        return ''
    return _STATE_FIXES.get(s.lower(), s)


def safe_float(val):
    try:
        if pd.isna(val):
            return 0.0
        return float(val)
    except Exception:
        return 0.0


def safe_int_or_none(val):
    """Like safe_int but returns None instead of 0 for missing values —
    so the difference between 'zero positions' and 'unknown' is preserved."""
    try:
        if pd.isna(val):
            return None
        return int(val)
    except Exception:
        return None


class Command(BaseCommand):
    help = 'Import all Excel data into the database'

    def add_arguments(self, parser):
        parser.add_argument('--data-dir', default='data', help='Directory containing Excel files (default: data/ folder in project root)')

    def handle(self, *args, **options):
        data_dir = options['data_dir']
        self.stdout.write('Clearing existing data...')
        ManpowerStaff.objects.all().delete()
        BatchPlan.objects.all().delete()
        Centre.objects.all().delete()
        ClusterMaster.objects.all().delete()

        # 0a. Load ClusterMaster (Cluster_Master_v1.xlsx → ClusterMaster table)
        self.stdout.write('Loading Cluster_Master_v1.xlsx into ClusterMaster...')
        try:
            cmst = pd.read_excel(f'{data_dir}/Cluster_Master_v1.xlsx')
            created = 0
            for _, row in cmst.iterrows():
                scid = safe_str(row.get('Sub Cluster ID', ''))
                if not scid:
                    continue
                map_url = safe_str(row.get('Map', ''))
                lat, lng = parse_lat_lng(map_url)
                stops    = parse_stops(map_url)
                ClusterMaster.objects.update_or_create(
                    sub_cluster_id=scid,
                    defaults={
                        'cluster':     safe_str(row.get('Cluster', '')),
                        'sub_cluster': safe_str(row.get('Sub Cluster', '')),
                        'state':       safe_str(row.get('State', '')),
                        'map_url':     map_url,
                        'lat':         lat,
                        'lng':         lng,
                        'stops':       stops,
                    }
                )
                created += 1
            self.stdout.write(f'  {created} ClusterMaster rows loaded')
        except FileNotFoundError:
            self.stdout.write('  Cluster_Master_v1.xlsx not found, skipping')

        # 0c. Load Sambhav Community (Sambhav_Community.xlsx → SambhavCommunity table)
        self.stdout.write('Loading Sambhav_Community.xlsx into SambhavCommunity...')
        SambhavCommunity.objects.all().delete()
        try:
            scdf = pd.read_excel(f'{data_dir}/Sambhav_Community.xlsx')
            created = 0
            for _, row in scdf.iterrows():
                project = safe_str(row.get('Project', ''))
                if not project:
                    continue
                SambhavCommunity.objects.create(
                    project        = project,
                    sub_cluster    = safe_str(row.get('Sub Cluster', '')),
                    sub_cluster_id = safe_str(row.get('Sub Cluster ID', '')),
                    cluster        = safe_str(row.get('Cluster', '')),
                    location       = safe_str(row.get('Location', '')),
                    project_brief  = safe_str(row.get('Project Brief', '')),
                    tm             = safe_str(row.get('TM', '')),
                )
                created += 1
            self.stdout.write(f'  {created} SambhavCommunity rows loaded')
        except FileNotFoundError:
            self.stdout.write('  Sambhav_Community.xlsx not found, skipping')

        # 0b. Build centre_id → cluster mapping from Center Master.xlsx
        # New schema: Sub Cluster ID | Cluster | Sub Cluster (replaces old Cluster Name / Sub Cluster Name)
        self.stdout.write('Loading cluster data from Center Master.xlsx...')
        cluster_map = {}
        try:
            cm = pd.read_excel(f'{data_dir}/Center Master.xlsx')
            for _, row in cm.iterrows():
                cid = safe_str(row.get('Centre ID', ''))
                if cid:
                    cluster_map[cid] = {
                        'sub_cluster_id': safe_str(row.get('Sub Cluster ID', '')),
                        'cluster':        safe_str(row.get('Cluster', '')),
                        'sub_cluster':    safe_str(row.get('Sub Cluster', '')),
                        'entity':         safe_str(row.get('Entity', '')),
                        'state':          _normalize_state(safe_str(row.get('State', ''))),
                        'center_status':  safe_str(row.get(
                            'Center Status (Active/ Closed/ Going to Close)', '')),
                    }
            self.stdout.write(f'  {len(cluster_map)} centre→cluster mappings loaded')
        except FileNotFoundError:
            self.stdout.write('  Center Master.xlsx not found, skipping')

        # 1. Import Ops Team (Centre master)
        self.stdout.write('Importing Centres from Ops_Team.xlsx...')
        ops = pd.read_excel(f'{data_dir}/Ops_Team.xlsx')
        for _, row in ops.iterrows():
            cid = safe_str(row['Centre ID'])
            if not cid:
                continue
            cm_data = cluster_map.get(cid, {})
            Centre.objects.get_or_create(
                centre_id=cid,
                defaults={
                    'centre_name':    safe_str(row['Centre Name']),
                    'bu_head':        safe_str(row.get('BU Head', '')),
                    'pmt_lead':       safe_str(row.get('PMT Lead', '')),
                    'tm_name':        safe_str(row.get('TM Name', '')),
                    'sub_cluster_id': cm_data.get('sub_cluster_id', ''),
                    'cluster':        cm_data.get('cluster', ''),
                    'sub_cluster':    cm_data.get('sub_cluster', ''),
                    'state':          cm_data.get('state', ''),
                    'entity':         cm_data.get('entity', ''),
                    'center_status':  cm_data.get('center_status', ''),
                }
            )
        self.stdout.write(f'  {Centre.objects.count()} centres loaded')

        # Also ensure all centre IDs from Batch_Plan_New and Manpower exist
        bp_raw = pd.read_excel(f'{data_dir}/Batch_Plan_New.xlsx')
        # Normalise headers: the source file has stray leading/trailing spaces
        # (e.g. ' FY 26-27 E Act', ' FY 26-27 E Target') which break exact-name lookups.
        bp_raw.columns = bp_raw.columns.str.strip()
        mm_raw = pd.read_excel(f'{data_dir}/Manpower_Master_1.xlsx')

        all_centre_ids = set()
        for df, id_col, name_col in [
            (bp_raw, 'Centre ID', 'Center'),
            (mm_raw, 'Centre ID', 'Center as per sahi'),
        ]:
            for _, row in df.iterrows():
                cid = safe_str(row[id_col])
                if cid and not Centre.objects.filter(centre_id=cid).exists():
                    cm_data = cluster_map.get(cid, {})
                    Centre.objects.get_or_create(
                        centre_id=cid,
                        defaults={'centre_name': safe_str(row.get(name_col, cid)), **cm_data}
                    )
        self.stdout.write(f'  Total centres: {Centre.objects.count()}')

        # 2. Import Batch Plan (new format) — actuals now live on the batch row
        self.stdout.write('Importing Batch Plan (Batch_Plan_New.xlsx)...')
        created = 0
        # Tolerate header variants: leading spaces in 'Final ... Planned' columns,
        # singular 'Sub Project name ', etc.
        def col(row, *names):
            for n in names:
                if n in row.index:
                    return row[n]
            return None

        for _, row in bp_raw.iterrows():
            cid = safe_str(row['Centre ID'])
            bid = safe_str(row['Batch ID'])
            if not bid or not cid:
                continue
            try:
                centre = Centre.objects.get(centre_id=cid)
            except Centre.DoesNotExist:
                continue
            BatchPlan.objects.update_or_create(
                batch_id=bid,
                defaults={
                    'centre': centre,
                    'centre_name':         safe_str(col(row, 'Center', 'Centre Name', 'Center Name')),
                    'qp':                  safe_str(col(row, 'QP Name', 'QP')),
                    'project_name':        safe_str(col(row, 'Project Name(SAHI)', 'Project Name')),
                    'sub_project_name':    safe_str(col(row, 'Sub Project name', 'Sub Project Name')),
                    'projects_fy':         safe_str(col(row, 'Projects_FY')),

                    # Planned dates
                    'batch_planned_start_date':         safe_date(col(row, 'Batch_Planned_Start_Date', 'Batch Planned Start Date')),
                    'certification_planned_start_date': safe_date(col(row, 'Certification_Start_Date',  'Certification Planned  Start Date')),
                    'placement_planned_end_date':       safe_date(col(row, 'Placement_End_Date',         'Placement Planned End Date')),

                    # Actual dates
                    'batch_actual_start_date':              safe_date(col(row, 'Batch Actual Start Date')),
                    'assessment_actual_certification_date': safe_date(col(row, 'Assessment Actual Certification Date')),
                    'placed_date':                          safe_date(col(row, 'Placed Date')),

                    # Targets (new format: 'FY 26-27 E/C/P Target'; old: 'Final ... Planned')
                    'final_enrolment_planned':     safe_int(col(row, 'FY 26-27 E Target', 'Final Enrolment Planned')),
                    'final_certification_planned': safe_int(col(row, 'FY 26-27 C Target', 'Final Certification Planned')),
                    'final_placement_planned':     safe_int(col(row, 'FY 26-27 P Target', 'Final Placement Planned')),

                    # FY 26-27 actuals (Q1A: trusted source)
                    'on_going': safe_int(col(row, 'On Going')),
                    'fy_e_act': safe_int(col(row, 'FY 26-27 E Act')),
                    'fy_c_act': safe_int(col(row, 'FY 26-27 C Act')),
                    'fy_p_act': safe_int(col(row, 'FY 26-27 P Act')),
                    'fy_naps_act': safe_int(col(row, 'FY 26-27 NAPS Act')),
                    'fy_nats_act': safe_int(col(row, 'FY 26-27 NATS Act')),

                    # Entity (SF / LLF)
                    'entity':   safe_str(col(row, 'Entity')),

                    # New-format columns (Jul-2026 refresh)
                    'skilling_type': safe_str(col(row, 'Skilling Type')),
                    'qp_code':       safe_str(col(row, 'QP Code')),
                    'naps_aligned':  safe_str(col(row, 'NAPS Aligned')),
                    'nats_aligned':  safe_str(col(row, 'NATS Aligned')),
                }
            )
            created += 1
        self.stdout.write(f'  {created} batches loaded')

        # 4. Import Manpower
        self.stdout.write('Importing Manpower...')
        created = 0
        for _, row in mm_raw.iterrows():
            cid = safe_str(row['Centre ID'])
            try:
                centre = Centre.objects.get(centre_id=cid)
            except Centre.DoesNotExist:
                centre = None
            ManpowerStaff.objects.create(
                ecode=safe_str(row['Ecode']),
                employee_name=safe_str(row['Employee Name']),
                official_email=safe_str(row['Official Email ID']),
                employee_status=safe_str(row['Employee Status']),
                sub_project_name=safe_str(row['Sub-project Name']),
                sub_project_code=safe_str(row['Sub Project Code']),
                role=safe_str(row['Role as per Ops ']),
                center_name_ops=safe_str(row['Center as per sahi']),
                centre=centre,
            )
            created += 1
        self.stdout.write(f'  {created} staff loaded')

        # 5. Import Community Colleges
        import os
        cc_path = f'{data_dir}/Community____Colleges.xlsx'
        if os.path.exists(cc_path):
            self.stdout.write('Importing Community Colleges...')
            CommunityCollege.objects.all().delete()
            cc_raw = pd.read_excel(cc_path)
            created = 0
            for _, row in cc_raw.iterrows():
                cid = safe_str(row.get('Centre ID', ''))
                centre = None
                try:
                    if cid:
                        centre = Centre.objects.get(centre_id=cid)
                except Centre.DoesNotExist:
                    pass
                try:
                    sno = int(row['S.No']) if not pd.isna(row['S.No']) else None
                except Exception:
                    sno = None
                def safe_float(v):
                    try:
                        return float(v) if not pd.isna(v) else None
                    except Exception:
                        return None
                CommunityCollege.objects.create(
                    sno=sno,
                    source=safe_str(row.get('Source', '')),
                    category=safe_str(row.get('Category', '')),
                    name_place=safe_str(row.get('Name / Place', '')),
                    address=safe_str(row.get('Address', '')),
                    latitude=safe_float(row.get('Latitude')),
                    longitude=safe_float(row.get('Longitude')),
                    distance_km=safe_float(row.get('Distance (km)')),
                    rating=safe_float(row.get('Rating')),
                    phone_hours=safe_str(row.get('Phone / Hours', '')),
                    centre_name=safe_str(row.get('Center Name', '')),
                    centre=centre,
                )
                created += 1
            self.stdout.write(f'  {created} community college records loaded')
        else:
            self.stdout.write(f'  Skipping Community Colleges (file not found: {cc_path})')

        # 6. Import Hyperlocal Jobs
        hj_path = f'{data_dir}/Hyperlocal_jobs.xlsx'
        if os.path.exists(hj_path):
            self.stdout.write('Importing Hyperlocal Jobs...')
            HyperlocalJob.objects.all().delete()
            hj_raw = pd.read_excel(hj_path)
            created = 0
            for _, row in hj_raw.iterrows():
                cid = safe_str(row.get('Centre ID', ''))
                centre = None
                try:
                    if cid:
                        centre = Centre.objects.get(centre_id=cid)
                except Centre.DoesNotExist:
                    pass
                def safe_float(v):
                    try:
                        return float(v) if not pd.isna(v) else None
                    except Exception:
                        return None
                def safe_int2(v):
                    try:
                        return int(v) if not pd.isna(v) else None
                    except Exception:
                        return None
                HyperlocalJob.objects.create(
                    course=safe_str(row.get('Course', '')),
                    sector=safe_str(row.get('Sector', '')),
                    district=safe_str(row.get('District', '')),
                    state=safe_str(row.get('State', '')),
                    discovered_employer=safe_str(row.get('Discovered Employer', '')),
                    discovered_employer_id=safe_str(row.get('Discovered Employer ID', '')),
                    phone=safe_str(row.get('Phone', '')),
                    employer_address=safe_str(row.get('Employer Address', '')),
                    distance_km=safe_float(row.get('Distance (km)')),
                    rating=safe_float(row.get('Rating')),
                    reviews=safe_int2(row.get('Reviews')),
                    naps_eligible=safe_str(row.get('NAPS Eligible', '')),
                    suitable_roles=safe_str(row.get('Suitable Roles', '')),
                    outreach_status=safe_str(row.get('Outreach Status', '')),
                    centre_name=safe_str(row.get('Centre Name', '')),
                    centre=centre,
                )
                created += 1
            self.stdout.write(f'  {created} hyperlocal job records loaded')
        else:
            self.stdout.write(f'  Skipping Hyperlocal Jobs (file not found: {hj_path})')

        # 7. Import NAPS Eligible
        naps_path = f'{data_dir}/NAPS Eligible.xlsx'
        try:
            self.stdout.write('Importing NAPS Eligible data...')
            NapsEligible.objects.all().delete()
            naps_df = pd.read_excel(naps_path)
            created = 0
            for _, row in naps_df.iterrows():
                # File uses 'QP Name' column (not 'QP')
                qp = safe_str(row.get('QP Name', '') or row.get('QP', ''))
                if not qp:
                    continue
                NapsEligible.objects.create(
                    qp=qp,
                    naps_eligible=safe_str(row.get('NAPS Eligible', '')),
                    course_name=safe_str(row.get('course_name', '') or row.get('Course Name', '')),
                    course_type=safe_str(row.get('course_type', '') or row.get('Course Type', '')),
                    sector=safe_str(row.get('Sector', '') or row.get('sector/Industry', '')),
                    minimum_qualification=safe_str(row.get('minimum_qualification', '')),
                    on_job_training=safe_str(row.get('on_job_training', '')),
                    qp_mapped=safe_str(row.get('QP mapped (yes/no)', '')),
                    # New alignment flags from updated NAPS Eligible.xlsx
                    naps_aligned=safe_str(row.get('NAPS Aligned', '')),
                    nats_aligned=safe_str(row.get('NATS Aligned', '')),
                )
                created += 1
            self.stdout.write(f'  {created} NAPS records loaded')
        except FileNotFoundError:
            self.stdout.write(f'  Skipping NAPS Eligible (file not found: {naps_path})')

        # 7b. Import Sales Pipeline
        import os
        sp_path = f'{data_dir}/Sales_Pipeline.xlsx'
        if os.path.exists(sp_path):
            self.stdout.write('Importing Sales Pipeline...')
            SalesPipeline.objects.all().delete()
            sp_df = pd.read_excel(sp_path)
            # Resolve centre by name
            centre_by_name = {c.centre_name: c for c in Centre.objects.all()}
            created = 0
            for _, row in sp_df.iterrows():
                cname = safe_str(row.get('Center Name', ''))
                SalesPipeline.objects.create(
                    opp_id=safe_str(row.get('Opp ID', '')),
                    created=safe_date(row.get('Created')),
                    centre_name=cname,
                    centre=centre_by_name.get(cname),
                    account_client=safe_str(row.get('Account / Client', '')),
                    client_type=safe_str(row.get('Client Type', '')),
                    sector=safe_str(row.get('Sector', '')),
                    service_line=safe_str(row.get('Service Line', '')),
                    exp_positions=safe_int(row.get('Exp. Positions')),
                    deal_value=safe_int(row.get('Deal Value ₹')),
                    stage=safe_str(row.get('Stage', '')),
                    prob=float(row.get('Prob.') or 0),
                    weighted=safe_int(row.get('Weighted ₹')),
                    exp_close=safe_date(row.get('Exp. Close')),
                    status=safe_str(row.get('Status', '')),
                    next_step=safe_str(row.get('Next Step', '')),
                    last_activity=safe_date(row.get('Last Activity')),
                )
                created += 1
            self.stdout.write(f'  {created} sales pipeline records loaded')
        else:
            self.stdout.write(f'  Skipping Sales Pipeline (file not found: {sp_path})')

        # 7c. Import Recruitment Funnel
        rf_path = f'{data_dir}/Recruitment_Funnel.xlsx'
        if os.path.exists(rf_path):
            self.stdout.write('Importing Recruitment Funnel...')
            RecruitmentFunnel.objects.all().delete()
            rf_df = pd.read_excel(rf_path)
            centre_by_name = {c.centre_name: c for c in Centre.objects.all()}
            created = 0
            for _, row in rf_df.iterrows():
                cname = safe_str(row.get('Center Name', ''))
                RecruitmentFunnel.objects.create(
                    req_id=safe_str(row.get('Req ID', '')),
                    month=safe_str(row.get('Month', '')),
                    centre_name=cname,
                    centre=centre_by_name.get(cname),
                    client=safe_str(row.get('Client', '')),
                    job_role=safe_str(row.get('Job Role', '')),
                    sector=safe_str(row.get('Sector', '')),
                    open_vacancies=safe_int(row.get('Open Vacancies/ Target Hire')),
                    sourced=safe_int(row.get('Sourced')),
                    screened=safe_int(row.get('Screened')),
                    interviewed=safe_int(row.get('Interviewed')),
                    offered=safe_int(row.get('Offered')),
                    joined=safe_int(row.get('Joined')),
                    dropped=safe_int(row.get('Dropped (post-offer)')),
                )
                created += 1
            self.stdout.write(f'  {created} recruitment funnel records loaded')
        else:
            self.stdout.write(f'  Skipping Recruitment Funnel (file not found: {rf_path})')

        # Import Cert Schedule
        cs_path = f'{data_dir}/Cert_Schedule.xlsx'
        self.stdout.write('Importing Cert Schedule...')
        try:
            cs_df = pd.read_excel(cs_path)
            CertSchedule.objects.all().delete()
            # Resolve centre_name → Centre FK
            centre_by_name = {c.centre_name: c for c in Centre.objects.all()}
            created = 0
            for _, row in cs_df.iterrows():
                bid = safe_str(row.get('Batch ID', ''))
                cname = safe_str(row.get('Centre Name', ''))
                if not bid and not cname:
                    continue
                CertSchedule.objects.create(
                    batch_id         = bid,
                    centre_name      = cname,
                    centre           = centre_by_name.get(cname),
                    sub_cluster      = safe_str(row.get('Sub Cluster', '')),
                    cluster          = safe_str(row.get('Cluster', '')),
                    course_trade     = safe_str(row.get('Course / Trade', '')),
                    project          = safe_str(row.get('Project', '')),
                    cert_start_date  = safe_date(row.get('Cert Start Date')),
                    days_to_cert     = safe_int(row.get('Days to Cert', 0)) or None,
                    cert_window      = safe_str(row.get('Cert Window', '')),
                    cert_target      = safe_int(row.get('Cert Target', 0)),
                    placement_target = safe_int(row.get('Placement Target', 0)),
                    naps             = safe_str(row.get('NAPS', '')),
                    nats             = safe_str(row.get('NATS', '')),
                    dbt              = safe_str(row.get('DBT', '')),
                    verify_flag      = safe_str(row.get('Verify Flag', '')),
                )
                created += 1
            self.stdout.write(f'  {created} Cert Schedule records loaded')
        except FileNotFoundError:
            self.stdout.write(f'  Skipping Cert Schedule (file not found: {cs_path})')

        # 8. Import NAPS Data (per-candidate; aggregated by SMB views per batch)
        nd_path = f'{data_dir}/NAPS_Data.xlsx'
        try:
            self.stdout.write('Importing NAPS Data...')
            NAPSData.objects.all().delete()
            nd = pd.read_excel(nd_path, sheet_name='Sheet1')
            # Strip any leading/trailing whitespace from column headers
            nd.columns = [str(c).strip() for c in nd.columns]
            created = 0
            for _, row in nd.iterrows():
                bid = safe_str(row.get('Batch ID', ''))
                if not bid:
                    continue
                NAPSData.objects.create(
                    batch_id                = bid,
                    project_name            = safe_str(row.get('Project Name(SAHI)', '')),
                    centre_name             = safe_str(row.get('Centre Name', '')),
                    centre_id               = safe_str(row.get('Centre ID', '')),
                    batch_actual_start_date = safe_date(row.get('Batch Actual Start Date')),
                    batch_actual_end_date   = safe_date(row.get('Batch Actual End Date')),
                    slab                    = safe_str(row.get('Slab', '')),
                    candidate_id            = safe_str(row.get('Candidate ID', '')),
                    course_name             = safe_str(row.get('Course Name', '')),
                    qp_name                 = safe_str(row.get('QP Name', '')),
                    naps_eligible           = safe_str(row.get('NAPS Eligible', '')),
                    estimated_revenue       = safe_int(row.get('Estimated revenue')),
                    candidate_name          = safe_str(row.get('Candidate Name', '')),
                )
                created += 1
            self.stdout.write(f'  {created} NAPSData candidate rows loaded')
        except FileNotFoundError:
            self.stdout.write(f'  Skipping NAPS Data (file not found: {nd_path})')

        # 9. Import NAPS Plan FY26-27
        np_path = f'{data_dir}/NAPS_Plan_FY26-27.xlsx'
        try:
            self.stdout.write('Importing NAPS Plan FY26-27...')
            NAPSPlan.objects.all().delete()
            npl = pd.read_excel(np_path)
            npl.columns = [str(c).strip() for c in npl.columns]
            created = 0
            for _, row in npl.iterrows():
                bid = safe_str(row.get('Batch ID', ''))
                if not bid:
                    continue
                NAPSPlan.objects.create(
                    projects_fy                  = safe_str(row.get('Projects_FY', '')),
                    batch_id                     = bid,
                    centre_name                  = safe_str(row.get('Centre Name', '')),
                    centre_id                    = safe_str(row.get('Centre ID', '')),
                    qp_name                      = safe_str(row.get('QP Name', '')),
                    naps_eligible                = safe_str(row.get('NAPS Eligible', '')),
                    sub_cluster_id               = safe_str(row.get('Sub Cluster ID', '')),
                    cluster                      = safe_str(row.get('Cluster', '')),
                    sub_cluster                  = safe_str(row.get('Sub Cluster', '')),
                    project_name                 = safe_str(row.get('Project Name(SAHI)', '')),
                    sub_project_name             = safe_str(row.get('Sub Project name', '')),
                    batch_planned_start_date     = safe_date(row.get('Batch_Planned_Start_Date')),
                    certification_start_date     = safe_date(row.get('Certification_Start_Date')),
                    placement_end_date           = safe_date(row.get('Placement_End_Date')),
                    final_enrolment_planned      = safe_int(row.get('Final Enrolment Planned')),
                    final_certification_planned  = safe_int(row.get('Final Certification Planned')),
                    final_placement_planned      = safe_float(row.get('Final Placement Planned')),
                    estimated_revenue            = safe_int(row.get('Estimated revenue')),
                )
                created += 1
            self.stdout.write(f'  {created} NAPSPlan rows loaded')
        except FileNotFoundError:
            self.stdout.write(f'  Skipping NAPS Plan (file not found: {np_path})')

        # 10. Import Outreach Hyperlocal Master (per-employer outreach status)
        oh_path = f'{data_dir}/Outreach_Hyperlocal_Master.xlsx'
        try:
            self.stdout.write('Importing Outreach Hyperlocal Master...')
            OutreachStatus.objects.all().delete()
            oh = pd.read_excel(oh_path)
            oh.columns = [str(c).strip() for c in oh.columns]
            created = 0
            for _, row in oh.iterrows():
                eid = safe_str(row.get('Discovered Employer ID', ''))
                if not eid:
                    continue
                OutreachStatus.objects.create(
                    discovered_employer      = safe_str(row.get('Discovered Employer', '')),
                    discovered_employer_id   = eid,
                    status                   = safe_str(row.get('Status', '')),
                    hr_name                  = safe_str(row.get('HR Name', '')),
                    email                    = safe_str(row.get('Email', '')),
                    hr_contact_name          = safe_str(row.get('HR Contact Name', '')),
                    number_of_open_positions = safe_int_or_none(row.get('Number of Open Positions')),
                    shortlisted              = safe_int_or_none(row.get('Shortlisted')),
                    centre_name              = safe_str(row.get('Centre Name', '')),
                    centre_id                = safe_str(row.get('Centre ID', '')),
                )
                created += 1
            self.stdout.write(f'  {created} OutreachStatus rows loaded')
        except FileNotFoundError:
            self.stdout.write(f'  Skipping Outreach Master (file not found: {oh_path})')

        self.stdout.write(self.style.SUCCESS('Import complete!'))
