"""
Management command: import_sahi_main_data
Usage:
  python manage.py import_sahi_main_data \
      --demand /path/to/SAHI_Demand_Master.xlsx

Re-running clears & reloads the SAHIDemand table.

Files schema:
  SAHI_Demand_Master.xlsx (13 cols):
    Sub Cluster ID | Cluster | Sub Cluster | Region | Zone | Existing/Potential |
    Demand City | Location | Existing Client | Client Nature |
    Designation | HC | Monthly Demand

NOTE: SAHI_Cluster_Map.xlsx is no longer imported. Center Master.xlsx now
carries Sub Cluster ID / Cluster / Sub Cluster directly, so the bridge
between SAHI demand and Centres goes through those shared columns.
"""

import pandas as pd
from django.core.management.base import BaseCommand

from dashboard.models import SAHIDemand


def _safe_str(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    return str(val).strip()


def _safe_int(val):
    try:
        if val is None or val == '' or (isinstance(val, float) and pd.isna(val)):
            return None
        return int(float(val))
    except (TypeError, ValueError):
        return None


class Command(BaseCommand):
    help = 'Import SAHI module data: SAHI_Demand_Master.xlsx'

    def add_arguments(self, parser):
        parser.add_argument('--demand', type=str, help='Path to SAHI_Demand_Master.xlsx')

    def handle(self, *args, **options):
        if options['demand']:
            self._import_demand(options['demand'])
        self.stdout.write(self.style.SUCCESS('SAHI main data import complete.'))

    # ── SAHI Demand Master ───────────────────────────────────────────────────
    def _import_demand(self, path):
        self.stdout.write(f'Importing SAHI Demand Master from {path} ...')
        try:
            df = pd.read_excel(path)
        except FileNotFoundError:
            self.stdout.write(self.style.WARNING(f'  File not found: {path} — skipping.'))
            return

        if df.empty:
            self.stdout.write('  Empty file — skipping.')
            return

        # Tolerant column resolver (raw column names from the new file)
        def col(row, *names):
            for n in names:
                if n in row.index:
                    return row[n]
            return None

        SAHIDemand.objects.all().delete()
        created = 0
        for _, row in df.iterrows():
            # Skip blank rows
            if not any(_safe_str(row.get(c, '')) for c in df.columns):
                continue
            SAHIDemand.objects.create(
                sub_cluster_id     = _safe_str(col(row, 'Sub Cluster ID')),
                cluster            = _safe_str(col(row, 'Cluster')),
                sub_cluster        = _safe_str(col(row, 'Sub Cluster')),
                region             = _safe_str(col(row, 'Region')),
                zone               = _safe_str(col(row, 'Zone')),
                existing_potential = _safe_str(col(row, 'Existing/Potential')),
                demand_city        = _safe_str(col(row, 'Demand City')),
                location           = _safe_str(col(row, 'Location')),
                existing_client    = _safe_str(col(row, 'Existing Client')),
                client_nature      = _safe_str(col(row, 'Client Nature')),
                designation        = _safe_str(col(row, 'Designation')),
                hc                 = _safe_int(col(row, 'HC')),
                monthly_demand     = _safe_int(col(row, 'Monthly Demand')),
            )
            created += 1
        self.stdout.write(f'  ✓ {created} SAHIDemand records created.')
