"""
Management command: import_targets
Loads Mobilsier_Target.xlsx and Trainer_Target.xlsx into the DB.
Uses column-NAME lookup instead of fixed indices — robust against new columns
being inserted (e.g. Centre ID was added between earlier columns).

Usage:
  python manage.py import_targets
  python manage.py import_targets --data-dir data
"""

import os

import openpyxl
from django.core.management.base import BaseCommand

from dashboard.models import MobiliserTarget


def _s(v):
    return '' if v is None else str(v).strip()


def _i(v):
    try:
        if v is None or v == '':
            return 0
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _normalize(name):
    """Lower-case, collapse whitespace, strip — for header matching."""
    return ' '.join(_s(name).lower().split())


def _idx(headers, *candidates):
    """Return the index of the first matching header (case/space-insensitive)."""
    norm = [_normalize(h) for h in headers]
    for cand in candidates:
        c = _normalize(cand)
        for i, h in enumerate(norm):
            if h == c:
                return i
    return None


def _month_label_from_header(header):
    """' May'26 E Target' → 'May'26'"""
    s = _s(header)
    for suf in (' E Target', ' C Target', ' P Target', ' E Act'):
        if s.lower().endswith(suf.lower()):
            return s[: -len(suf)].strip()
    return s.strip()


class Command(BaseCommand):
    help = 'Import Mobiliser & Trainer target Excel files.'

    def add_arguments(self, parser):
        parser.add_argument('--data-dir', default='data')

    def handle(self, *args, **options):
        data_dir = options['data_dir']

        mob_path = os.path.join(data_dir, 'Mobilsier_Target.xlsx')

        if os.path.exists(mob_path):
            self._import_mobiliser(mob_path)
        else:
            self.stdout.write(self.style.WARNING(f'  (Mobilsier_Target.xlsx not found in {data_dir}/)'))

        # NOTE: Trainer_Target.xlsx is no longer loaded here.
        # Trainer-level data now comes from Trainer_productivity_present.xlsx
        # and Trainer_productivity_duration.xlsx via the
        # `import_productivity_supply` command.

        self.stdout.write(self.style.SUCCESS('Target data import complete.'))

    # ── Mobiliser ────────────────────────────────────────────────────────────
    def _import_mobiliser(self, path):
        self.stdout.write(f'Importing Mobiliser Target from {path} ...')
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            self.stdout.write('  Empty file — skipping.'); return

        headers = rows[0]
        # Column-name lookup (tolerant of new columns, re-ordering, etc.)
        ix = {
            'projects_fy':  _idx(headers, 'Projects_FY'),
            'project':      _idx(headers, 'Project Name(SAHI)', 'Project Name (SAHI)', 'Project Name'),
            'mob_id':       _idx(headers, 'Mobilsier ID', 'Mobiliser ID'),
            'mob_id2':      _idx(headers, 'Mobilsier ID.1', 'Mobiliser ID.1'),
            'center':       _idx(headers, 'SAHI Center Name', 'Center Name'),
            'centre_id':    _idx(headers, 'Centre ID', 'Center ID'),
            'batch':        _idx(headers, 'Batch ID'),
            'mob_name':     _idx(headers, 'Mobilsier', 'Mobiliser'),
        }
        # Find the E/C/P Target + E Act columns by suffix (handles any month label)
        e_target_idx = c_target_idx = p_target_idx = e_act_idx = None
        for i, h in enumerate(headers):
            hl = _normalize(h)
            if hl.endswith('e target'): e_target_idx = i
            elif hl.endswith('c target'): c_target_idx = i
            elif hl.endswith('p target'): p_target_idx = i
            elif hl.endswith('e act'):    e_act_idx    = i

        e_target_label = _month_label_from_header(
            headers[e_target_idx]) if e_target_idx is not None else ''

        # Surface what was resolved (useful when files change again)
        self.stdout.write(f'  Header map: '
                          f'mob_id@{ix["mob_id"]}, mob_name@{ix["mob_name"]}, '
                          f'batch@{ix["batch"]}, center@{ix["center"]}, '
                          f'E@{e_target_idx}, C@{c_target_idx}, P@{p_target_idx}, EAct@{e_act_idx}, '
                          f'label="{e_target_label}"')

        def get(row, key):
            i = ix.get(key)
            return row[i] if (i is not None and i < len(row)) else None

        MobiliserTarget.objects.all().delete()
        created = 0
        for row in rows[1:]:
            if not any(row):
                continue
            mid = _i(get(row, 'mob_id'))
            if not mid:
                mid = _i(row[ix['mob_id2']] if ix['mob_id2'] is not None and ix['mob_id2'] < len(row) else None)

            MobiliserTarget.objects.create(
                projects_fy        = _s(get(row, 'projects_fy')),
                project_name_sahi  = _s(get(row, 'project')),
                mobiliser_id       = mid,
                sahi_center_name   = _s(get(row, 'center')),
                batch_id           = _s(get(row, 'batch')),
                mobiliser_name     = _s(get(row, 'mob_name')),
                e_target           = _i(row[e_target_idx]) if e_target_idx is not None and e_target_idx < len(row) else 0,
                c_target           = _i(row[c_target_idx]) if c_target_idx is not None and c_target_idx < len(row) else 0,
                p_target           = _i(row[p_target_idx]) if p_target_idx is not None and p_target_idx < len(row) else 0,
                e_act              = _i(row[e_act_idx])    if e_act_idx    is not None and e_act_idx    < len(row) else 0,
                target_month_label = e_target_label,
            )
            created += 1
        self.stdout.write(f'  ✓ {created} MobiliserTarget rows '
                          f'(month label: "{e_target_label}").')

