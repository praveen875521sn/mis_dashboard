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
            choices=['main', 'staffing', 'sahi', 'designation', 'worksetu', 'targets', 'productivity'],
            help='Run only one phase.'
        )
        parser.add_argument('--skip-main',         action='store_true')
        parser.add_argument('--skip-staffing',     action='store_true')
        parser.add_argument('--skip-sahi',         action='store_true')
        parser.add_argument('--skip-designation',  action='store_true')
        parser.add_argument('--skip-worksetu',     action='store_true')
        parser.add_argument('--skip-targets',      action='store_true')
        parser.add_argument('--skip-productivity', action='store_true')

    def handle(self, *args, **options):
        data_dir = options['data_dir']
        only     = options['only']

        run_main         = (only is None or only == 'main')         and not options['skip_main']
        run_staffing     = (only is None or only == 'staffing')     and not options['skip_staffing']
        run_sahi         = (only is None or only == 'sahi')         and not options['skip_sahi']
        run_desig        = (only is None or only == 'designation')  and not options.get('skip_designation', False)
        run_worksetu     = (only is None or only == 'worksetu')      and not options.get('skip_worksetu', False)
        run_targets      = (only is None or only == 'targets')      and not options['skip_targets']
        run_productivity = (only is None or only == 'productivity') and not options['skip_productivity']

        steps = []
        if run_main:         steps.append('main')
        if run_staffing:     steps.append('staffing')
        if run_sahi:         steps.append('sahi')
        if run_desig:        steps.append('designation')
        if run_worksetu:     steps.append('worksetu')
        if run_targets:      steps.append('targets')
        if run_productivity: steps.append('productivity')
        if not steps:
            raise CommandError('Nothing to do — all phases were skipped.')

        self.stdout.write(self.style.NOTICE(
            f'Importing data ({", ".join(steps)}) from "{data_dir}/" ...\n'
        ))

        total = len(steps)
        idx = 0

        # 1. Main
        if run_main:
            idx += 1
            self._heading(f'{idx}/{total}  Main data — import_data')
            call_command('import_data', f'--data-dir={data_dir}')

        # 2. Staffing
        if run_staffing:
            idx += 1
            self._heading(f'{idx}/{total}  Staffing data — import_staffing_data')
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
            idx += 1
            self._heading(f'{idx}/{total}  SAHI data — import_sahi_main_data')
            call_command(
                'import_sahi_main_data',
                f'--demand={data_dir}/SAHI_Demand_Master.xlsx',
            )

        # 4. Designation Master (Designation → QP mapping)
        if run_desig:
            idx += 1
            self._heading(f'{idx}/{total}  Designation Master — import_designation_master')
            desig_path = os.path.join(data_dir, 'Designation_Master.xlsx')
            if os.path.exists(desig_path):
                call_command('import_designation_master', f'--file={desig_path}')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  (skipping Designation_Master.xlsx — file not found in {data_dir}/)'
                ))

        # 5. WorkSetu PIN Map
        if run_worksetu:
            idx += 1
            self._heading(f'{idx}/{total}  WorkSetu PIN Map — import_worksetu')
            ws_path = os.path.join(data_dir, 'Supply_WorkSetu_Sub_Cluster.xlsx')
            if os.path.exists(ws_path):
                call_command('import_worksetu', f'--file={ws_path}')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  (skipping Supply_WorkSetu_Sub_Cluster.xlsx — file not found in {data_dir}/)'
                ))

        # 6. Targets (Mobiliser only now — Trainer_Target.xlsx is deprecated,
        #     replaced by Trainer_productivity_present/duration in the
        #     "productivity" phase below.)
        if run_targets:
            idx += 1
            self._heading(f'{idx}/{total}  Target data — import_targets')
            call_command('import_targets', f'--data-dir={data_dir}')

        # 5. Productivity + Supply chain (new)
        if run_productivity:
            idx += 1
            self._heading(f'{idx}/{total}  Productivity & Supply — import_productivity_supply')
            call_command('import_productivity_supply', f'--data-dir={data_dir}')

        self.stdout.write(self.style.SUCCESS('\n✓ All requested imports complete.'))

    def _heading(self, text):
        bar = '─' * 70
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{bar}\n{text}\n{bar}'))
