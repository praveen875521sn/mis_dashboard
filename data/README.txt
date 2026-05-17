Place all Excel data files in this folder before running the import commands.

═══════════════════════════════════════════════
STEP 1 — Import Employability tab data
═══════════════════════════════════════════════
Command:
    python manage.py import_data

Required files:
  - Ops_Team.xlsx
  - Batch_Plan.xlsx
  - ECPv1xl.xlsx
  - Manpower_Master_1.xlsx
  - Community____Colleges.xlsx
  - Hyperlocal_jobs.xlsx

═══════════════════════════════════════════════
STEP 2 — Import Staffing tab data
═══════════════════════════════════════════════
Command:
    python manage.py import_staffing_data \
        --demand data/Demand_Master.xlsx \
        --iti    data/ITI___Diploma_Master.xlsx \
        --our    data/Our_ITI_Collage.xlsx

Required files (already present in this folder):
  - Demand_Master.xlsx          → Table 1 (Demand) + Table 2 (Supply/Centre)
  - ITI___Diploma_Master.xlsx   → Table 3 (ITI & Diploma colleges)
  - Our_ITI_Collage.xlsx        → Table 4 (SF Intervention / Our ITI Colleges)

Notes:
  - Each --flag is optional. Omit any file you don't want to reimport.
  - Re-running clears and reloads the respective table each time.
  - Run from the project root (same folder as manage.py).
