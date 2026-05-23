"""
Backfill Centre.center_status from Center Master.xlsx onto existing rows.

Usage:
    python manage.py backfill_center_status
    python manage.py backfill_center_status --data-dir other/path
"""
import os
import pandas as pd
from django.core.management.base import BaseCommand
from django.conf import settings
from dashboard.models import Centre


STATUS_COL = 'Center Status (Active/ Closed/ Going to Close)'


class Command(BaseCommand):
    help = 'Populate Centre.center_status from Center Master.xlsx.'

    def add_arguments(self, parser):
        parser.add_argument('--data-dir', default='data',
                            help='Directory holding Center Master.xlsx (default: ./data)')

    def handle(self, *args, **opts):
        data_dir = opts['data_dir']
        path = os.path.join(data_dir, 'Center Master.xlsx')
        if not os.path.exists(path):
            self.stderr.write(self.style.ERROR(f'File not found: {path}'))
            return

        df = pd.read_excel(path)
        if STATUS_COL not in df.columns:
            self.stderr.write(self.style.ERROR(
                f'Column "{STATUS_COL}" not found in {path}'))
            self.stderr.write(f'Available columns: {list(df.columns)}')
            return

        # Build {centre_id: status}
        status_by_cid = {}
        for _, row in df.iterrows():
            cid = str(row.get('Centre ID', '')).strip()
            status = row.get(STATUS_COL, '')
            if cid and pd.notna(status):
                status_by_cid[cid] = str(status).strip()

        self.stdout.write(f'Read {len(status_by_cid)} centre statuses from Center Master.xlsx')

        updated = missing = 0
        for centre in Centre.objects.all():
            new_status = status_by_cid.get(centre.centre_id, '')
            if new_status and centre.center_status != new_status:
                centre.center_status = new_status
                centre.save(update_fields=['center_status'])
                updated += 1
            elif not new_status:
                missing += 1

        # Show distribution
        from collections import Counter
        dist = Counter(Centre.objects.values_list('center_status', flat=True))

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. Updated {updated} centres · {missing} not found in Center Master'))
        self.stdout.write('\nStatus distribution:')
        for status, count in sorted(dist.items(), key=lambda x: -x[1]):
            label = status if status else '(blank)'
            self.stdout.write(f'  {label:25s} {count:4d}')
