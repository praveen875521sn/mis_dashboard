from django.db import models


class Centre(models.Model):
    centre_id      = models.CharField(max_length=100, unique=True)
    centre_name    = models.CharField(max_length=255)
    bu_head        = models.CharField(max_length=255, null=True, blank=True)
    pmt_lead       = models.CharField(max_length=255, null=True, blank=True)
    tm_name        = models.CharField(max_length=255, null=True, blank=True)
    sub_cluster_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    cluster        = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    sub_cluster    = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    state          = models.CharField(max_length=100, blank=True, db_index=True)  # Centre's physical state (Center Master)
    entity         = models.CharField(max_length=50,  null=True, blank=True)
    # From "Center Status (Active/ Closed/ Going to Close)" column in Center Master.xlsx
    # Common values: "Active", "Opeing Shortly", "Closing Shortly" (note typo in source data)
    center_status  = models.CharField(max_length=50, blank=True, db_index=True)

    def __str__(self):
        return self.centre_name


class NapsEligible(models.Model):
    qp                   = models.CharField(max_length=500, blank=True)
    naps_eligible        = models.CharField(max_length=10,  blank=True)
    course_name          = models.CharField(max_length=500, blank=True)
    course_type          = models.CharField(max_length=100, blank=True)
    sector               = models.CharField(max_length=255, blank=True)
    minimum_qualification= models.CharField(max_length=255, blank=True)
    on_job_training      = models.CharField(max_length=100, blank=True)
    qp_mapped            = models.CharField(max_length=10,  blank=True)
    # NAPS / NATS alignment flags (from NAPS Eligible.xlsx)
    naps_aligned         = models.CharField(max_length=10,  blank=True)
    nats_aligned         = models.CharField(max_length=10,  blank=True)

    def __str__(self):
        return self.qp


class BatchPlan(models.Model):
    """
    Single source of truth for Employability analytics.
    Source: Batch_Plan_New.xlsx (each row = one Batch × Centre × QP).
    Replaces the old Batch_Plan.xlsx + ECPv1xl.xlsx combo.
    """
    batch_id     = models.CharField(max_length=100, unique=True)
    centre       = models.ForeignKey(Centre, on_delete=models.CASCADE, to_field='centre_id')
    centre_name  = models.CharField(max_length=255)
    qp           = models.CharField(max_length=255)
    project_name = models.CharField(max_length=255, blank=True)        # Project Name (SAHI)
    sub_project_name = models.CharField(max_length=255, blank=True)
    projects_fy  = models.CharField(max_length=100, blank=True)        # Projects_FY column

    # Planned dates
    batch_planned_start_date         = models.DateField(null=True, blank=True)
    batch_planned_end_date           = models.DateField(null=True, blank=True)   # legacy / unused now
    certification_planned_start_date = models.DateField(null=True, blank=True)
    placement_planned_end_date       = models.DateField(null=True, blank=True)

    # Actual dates (drive month-on-month bucketing — Q2A)
    batch_actual_start_date              = models.DateField(null=True, blank=True)
    assessment_actual_certification_date = models.DateField(null=True, blank=True)
    placed_date                          = models.DateField(null=True, blank=True)

    # Planned targets
    final_enrolment_planned     = models.IntegerField(default=0)
    final_certification_planned = models.IntegerField(default=0)
    final_placement_planned     = models.IntegerField(default=0)

    # Entity (SF / LLF)
    entity          = models.CharField(max_length=20, blank=True, default='')

    # Actuals (Q1A: trust these columns as the source of truth)
    on_going        = models.IntegerField(default=0)   # On Going flag/count
    fy_e_act        = models.IntegerField(default=0)   # FY 26-27 E Act
    fy_c_act        = models.IntegerField(default=0)   # FY 26-27 C Act
    fy_p_act        = models.IntegerField(default=0)   # FY 26-27 P Act
    fy_naps_act     = models.IntegerField(default=0)   # FY 26-27 NAPS Act
    fy_nats_act     = models.IntegerField(default=0)   # FY 26-27 NATS Act

    def __str__(self):
        return self.batch_id


# Candidate model removed — actuals now live on BatchPlan directly.
# ECPv1xl.xlsx is no longer imported.


class ManpowerStaff(models.Model):
    ecode = models.CharField(max_length=50)
    employee_name = models.CharField(max_length=255)
    official_email = models.CharField(max_length=255)
    employee_status = models.CharField(max_length=50)
    sub_project_name = models.CharField(max_length=255)
    sub_project_code = models.CharField(max_length=100)
    role = models.CharField(max_length=100)
    center_name_ops = models.CharField(max_length=255)
    centre = models.ForeignKey(Centre, on_delete=models.SET_NULL, null=True, to_field='centre_id')

    def __str__(self):
        return self.employee_name


class CommunityCollege(models.Model):
    sno = models.IntegerField(null=True, blank=True)
    source = models.CharField(max_length=255, blank=True, db_index=True)
    category = models.CharField(max_length=255, blank=True, db_index=True)
    name_place = models.CharField(max_length=255, blank=True)
    address = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    distance_km = models.FloatField(null=True, blank=True)
    rating = models.FloatField(null=True, blank=True)
    phone_hours = models.CharField(max_length=255, blank=True)
    centre_name = models.CharField(max_length=255, blank=True)
    centre = models.ForeignKey(Centre, on_delete=models.SET_NULL, null=True, blank=True, to_field='centre_id')

    def __str__(self):
        return self.name_place


class HyperlocalJob(models.Model):
    course = models.CharField(max_length=255, blank=True)
    sector = models.CharField(max_length=255, blank=True)
    district = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=255, blank=True)
    discovered_employer = models.CharField(max_length=255, blank=True)
    discovered_employer_id = models.CharField(max_length=50, blank=True, db_index=True)
    phone = models.CharField(max_length=100, blank=True)
    employer_address = models.TextField(blank=True)
    distance_km = models.FloatField(null=True, blank=True)
    rating = models.FloatField(null=True, blank=True)
    reviews = models.IntegerField(null=True, blank=True)
    naps_eligible = models.CharField(max_length=10, blank=True)
    suitable_roles = models.CharField(max_length=500, blank=True)
    outreach_status = models.CharField(max_length=100, blank=True)
    centre_name = models.CharField(max_length=255, blank=True)
    centre = models.ForeignKey(Centre, on_delete=models.SET_NULL, null=True, blank=True, to_field='centre_id')

    def __str__(self):
        return self.discovered_employer


# ── Staffing Tab Models ───────────────────────────────────────────────────────

class DemandSupply(models.Model):
    """Table 1 + Table 2 combined — Demand & Supply mapping per industrial cluster"""
    new_existing = models.CharField(max_length=50, blank=True)
    region = models.CharField(max_length=255, blank=True)
    city_location = models.CharField(max_length=255, blank=True)
    industrial_estate_cluster = models.CharField(max_length=255, blank=True)
    existing_client = models.CharField(max_length=255, blank=True)
    std_designation = models.CharField(max_length=255, blank=True)
    estimated_monthly_demand = models.IntegerField(null=True, blank=True)
    # Supply / Centre info
    nearest_center = models.CharField(max_length=255, blank=True)
    centre_id_ref = models.CharField(max_length=255, blank=True)
    center_address = models.TextField(blank=True)
    training_program_match = models.CharField(max_length=255, blank=True)
    estimated_monthly_supply = models.IntegerField(null=True, blank=True)
    training_program_naps_nats = models.CharField(max_length=10, blank=True)
    nearest_iti = models.CharField(max_length=255, blank=True)
    distance_from_center = models.CharField(max_length=100, blank=True)
    iti_trade_match = models.CharField(max_length=255, blank=True)
    centre = models.ForeignKey(Centre, on_delete=models.SET_NULL, null=True, blank=True, to_field='centre_id')

    def __str__(self):
        return f"{self.existing_client} — {self.city_location}"


class ITIDiplomaMaster(models.Model):
    """Table 3 — ITI & Diploma college master"""
    sno = models.IntegerField(null=True, blank=True)
    college_name = models.CharField(max_length=255, blank=True)
    college_type = models.CharField(max_length=50, blank=True)   # ITI / Diploma
    address = models.TextField(blank=True)
    rating = models.CharField(max_length=20, blank=True)
    phone_number = models.CharField(max_length=100, blank=True)
    working_hours = models.CharField(max_length=255, blank=True)
    website_map = models.CharField(max_length=255, blank=True)
    centre_id_ref = models.CharField(max_length=255, blank=True)
    centre_name = models.CharField(max_length=255, blank=True)
    centre = models.ForeignKey(Centre, on_delete=models.SET_NULL, null=True, blank=True, to_field='centre_id')

    def __str__(self):
        return self.college_name


class SFInterventionCollege(models.Model):
    """Table 4 — SF Intervention / Our ITI Colleges"""
    name_of_college = models.CharField(max_length=255, blank=True)
    address = models.TextField(blank=True)
    project_name = models.CharField(max_length=255, blank=True)
    qp = models.CharField(max_length=255, blank=True)
    centre_id_ref = models.CharField(max_length=255, blank=True)
    centre_name = models.CharField(max_length=255, blank=True)
    centre = models.ForeignKey(Centre, on_delete=models.SET_NULL, null=True, blank=True, to_field='centre_id')

    def __str__(self):
        return self.name_of_college


# ── SAHI Module Models ────────────────────────────────────────────────────────

class SAHIDemand(models.Model):
    """
    Main demand data for the SAHI module.
    Source: SAHI_Demand_Master.xlsx (now includes Sub Cluster ID / Cluster / Sub Cluster columns)
    Columns: Sub Cluster ID | Cluster | Sub Cluster | Region | Existing/Potential |
             Demand City | Location | Existing Client | Client Nature | Designation |
             HC | Monthly Demand
    """
    sub_cluster_id      = models.CharField(max_length=100, blank=True, db_index=True)
    cluster             = models.CharField(max_length=255, blank=True, db_index=True)
    sub_cluster         = models.CharField(max_length=255, blank=True, db_index=True)
    region              = models.CharField(max_length=255, blank=True, db_index=True)
    zone                = models.CharField(max_length=100, blank=True, db_index=True)  # Production / Technology & Services
    existing_potential  = models.CharField(max_length=50,  blank=True)
    demand_city         = models.CharField(max_length=255, blank=True, db_index=True)
    location            = models.CharField(max_length=255, blank=True)
    existing_client     = models.CharField(max_length=500, blank=True, db_index=True)
    client_nature       = models.CharField(max_length=255, blank=True)
    designation         = models.CharField(max_length=255, blank=True)
    hc                  = models.IntegerField(null=True, blank=True)
    monthly_demand      = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.existing_client} — {self.designation} ({self.demand_city})"


class DesignationQPMap(models.Model):
    """
    Maps SAHI Demand designations → Qualification Packs (QPs) in BatchPlan.
    Source: Designation_Master.xlsx (2 cols: Designation | Qp).
    One designation can map to multiple QPs (one row per mapping).
    """
    designation = models.CharField(max_length=255, db_index=True)
    qp          = models.CharField(max_length=255, db_index=True)

    class Meta:
        unique_together = [('designation', 'qp')]
        verbose_name     = 'Designation → QP Mapping'
        verbose_name_plural = 'Designation → QP Mappings'

    def __str__(self):
        return f"{self.designation} → {self.qp}"


class ClusterMaster(models.Model):
    """
    Cluster + Sub Cluster reference table with Google Maps URL per sub-cluster.
    Source: Cluster_Master_v1.xlsx
    Columns: Sub Cluster ID | Cluster | Sub Cluster | State | Map
    """
    sub_cluster_id = models.CharField(max_length=100, unique=True)
    cluster        = models.CharField(max_length=255, db_index=True)
    sub_cluster    = models.CharField(max_length=255, db_index=True)
    state          = models.CharField(max_length=100, blank=True)
    map_url        = models.TextField(blank=True)  # long Google Maps directions URLs
    # Coordinates parsed from map_url (center of the cluster area).
    # Populated by import_data.py / parse_cluster_coords management command.
    lat            = models.FloatField(null=True, blank=True)
    lng            = models.FloatField(null=True, blank=True)
    # List of [lat, lng] pairs for each individual stop encoded in the Google
    # Maps URL — these are the actual sub-locations (e.g., Whitefield, Hoskote,
    # Mahadevapura for "Bangalore East – Whitefield / Hoskote Belt").
    # For URLs with no stops the list is empty; treat `lat`/`lng` as the
    # single location in that case.
    stops          = models.JSONField(default=list, blank=True)

    class Meta:
        indexes = [models.Index(fields=['cluster', 'sub_cluster'])]

    def __str__(self):
        return f"{self.cluster} › {self.sub_cluster}"


# SAHIClusterMap removed — Center Master now carries Cluster + Sub Cluster directly,
# so SAHI demand can bridge to Centres via the shared Sub Cluster ID / Cluster columns.


# ── Cert Schedule (SMB Page) ─────────────────────────────────────────────────

class CertSchedule(models.Model):
    """
    Certification schedule per batch. Source: Cert_Schedule.xlsx.
    Each row is one Batch with its planned cert date + window + targets.
    """
    batch_id          = models.CharField(max_length=100, db_index=True)
    centre_name       = models.CharField(max_length=255)
    centre            = models.ForeignKey(
        Centre, on_delete=models.SET_NULL, null=True, blank=True, to_field='centre_id'
    )
    sub_cluster       = models.CharField(max_length=255, blank=True)
    cluster           = models.CharField(max_length=255, blank=True)
    course_trade      = models.CharField(max_length=255, blank=True)
    project           = models.CharField(max_length=255, blank=True)
    cert_start_date   = models.DateField(null=True, blank=True)
    days_to_cert      = models.IntegerField(null=True, blank=True)
    cert_window       = models.CharField(max_length=50, blank=True)
    cert_target       = models.IntegerField(default=0)
    placement_target  = models.IntegerField(default=0)
    naps              = models.CharField(max_length=10, blank=True)
    nats              = models.CharField(max_length=10, blank=True)
    dbt               = models.CharField(max_length=10, blank=True)
    verify_flag       = models.CharField(max_length=50, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['cert_start_date']),
            models.Index(fields=['cert_window']),
        ]

    def __str__(self):
        return f"{self.batch_id} — {self.course_trade}"


# ── Mobiliser & Trainer Target / Status ─────────────────────────────────────

class MobiliserTarget(models.Model):
    """
    One row per (Mobiliser × Batch).
    Source: Mobilsier_Target.xlsx
    """
    projects_fy          = models.CharField(max_length=50,  blank=True)
    project_name_sahi    = models.CharField(max_length=255, blank=True)
    mobiliser_id         = models.IntegerField(db_index=True)   # = Manpower.ecode
    sahi_center_name     = models.CharField(max_length=255, blank=True)
    batch_id             = models.CharField(max_length=100, blank=True, db_index=True)
    mobiliser_name       = models.CharField(max_length=255, blank=True)
    e_target             = models.IntegerField(default=0)
    c_target             = models.IntegerField(default=0)
    p_target             = models.IntegerField(default=0)
    e_act                = models.IntegerField(default=0)
    target_month_label   = models.CharField(max_length=20, blank=True)  # e.g. "May'26"

    def __str__(self):
        return f"{self.mobiliser_name} ({self.mobiliser_id}) — {self.sahi_center_name}"


class TrainerTarget(models.Model):
    """
    One row per (Trainer × Batch). Day-wise hours stored in TrainerTargetDay.
    Source: Trainer_Target.xlsx
    """
    batch_id             = models.CharField(max_length=100, blank=True, db_index=True)
    sahi_center_name     = models.CharField(max_length=255, blank=True)
    project_name_sahi    = models.CharField(max_length=255, blank=True)
    sub_project_name     = models.CharField(max_length=255, blank=True)
    sub_project_id_1     = models.CharField(max_length=100, blank=True)
    trainer_name         = models.CharField(max_length=255, blank=True)
    trainer_id           = models.IntegerField(db_index=True)   # = Manpower.ecode

    def __str__(self):
        return f"{self.trainer_name} ({self.trainer_id}) — {self.sahi_center_name}"


class TrainerTargetDay(models.Model):
    """One day's training hours for a trainer/batch row."""
    trainer_target = models.ForeignKey(
        TrainerTarget, related_name='days', on_delete=models.CASCADE
    )
    date  = models.DateField(db_index=True)
    hours = models.FloatField(default=0)

    class Meta:
        indexes = [models.Index(fields=['trainer_target', 'date'])]
        ordering = ['date']

    def __str__(self):
        return f"{self.trainer_target_id} {self.date}: {self.hours}h"


class SambhavCommunity(models.Model):
    """
    Sambhav Community projects.
    Source: Sambhav_Community.xlsx
    Columns: Project | Sub Cluster | Sub Cluster ID | Cluster | Location | Project Brief | TM
    """
    project        = models.CharField(max_length=255, blank=True, db_index=True)
    sub_cluster    = models.CharField(max_length=255, blank=True, db_index=True)
    sub_cluster_id = models.CharField(max_length=100, blank=True, db_index=True)
    cluster        = models.CharField(max_length=255, blank=True, db_index=True)
    location       = models.CharField(max_length=500, blank=True)
    project_brief  = models.TextField(blank=True)
    tm             = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=['cluster', 'sub_cluster'])]

    def __str__(self):
        return f"{self.project} — {self.sub_cluster}"


class NAPSData(models.Model):
    """
    Per-candidate NAPS data, used to build the Certification Pipeline table
    (aggregated to one row per Batch ID).
    Source: NAPS_Data.xlsx
    """
    batch_id                 = models.CharField(max_length=100, db_index=True)
    project_name             = models.CharField(max_length=255, blank=True, db_index=True)
    centre_name              = models.CharField(max_length=255, blank=True, db_index=True)
    centre_id                = models.CharField(max_length=100, blank=True, db_index=True)
    batch_actual_start_date  = models.DateField(null=True, blank=True)
    batch_actual_end_date    = models.DateField(null=True, blank=True)
    slab                     = models.CharField(max_length=100, blank=True)
    candidate_id             = models.CharField(max_length=100, blank=True)
    course_name              = models.CharField(max_length=255, blank=True)
    qp_name                  = models.CharField(max_length=255, blank=True, db_index=True)
    naps_eligible            = models.CharField(max_length=10, blank=True, db_index=True)
    estimated_revenue        = models.IntegerField(default=0)
    candidate_name           = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=['batch_id', 'qp_name'])]


class NAPSPlan(models.Model):
    """
    Planned NAPS certifications month-by-month per Batch.
    Source: NAPS_Plan_FY26-27.xlsx
    """
    projects_fy                  = models.CharField(max_length=100, blank=True)
    batch_id                     = models.CharField(max_length=100, db_index=True)
    centre_name                  = models.CharField(max_length=255, blank=True, db_index=True)
    centre_id                    = models.CharField(max_length=100, blank=True, db_index=True)
    qp_name                      = models.CharField(max_length=255, blank=True, db_index=True)
    naps_eligible                = models.CharField(max_length=10, blank=True, db_index=True)
    sub_cluster_id               = models.CharField(max_length=100, blank=True)
    cluster                      = models.CharField(max_length=255, blank=True, db_index=True)
    sub_cluster                  = models.CharField(max_length=255, blank=True, db_index=True)
    project_name                 = models.CharField(max_length=255, blank=True, db_index=True)
    sub_project_name             = models.CharField(max_length=255, blank=True)
    batch_planned_start_date     = models.DateField(null=True, blank=True)
    certification_start_date     = models.DateField(null=True, blank=True)
    placement_end_date           = models.DateField(null=True, blank=True)
    final_enrolment_planned      = models.IntegerField(default=0)
    final_certification_planned  = models.IntegerField(default=0)
    final_placement_planned      = models.FloatField(default=0)
    estimated_revenue            = models.IntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=['centre_id', 'qp_name'])]


class OutreachStatus(models.Model):
    """
    Outreach pipeline status for each Discovered Employer found via
    Hyperlocal job discovery. One row per employer (per centre).
    Source: Outreach_Hyperlocal_Master.xlsx
    """
    discovered_employer       = models.CharField(max_length=255, blank=True)
    discovered_employer_id    = models.CharField(max_length=50, db_index=True)
    status                    = models.CharField(max_length=50, blank=True, db_index=True)
    hr_name                   = models.CharField(max_length=255, blank=True)
    email                     = models.CharField(max_length=255, blank=True)
    hr_contact_name           = models.CharField(max_length=100, blank=True)
    number_of_open_positions  = models.IntegerField(null=True, blank=True)
    shortlisted               = models.IntegerField(null=True, blank=True)
    centre_name               = models.CharField(max_length=255, blank=True)
    centre_id                 = models.CharField(max_length=100, blank=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=['centre_id', 'status'])]

    def __str__(self):
        return f"{self.discovered_employer_id} — {self.status}"


# ─────────────────────────────────────────────────────────────────────────────
#  Sourcing Summary
#  ----------------
#  Master:  Sourcing_Channels_Master.xlsx — full taxonomy of 6 Community Sources
#           with 46 Community Categories (e.g. Community Mobilisation → Panchayat).
#  Actual:  Sourcing_Actual_Data.xlsx — one row per candidate showing which
#           Source / Category they were sourced through. Counts here drive the
#           "candidate count" and the Active flag on the Sourcing Summary card.
# ─────────────────────────────────────────────────────────────────────────────
class SourcingChannelMaster(models.Model):
    """Master taxonomy: Community Source → Community Category.
    Defines the full universe of categories that *can* exist for each source,
    regardless of whether any candidate has actually been sourced through it."""
    community_source   = models.CharField(max_length=255, db_index=True)
    community_category = models.CharField(max_length=255, db_index=True)

    class Meta:
        unique_together = [('community_source', 'community_category')]
        indexes = [models.Index(fields=['community_source', 'community_category'])]

    def __str__(self):
        return f"{self.community_source} → {self.community_category}"


class SourcingActual(models.Model):
    """One row per candidate showing the Source / Category they came in through.
    Each row counts as 1 lead/candidate for the Sourcing Summary card."""
    centre             = models.ForeignKey(Centre, on_delete=models.SET_NULL,
                                           null=True, blank=True, to_field='centre_id')
    centre_id_raw      = models.CharField(max_length=100, blank=True, db_index=True)
    centre_name        = models.CharField(max_length=255, blank=True)
    batch_id           = models.CharField(max_length=100, blank=True, db_index=True)
    candidate_age      = models.IntegerField(null=True, blank=True)
    community_source   = models.CharField(max_length=255, blank=True, db_index=True)
    community_category = models.CharField(max_length=255, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['community_source', 'community_category']),
            models.Index(fields=['centre_id_raw', 'community_source']),
        ]

    def __str__(self):
        return f"{self.centre_name} · {self.community_source} / {self.community_category}"


# ── Trainer Productivity (NEW — replaces Trainer_Target) ────────────────────
#
# Two paired tables driven by Trainer_productivity_present.xlsx and
# Trainer_productivity_duration.xlsx. Each row is one Batch × Trainer; the
# day-wise figures (present-count or hours) are stored in the *Day child rows.
#
# Replaces the old TrainerTarget-based "Trainer Status" view with:
#   • Attendance Performance — Enrolled, day-wise Present, Present %
#   • Trainer Productivity Duration — day-wise hours, total, days worked

class TrainerProductivityPresent(models.Model):
    """One row per (Batch × Trainer) from Trainer_productivity_present.xlsx."""
    batch_id     = models.CharField(max_length=100, blank=True, db_index=True)
    centre_name  = models.CharField(max_length=255, blank=True)
    centre_id    = models.CharField(max_length=100, blank=True, db_index=True)
    qp_name      = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    trainer_id   = models.IntegerField(db_index=True)
    enrolled     = models.IntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=['centre_id', 'trainer_id'])]

    def __str__(self):
        return f"{self.trainer_name} · {self.batch_id} ({self.enrolled} enr)"


class TrainerProductivityPresentDay(models.Model):
    """Per-day present count for one TrainerProductivityPresent row."""
    parent = models.ForeignKey(
        TrainerProductivityPresent, related_name='days', on_delete=models.CASCADE
    )
    date     = models.DateField(db_index=True)
    present  = models.IntegerField(default=0)

    class Meta:
        indexes  = [models.Index(fields=['parent', 'date'])]
        ordering = ['date']


class TrainerProductivityDuration(models.Model):
    """One row per (Batch × Trainer) from Trainer_productivity_duration.xlsx."""
    batch_id     = models.CharField(max_length=100, blank=True, db_index=True)
    centre_name  = models.CharField(max_length=255, blank=True)
    centre_id    = models.CharField(max_length=100, blank=True, db_index=True)
    qp_name      = models.CharField(max_length=255, blank=True)
    trainer_name = models.CharField(max_length=255, blank=True)
    trainer_id   = models.IntegerField(db_index=True)

    class Meta:
        indexes = [models.Index(fields=['centre_id', 'trainer_id'])]

    def __str__(self):
        return f"{self.trainer_name} · {self.batch_id}"


class TrainerProductivityDurationDay(models.Model):
    """Per-day duration (decimal hours) for one TrainerProductivityDuration row."""
    parent = models.ForeignKey(
        TrainerProductivityDuration, related_name='days', on_delete=models.CASCADE
    )
    date  = models.DateField(db_index=True)
    hours = models.FloatField(default=0)

    class Meta:
        indexes  = [models.Index(fields=['parent', 'date'])]
        ordering = ['date']


# ── Associate Supply (NEW — for SAHI "Supply Chain" tables) ─────────────────

class AssociateData(models.Model):
    """
    One row per candidate associate. Source: Associate_data.xlsx.
    Bridges SAHI demand → ITI/Polytechnic supply via Sub Cluster ID + Supply PIN.
    """
    associate_no                = models.CharField(max_length=50,  blank=True, db_index=True)
    associate_name              = models.CharField(max_length=255, blank=True)
    date_of_birth               = models.CharField(max_length=20,  blank=True)
    gender                      = models.CharField(max_length=20,  blank=True, db_index=True)
    permanent_address           = models.TextField(blank=True)
    supply_state                = models.CharField(max_length=100, blank=True, db_index=True)
    supply_district             = models.CharField(max_length=100, blank=True, db_index=True)
    supply_pin                  = models.CharField(max_length=10,  blank=True, db_index=True)
    latitude                    = models.FloatField(null=True, blank=True)
    longitude                   = models.FloatField(null=True, blank=True)
    demand_city                 = models.CharField(max_length=100, blank=True)
    demand_cluster_client_loc   = models.CharField(max_length=255, blank=True)
    client                      = models.CharField(max_length=500, blank=True, db_index=True)
    sub_cluster_id              = models.CharField(max_length=100, blank=True, db_index=True)
    cluster                     = models.CharField(max_length=255, blank=True, db_index=True)
    sub_cluster                 = models.CharField(max_length=255, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['sub_cluster_id', 'supply_pin']),
            models.Index(fields=['cluster', 'sub_cluster']),
        ]

    def __str__(self):
        return f"{self.associate_no} · {self.associate_name}"


class ITIPolytechnicByPIN(models.Model):
    """
    Reference list of ITI / Polytechnic colleges grouped by Supply PIN.
    Source: ITI_Polytechnic_Colleges_by_PIN_Supply.xlsx.
    """
    sno              = models.IntegerField(null=True, blank=True)
    supply_pin       = models.CharField(max_length=10, blank=True, db_index=True)
    latitude         = models.FloatField(null=True, blank=True)
    longitude        = models.FloatField(null=True, blank=True)
    institution_name = models.CharField(max_length=500, blank=True)
    institution_type = models.CharField(max_length=50,  blank=True, db_index=True)  # 'ITI' / 'Polytechnic'
    address_location = models.CharField(max_length=500, blank=True)
    distance_km      = models.CharField(max_length=50,  blank=True)

    class Meta:
        indexes  = [models.Index(fields=['supply_pin', 'institution_type'])]
        ordering = ['supply_pin', 'institution_type', 'institution_name']

    def __str__(self):
        return f"{self.institution_name} ({self.institution_type}) @ {self.supply_pin}"


class WorkSetuPINMap(models.Model):
    """
    Maps Supply PIN → WorkSetu Sub Cluster.
    Source: Supply_WorkSetu_Sub_Cluster.xlsx
    Columns: Supply State | Supply District | Supply PIN | Sub Cluster
    Used to derive the WorkSetu Sub Cluster for every associate (via supply_pin).
    """
    supply_state        = models.CharField(max_length=100, blank=True, db_index=True)
    supply_district     = models.CharField(max_length=100, blank=True, db_index=True)
    supply_pin          = models.CharField(max_length=10,  unique=True, db_index=True)
    worksetu_sub_cluster = models.CharField(max_length=255, blank=True, db_index=True)

    class Meta:
        verbose_name        = 'WorkSetu PIN Mapping'
        verbose_name_plural = 'WorkSetu PIN Mappings'
        indexes = [models.Index(fields=['worksetu_sub_cluster'])]

    def __str__(self):
        return f"PIN {self.supply_pin} → {self.worksetu_sub_cluster}"


class SalesPipeline(models.Model):
    """
    Sales / business-development opportunities.
    Source: Sales_Pipeline.xlsx (each row = one opportunity).
    Used in MIS Summary → Sales Pipeline table (TM → Centre → Stage drill-down).
    """
    opp_id        = models.CharField(max_length=50, blank=True, db_index=True)
    created       = models.DateField(null=True, blank=True)
    centre_name   = models.CharField(max_length=255, blank=True, db_index=True)
    centre        = models.ForeignKey(Centre, on_delete=models.SET_NULL, null=True, blank=True, to_field='centre_id')
    account_client = models.CharField(max_length=255, blank=True)
    client_type   = models.CharField(max_length=100, blank=True)
    sector        = models.CharField(max_length=255, blank=True)
    service_line  = models.CharField(max_length=255, blank=True)
    exp_positions = models.IntegerField(default=0)
    deal_value    = models.FloatField(default=0)
    stage         = models.CharField(max_length=100, blank=True, db_index=True)
    prob          = models.FloatField(default=0)
    weighted      = models.FloatField(default=0)
    exp_close     = models.DateField(null=True, blank=True)
    status        = models.CharField(max_length=100, blank=True)
    next_step     = models.CharField(max_length=255, blank=True)
    last_activity = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.opp_id} — {self.account_client} ({self.stage})"


class RecruitmentFunnel(models.Model):
    """
    Recruitment requisitions and their funnel metrics.
    Source: Recruitment_Funnel.xlsx (each row = one requisition).
    Used in MIS Summary → Recruitment Funnel table (TM → Centre → Client drill-down).
    """
    req_id        = models.CharField(max_length=50, blank=True, db_index=True)
    month         = models.CharField(max_length=20, blank=True)
    centre_name   = models.CharField(max_length=255, blank=True, db_index=True)
    centre        = models.ForeignKey(Centre, on_delete=models.SET_NULL, null=True, blank=True, to_field='centre_id')
    client        = models.CharField(max_length=255, blank=True)
    job_role      = models.CharField(max_length=255, blank=True)
    sector        = models.CharField(max_length=255, blank=True)
    open_vacancies = models.IntegerField(default=0)   # Open Vacancies / Target Hire
    sourced       = models.IntegerField(default=0)
    screened      = models.IntegerField(default=0)
    interviewed   = models.IntegerField(default=0)
    offered       = models.IntegerField(default=0)
    joined        = models.IntegerField(default=0)
    dropped       = models.IntegerField(default=0)   # Dropped (post-offer)

    def __str__(self):
        return f"{self.req_id} — {self.client} ({self.job_role})"
