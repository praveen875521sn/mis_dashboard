"""
Import batch-level candidate sourcing data (Actual + Target).

Files (in data/):
  1. Sourcing_Channels_Master.xlsx            → SourcingChannelMaster
       Columns: Community Source | Community Category
  2. Candidate_Sourcing_Channels_Complete.xlsx → SourcingComplete   (ACTUAL)
       Columns: Batch ID (Complete) | Candidate Count | Sourcing Channels Type |
                Sourcing Channels Details | Sourcing Channels Name | SPOC Name |
                SPOC Contact No. | Location | Remarks
  3. Candidate_Sourcing_Channels_Target.xlsx   → SourcingTarget     (TARGET)
       Wide format: Batch ID + one numeric column per Community Category.
       Each category column is mapped back to its Community Source via the master.

Usage:  python manage.py import_batch_sourcing
"""
import os

import pandas as pd
from django.core.management.base import BaseCommand

from dashboard.models import SourcingChannelMaster, SourcingComplete, SourcingTarget


def _s(v):
    """Safe string: None/NaN → ''. Strips whitespace."""
    if v is None:
        return ''
    if isinstance(v, float) and v != v:  # NaN
        return ''
    return str(v).strip()


def _i(v):
    try:
        if v is None or (isinstance(v, float) and v != v):
            return 0
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _f(v):
    try:
        if v is None or (isinstance(v, float) and v != v):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class Command(BaseCommand):
    help = 'Import Sourcing Channels Master + Complete (actual) + Target data'

    def handle(self, *args, **options):
        data_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'data')

        # ── 1. Master: Community Source → Category ──────────────────────────
        self.stdout.write('Importing Sourcing_Channels_Master.xlsx...')
        mdf = pd.read_excel(f'{data_dir}/Sourcing_Channels_Master.xlsx')
        mdf.columns = mdf.columns.str.strip()

        SourcingChannelMaster.objects.all().delete()
        cat_to_source = {}     # lowercased category → canonical source
        for _, row in mdf.iterrows():
            src = _s(row.get('Community Source'))
            cat = _s(row.get('Community Category'))
            if not src or not cat:
                continue
            SourcingChannelMaster.objects.get_or_create(
                community_source=src, community_category=cat)
            cat_to_source[cat.lower()] = src
        self.stdout.write(
            f'  {SourcingChannelMaster.objects.count()} master rows loaded')

        # ── 2. Complete (Actual): one row per Batch × Channel ───────────────
        self.stdout.write('Importing Candidate_Sourcing_Channels_Complete.xlsx...')
        cdf = pd.read_excel(f'{data_dir}/Candidate_Sourcing_Channels_Complete.xlsx')
        cdf.columns = cdf.columns.str.strip()

        SourcingComplete.objects.all().delete()
        rows = []
        for _, row in cdf.iterrows():
            bid = _s(row.get('Batch ID (Complete)'))
            if not bid:
                continue
            cat = _s(row.get('Sourcing Channels Details'))
            # Prefer the master taxonomy for Category → Source; fall back to
            # the file's own 'Sourcing Channels Type' when the category is
            # unknown to the master.
            src = cat_to_source.get(cat.lower()) or _s(row.get('Sourcing Channels Type'))
            rows.append(SourcingComplete(
                batch_id=bid,
                candidate_count=_i(row.get('Candidate Count')),
                community_source=src,
                community_category=cat,
                channel_name=_s(row.get('Sourcing Channels Name')),
                spoc_name=_s(row.get('SPOC Name')),
                spoc_contact=_s(row.get('SPOC Contact No.')).removesuffix('.0'),
                location=_s(row.get('Location')),
                remarks=_s(row.get('Remarks')),
            ))
        SourcingComplete.objects.bulk_create(rows)
        self.stdout.write(f'  {len(rows)} actual sourcing rows loaded')

        # ── 3. Target (wide → long) ──────────────────────────────────────────
        self.stdout.write('Importing Candidate_Sourcing_Channels_Target.xlsx...')
        tdf = pd.read_excel(f'{data_dir}/Candidate_Sourcing_Channels_Target.xlsx')
        tdf.columns = tdf.columns.str.strip()

        SourcingTarget.objects.all().delete()
        cat_cols = [c for c in tdf.columns if c != 'Batch ID']
        unmapped = sorted({c for c in cat_cols if c.lower() not in cat_to_source})
        if unmapped:
            self.stdout.write(self.style.WARNING(
                f'  Categories in Target file missing from master '
                f'(imported with blank source): {unmapped}'))

        trows = []
        for _, row in tdf.iterrows():
            bid = _s(row.get('Batch ID'))
            if not bid:
                continue
            for cat in cat_cols:
                val = _f(row.get(cat))
                if val == 0:
                    continue           # keep the table sparse
                trows.append(SourcingTarget(
                    batch_id=bid,
                    community_source=cat_to_source.get(cat.lower(), ''),
                    community_category=cat,
                    target_count=val,
                ))
        SourcingTarget.objects.bulk_create(trows)
        self.stdout.write(f'  {len(trows)} target sourcing rows loaded')

        self.stdout.write(self.style.SUCCESS('Batch sourcing import complete.'))
