"""
Backfill lat/lng AND stops on existing ClusterMaster rows by re-parsing the
stored map_url.

Usage:
    python manage.py parse_cluster_coords            # parse all rows
    python manage.py parse_cluster_coords --force    # alias (same behaviour)
"""
from django.core.management.base import BaseCommand
from dashboard.models import ClusterMaster
from dashboard.management.commands.import_data import parse_lat_lng, parse_stops


class Command(BaseCommand):
    help = 'Populate ClusterMaster.lat/lng/stops from existing map_url values.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='(no-op kept for compatibility) re-parses everything.')

    def handle(self, *args, **options):
        qs = ClusterMaster.objects.all()

        total, updated, failed = 0, 0, 0
        total_stops = 0
        for row in qs:
            total += 1
            lat, lng = parse_lat_lng(row.map_url)
            stops    = parse_stops(row.map_url)
            if lat is None or lng is None:
                failed += 1
                self.stdout.write(self.style.WARNING(
                    f'  X {row.sub_cluster_id} ({row.sub_cluster}) - no coords parsed'))
                continue
            row.lat, row.lng, row.stops = lat, lng, stops
            row.save(update_fields=['lat', 'lng', 'stops'])
            updated += 1
            total_stops += len(stops)

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. Scanned {total} rows | Updated {updated} | Failed {failed}'))
        self.stdout.write(f'Total individual stops across all rows: {total_stops}')
