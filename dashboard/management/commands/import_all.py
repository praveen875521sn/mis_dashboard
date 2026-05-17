"""
Management command: import_all
Runs all data import commands in order.

Usage:
  python manage.py import_all
  python manage.py import_all --only sahi
  python manage.py import_all --skip-targets
"""

import os
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Run all data import commands in one go.'

    def add_arguments(self, parser):
        parser.add_argument('--data-dir', default='data')
        parser.add_argument(
            '--only',
            choices=['main', 'staffing', 'sahi', 'targets'],
            help='Run only one phase.'
        )
        parser.add_argument('--skip-main',     action='store_true')
        parser.add_argument('--skip-staffing', action='store_true')
        parser.add_argument('--skip-sahi',     action='store_true')
        parser.add_argument('--skip-targets',  action='store_true')

    def handle(self, *args, **options):
        data_dir = options['data_dir']
        only     = options['only']

        run_main     = (only is None or only == 'main')     and not options['skip_main']
        run_staffing = (only is None or only == 'staffing') and not options['skip_staffing']
        run_sahi     = (only is None or only == 'sahi')     and not options['skip_sahi']
        run_targets  = (only is None or only == 'targets')  and not options['skip_targets']

        steps = []
        if run_main:     steps.append('main')
        if run_staffing: steps.append('staffing')
        if run_sahi:     steps.append('sahi')
        if run_targets:  steps.append('targets')
        if not steps:
            raise CommandError('Nothing to do — all phases were skipped.')

        self.stdout.write(self.style.NOTICE(
            f'Importing data ({", ".join(steps)}) from "{data_dir}/" ...\n'
        ))

        # 1. Main
        if run_main:
            self._heading('1/4  Main data — import_data')
            call_command('import_data', f'--data-dir={data_dir}')

        # 2. Staffing
        if run_staffing:
            self._heading('2/4  Staffing data — import_staffing_data')
            staffing_args = []
            for flag, fname in [
                ('--demand', 'Demand_Master.xlsx'),
                ('--iti',    'ITI___Diploma_Master.xlsx'),
                ('--our',    'Our_ITI_Collage.xlsx'),
            ]:
                path = os.path.join(data_dir, fname)
                if os.path.exists(path):
                    staffing_args += [f'{flag}={path}']
                else:
                    self.stdout.write(self.style.WARNING(
                        f'  (skipping {fname} — file not found in {data_dir}/)'
                    ))
            if staffing_args:
                call_command('import_staffing_data', *staffing_args)
            else:
                self.stdout.write(self.style.WARNING(
                    '  No staffing files found — phase skipped.'
                ))

        # 3. SAHI
        if run_sahi:
            self._heading('3/4  SAHI data — import_sahi_main_data')
            call_command(
                'import_sahi_main_data',
                f'--demand={data_dir}/SAHI_Demand_Master.xlsx',
            )

        # 4. Targets (Mobiliser + Trainer)
        if run_targets:
            self._heading('4/4  Target data — import_targets')
            call_command('import_targets', f'--data-dir={data_dir}')

        self.stdout.write(self.style.SUCCESS('\n✓ All requested imports complete.'))

    def _heading(self, text):
        bar = '─' * 70
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{bar}\n{text}\n{bar}'))
