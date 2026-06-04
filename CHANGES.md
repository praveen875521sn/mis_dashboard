# Update — Trainer Productivity + SAHI Supply Chain

## What changed

### Employability tab (replaces the old "Trainer Status" table)
The single "Trainer Status" table is **removed**. In its place there are now
two new tables, both driven by the day-wise productivity sheets:

1. **📋 Attendance Performance** — row per (Batch × Trainer):
   `Batch ID | Centre | QP | Trainer | Enrolled | day-wise Present | Total Present | Days | Present %`
   * Source: `Trainer_productivity_present.xlsx`
   * `Present %` = average daily attendance across days the class was held
     (i.e. `Total Present ÷ (Enrolled × Days Held) × 100`).

2. **⏱️ Trainer Productivity Duration** — row per (Batch × Trainer):
   `Batch ID | Centre | QP | Trainer | day-wise Hours | Total Hrs | Days`
   * Source: `Trainer_productivity_duration.xlsx`
   * Excel-time cells (`2:00`, `3:00`, etc.) are converted to decimal hours.

Both tables share the same day columns (May 1 – 20 in the supplied data).
Centre scoping (BU/TM/Project/Centre filters on Employability, and the
individual centre on the Centre Detail page) is respected.

The **📣 Mobilizer Status** table is unchanged.

### SAHI tab (two new tables after "🎓 Diploma Colleges…")

3. **🧭 Supply Summary — Associates by State, District & Client**
   `Supply State | Supply District | Client | Gender | Count`
   * Join: `SAHI_Demand_Master.Sub Cluster ID` →
     `Associate_data.Sub Cluster ID` (group by state/district/client/gender).

4. **🏛️ Supply Chain — ITI & Polytechnic Colleges (by Supply PIN)**
   `Institution Name | Type | Address / Location | Supply PIN`
   * Join: `… → Associate_data.Supply PIN` →
     `ITI_Polytechnic_Colleges_by_PIN.Supply PIN`.

Both new SAHI tables react to the existing Cluster / Sub Cluster dropdowns.

### Trainer_Target is fully retired
* `data/Trainer_Target.xlsx` deleted.
* `import_targets` no longer loads it (only Mobiliser remains).
* `TrainerTarget` / `TrainerTargetDay` models are kept in the schema for
  migration history but are no longer populated or queried.

## New files

```
data/Trainer_productivity_present.xlsx
data/Trainer_productivity_duration.xlsx
data/Associate_data.xlsx
data/ITI_Polytechnic_Colleges_by_PIN_Supply.xlsx
dashboard/management/commands/import_productivity_supply.py
dashboard/migrations/0018_productivity_associate_iti.py
```

## New models

```
TrainerProductivityPresent  + TrainerProductivityPresentDay   (attendance)
TrainerProductivityDuration + TrainerProductivityDurationDay  (hours)
AssociateData                                                  (supply candidates)
ITIPolytechnicByPIN                                            (institution directory)
```

## New API endpoints

```
GET /api/sahi/supply-summary/?cluster=…&sub_cluster=…
GET /api/sahi/iti-polytechnic/?cluster=…&sub_cluster=…
```

## How to re-run from scratch

```bash
python manage.py migrate
python manage.py import_all                   # main + staffing + sahi + targets + productivity
# OR just the new phase:
python manage.py import_productivity_supply
```

`import_all` now has a 5th phase `productivity`; flags `--only productivity`
and `--skip-productivity` are available.
