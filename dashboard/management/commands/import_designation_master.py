"""
Management command: import_designation_master

Loads Designation_Master.xlsx into DesignationQPMap.

Columns expected:
  Designation | Qp

Usage:
  python manage.py import_designation_master
  python manage.py import_designation_master --file=data/Designation_Master.xlsx
"""

import os
import openpyxl
from django.core.management.base import BaseCommand

from dashboard.models import DesignationQPMap


class Command(BaseCommand):
    help = 'Import Designation → QP mappings from Designation_Master.xlsx'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            default=os.path.join('data', 'Designation_Master.xlsx'),
            help='Path to Designation_Master.xlsx (default: data/Designation_Master.xlsx)',
        )

    def handle(self, *args, **options):
        path = options['file']
        self.stdout.write(f'Importing Designation Master from {path} ...')

        if not os.path.exists(path):
            self.stdout.write(self.style.WARNING(
                f'  File not found: {path} — skipping.'
            ))
            return

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active

        headers = [str(c.value).strip() if c.value else '' for c in next(ws.iter_rows(max_row=1))]

        def col(row, name):
            try:
                return row[headers.index(name)].value
            except (ValueError, IndexError):
                return None

        def _s(v):
            return str(v).strip() if v else ''

        DesignationQPMap.objects.all().delete()

        created = 0
        skipped = 0
        for row in ws.iter_rows(min_row=2):
            designation = _s(col(row, 'Designation'))
            qp          = _s(col(row, 'Qp'))
            if not designation or not qp:
                skipped += 1
                continue
            DesignationQPMap.objects.get_or_create(designation=designation, qp=qp)
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'  ✓ {created} Designation→QP mappings loaded ({skipped} rows skipped — no QP).'
        ))
