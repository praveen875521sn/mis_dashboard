# MIS Dashboard — Cluster Impact Map (v3)

This is the full project with the Cluster Impact Map fully tuned to your specs.

## What's new in v3

1. **Active / Inactive removed.** All markers are green. No status pills.
2. **Multi-location sub-clusters now plot every stop.** Sub-clusters whose
   Google Maps URL contains multiple waypoints (35 of the 86, e.g. Bangalore
   Whitefield/Hoskote Belt) get one green marker per location. Total: 164
   markers across 86 sub-clusters.
3. **Simplified popup.** Just shows sub-cluster name + cluster + state + a
   Google Maps link. No centre count, no status.
4. **Header badges now read** "86 sub-clusters · 164 locations".

## Run

```powershell
# 1. Apply migrations
python manage.py migrate

# 2. Backfill cluster coordinates AND stops onto existing rows
python manage.py parse_cluster_coords

# 3. (Optional, only if you want centre status stored for other uses)
python manage.py backfill_center_status

# 4. Start
python manage.py runserver
```

The bundled `db.sqlite3` already has migrations applied and stops backfilled
— you can skip straight to `runserver`.

## Files changed since your original project

| File | Change |
|---|---|
| `dashboard/models.py` | `ClusterMaster.lat/lng/stops`, `Centre.center_status` |
| `dashboard/migrations/0014_clustermaster_lat_lng.py` | (new) |
| `dashboard/migrations/0015_centre_center_status.py` | (new) |
| `dashboard/migrations/0016_clustermaster_stops.py` | (new) |
| `dashboard/management/commands/import_data.py` | Coord + stops parser, centre status loading |
| `dashboard/management/commands/parse_cluster_coords.py` | (new) backfills lat/lng AND stops |
| `dashboard/management/commands/backfill_center_status.py` | (new) backfills centre status |
| `dashboard/views.py` | `cluster_map_data_api` returns `locations: [[lat,lng], ...]` per row |
| `dashboard/urls.py` | One new route |
| `templates/dashboard/home.html` | Map card, multi-marker rendering, green-only |

## Verified results

| Filter | Sub-clusters | Locations |
|---|---|---|
| (no filter) | 86 | 164 |
| `?cluster=Bangalore` | 6 | 23 |
| `?cluster=Bangalore&sub_cluster=Bangalore East – Whitefield / Hoskote Belt` | 1 | 4 |

The Bangalore Whitefield/Hoskote sub-cluster now correctly produces 4 markers:
Hoskote Industrial Area, Hoskote, Whitefield, and Mahadevapura — matching the
Google Maps route in your reference screenshot.

## Notes

- All markers within the same sub-cluster share the same popup (so clicking
  any of the 4 Whitefield/Hoskote pins shows the same sub-cluster info).
- Sub-clusters without explicit stops in the URL (single-place URLs, 51 of
  the 86) still get one marker at their `@lat,lng` center — unchanged behavior.
- The `Centre.center_status` field is still populated for future use, but no
  longer drives anything on the map.
