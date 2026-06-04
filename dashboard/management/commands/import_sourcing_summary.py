"""
Imports the two Sourcing Summary workbooks into the database:

  data/Sourcing_Channels_Master.xlsx  →  SourcingChannelMaster
  data/Sourcing_Actual_Data.xlsx       →  SourcingActual

Both tables are fully replaced on each run (truncate + reload) so the import
is idempotent — re-running it always reflects the current Excel files exactly.
"""

import os
import pandas as pd
from django.core.management.base import BaseCommand
from dashboard.models import Centre, SourcingChannelMaster, SourcingActual


def _s(v):
    """Strip + handle NaN/None → ''."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    return str(v).strip()


def _i(v):
    """Int-or-None for nullable integer columns."""
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _norm_cols(df):
    """Trim whitespace from column headers — both Excel files have trailing
    spaces on column names like 'Community Source '."""
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    return df


class Command(BaseCommand):
    help = 'Import Sourcing Channels Master + Sourcing Actual Data Excel files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--data-dir', default='data',
            help='Directory containing the two Excel files (default: data)'
        )

    def handle(self, *args, **opts):
        data_dir = opts['data_dir']

        # ── Master: Sourcing_Channels_Master.xlsx ──────────────────────────
        master_path = os.path.join(data_dir, 'Sourcing_Channels_Master.xlsx')
        if not os.path.exists(master_path):
            self.stdout.write(self.style.WARNING(
                f'Skipping master — file not found: {master_path}'))
        else:
            self.stdout.write('Importing Sourcing Channels Master...')
            SourcingChannelMaster.objects.all().delete()
            df = _norm_cols(pd.read_excel(master_path))

            created = 0
            seen = set()
            for _, row in df.iterrows():
                src = _s(row.get('Community Source', ''))
                cat = _s(row.get('Community Category', ''))
                if not src or not cat:
                    continue
                key = (src, cat)
                if key in seen:
                    # Defensive: skip duplicate (src, cat) rows in the Excel.
                    continue
                seen.add(key)
                SourcingChannelMaster.objects.create(
                    community_source=src,
                    community_category=cat,
                )
                created += 1
            self.stdout.write(f'  {created} master rows loaded')

        # ── Actual: Sourcing_Actual_Data.xlsx ──────────────────────────────
        actual_path = os.path.join(data_dir, 'Sourcing_Actual_Data.xlsx')
        if not os.path.exists(actual_path):
            self.stdout.write(self.style.WARNING(
                f'Skipping actual — file not found: {actual_path}'))
            return

        self.stdout.write('Importing Sourcing Actual Data...')
        SourcingActual.objects.all().delete()
        df = _norm_cols(pd.read_excel(actual_path))

        # Build a centre_id → Centre cache to keep per-row lookups O(1).
        # Centre IDs in this sheet sometimes contain interior spaces
        # (e.g. "2024 0313 0914 5388") so we match by the *literal* string
        # exactly as stored on Centre.centre_id.
        centre_cache = {c.centre_id: c for c in Centre.objects.all()}

        rows_to_create = []
        unknown_centre_ids = set()
        for _, row in df.iterrows():
            cid = _s(row.get('Centre ID', ''))
            centre = centre_cache.get(cid)
            if cid and centre is None:
                unknown_centre_ids.add(cid)
            rows_to_create.append(SourcingActual(
                centre=centre,
                centre_id_raw=cid,
                centre_name=_s(row.get('Centre Name', '')),
                batch_id=_s(row.get('Batch ID', '')),
                candidate_age=_i(row.get('Candidate Age')),
                community_source=_s(row.get('Community Source', '')),
                community_category=_s(row.get('Community Category', '')),
            ))

        # bulk_create in chunks — 6k+ rows would be slow with .create() per row
        SourcingActual.objects.bulk_create(rows_to_create, batch_size=1000)
        self.stdout.write(f'  {len(rows_to_create)} candidate rows loaded')
        if unknown_centre_ids:
            self.stdout.write(self.style.WARNING(
                f'  {len(unknown_centre_ids)} Centre IDs in actual data were '
                f'not found in Centre master (data still imported, just without FK)'
            ))

        self.stdout.write(self.style.SUCCESS('Sourcing summary import complete.'))
