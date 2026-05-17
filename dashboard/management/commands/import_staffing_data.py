"""
Management command: import_staffing_data
Usage:
  python manage.py import_staffing_data \
      --demand /path/to/Demand_Master.xlsx \
      --iti    /path/to/ITI___Diploma_Master.xlsx \
      --our    /path/to/Our_ITI_Collage.xlsx

Each flag is optional — omit any file you don't want to reimport.
Re-running clears & reloads the respective table each time.
"""

import openpyxl
from django.core.management.base import BaseCommand

from dashboard.models import (
    Centre, DemandSupply, ITIDiplomaMaster, SFInterventionCollege
)


def _safe_str(val):
    if val is None:
        return ''
    return str(val).strip()


def _safe_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _resolve_centre(centre_id_str):
    """Return a Centre FK or None, trying each space-separated token as centre_id."""
    if not centre_id_str:
        return None
    # The centre_id field in Excel may contain multiple IDs or the actual ID
    cid = centre_id_str.strip()
    try:
        return Centre.objects.get(centre_id=cid)
    except Centre.DoesNotExist:
        return None


class Command(BaseCommand):
    help = 'Import Staffing tab data: Demand/Supply, ITI Diploma Master, Our ITI Colleges'

    def add_arguments(self, parser):
        parser.add_argument('--demand', type=str, help='Path to Demand_Master.xlsx')
        parser.add_argument('--iti', type=str, help='Path to ITI___Diploma_Master.xlsx')
        parser.add_argument('--our', type=str, help='Path to Our_ITI_Collage.xlsx')

    def handle(self, *args, **options):
        if options['demand']:
            self._import_demand(options['demand'])
        if options['iti']:
            self._import_iti(options['iti'])
        if options['our']:
            self._import_our(options['our'])
        self.stdout.write(self.style.SUCCESS('Staffing data import complete.'))

    # ── Demand / Supply ───────────────────────────────────────────────────────
    def _import_demand(self, path):
        self.stdout.write(f'Importing Demand/Supply from {path} ...')
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            self.stdout.write('  Empty file — skipping.')
            return

        # Skip header row
        DemandSupply.objects.all().delete()
        created = 0
        for row in rows[1:]:
            if not any(row):
                continue
            # Columns (0-indexed):
            # 0  New/Existing   1 Region   2 City/Location   3 Industrial Estate/Cluster
            # 4  Existing Client  5 Std Designation  6 Est Monthly Demand
            # 7  Nearest Center  8 Centre ID  9 Center Address
            # 10 Training Program Match  11 Est Monthly Supply  12 NAPS/NATS
            # 13 Nearest ITI  14 Distance  15 ITI Trade Match
            centre_id_val = _safe_str(row[8]) if len(row) > 8 else ''
            centre_obj = _resolve_centre(centre_id_val)

            DemandSupply.objects.create(
                new_existing=_safe_str(row[0]) if len(row) > 0 else '',
                region=_safe_str(row[1]) if len(row) > 1 else '',
                city_location=_safe_str(row[2]) if len(row) > 2 else '',
                industrial_estate_cluster=_safe_str(row[3]) if len(row) > 3 else '',
                existing_client=_safe_str(row[4]) if len(row) > 4 else '',
                std_designation=_safe_str(row[5]) if len(row) > 5 else '',
                estimated_monthly_demand=_safe_int(row[6]) if len(row) > 6 else None,
                nearest_center=_safe_str(row[7]) if len(row) > 7 else '',
                centre_id_ref=centre_id_val,
                center_address=_safe_str(row[9]) if len(row) > 9 else '',
                training_program_match=_safe_str(row[10]) if len(row) > 10 else '',
                estimated_monthly_supply=_safe_int(row[11]) if len(row) > 11 else None,
                training_program_naps_nats=_safe_str(row[12]) if len(row) > 12 else '',
                nearest_iti=_safe_str(row[13]) if len(row) > 13 else '',
                distance_from_center=_safe_str(row[14]) if len(row) > 14 else '',
                iti_trade_match=_safe_str(row[15]) if len(row) > 15 else '',
                centre=centre_obj,
            )
            created += 1
        self.stdout.write(f'  ✓ {created} DemandSupply records created.')

    # ── ITI & Diploma Master ──────────────────────────────────────────────────
    def _import_iti(self, path):
        self.stdout.write(f'Importing ITI/Diploma Master from {path} ...')
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            self.stdout.write('  Empty file — skipping.')
            return

        ITIDiplomaMaster.objects.all().delete()
        created = 0
        for row in rows[1:]:
            if not any(row):
                continue
            # Columns: 0 S.No  1 College Name  2 Type  3 Address  4 Rating
            #          5 Phone  6 Working Hours  7 Website/Map
            #          8 Centre ID (numeric-ish)  9 Centre Name  10 Centre ID (dup)
            centre_id_val = _safe_str(row[8]) if len(row) > 8 else ''
            centre_name_val = _safe_str(row[9]) if len(row) > 9 else ''
            centre_obj = _resolve_centre(centre_id_val)

            ITIDiplomaMaster.objects.create(
                sno=_safe_int(row[0]),
                college_name=_safe_str(row[1]) if len(row) > 1 else '',
                college_type=_safe_str(row[2]) if len(row) > 2 else '',
                address=_safe_str(row[3]) if len(row) > 3 else '',
                rating=_safe_str(row[4]) if len(row) > 4 else '',
                phone_number=_safe_str(row[5]) if len(row) > 5 else '',
                working_hours=_safe_str(row[6]) if len(row) > 6 else '',
                website_map=_safe_str(row[7]) if len(row) > 7 else '',
                centre_id_ref=centre_id_val,
                centre_name=centre_name_val,
                centre=centre_obj,
            )
            created += 1
        self.stdout.write(f'  ✓ {created} ITIDiplomaMaster records created.')

    # ── SF Intervention / Our ITI Colleges ───────────────────────────────────
    def _import_our(self, path):
        self.stdout.write(f'Importing Our ITI Colleges from {path} ...')
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            self.stdout.write('  Empty file — skipping.')
            return

        SFInterventionCollege.objects.all().delete()
        created = 0
        for row in rows[1:]:
            if not any(row):
                continue
            # Columns: 0 Name Of College  1 Address  2 Project Name  3 QP
            #          4 Centre ID  5 Centre Name
            centre_id_val = _safe_str(row[4]) if len(row) > 4 else ''
            centre_name_val = _safe_str(row[5]) if len(row) > 5 else ''
            centre_obj = _resolve_centre(centre_id_val)

            SFInterventionCollege.objects.create(
                name_of_college=_safe_str(row[0]) if len(row) > 0 else '',
                address=_safe_str(row[1]) if len(row) > 1 else '',
                project_name=_safe_str(row[2]) if len(row) > 2 else '',
                qp=_safe_str(row[3]) if len(row) > 3 else '',
                centre_id_ref=centre_id_val,
                centre_name=centre_name_val,
                centre=centre_obj,
            )
            created += 1
        self.stdout.write(f'  ✓ {created} SFInterventionCollege records created.')
