from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0011_communitycollege_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='NAPSData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('batch_id',                models.CharField(db_index=True, max_length=100)),
                ('project_name',            models.CharField(blank=True, db_index=True, max_length=255)),
                ('centre_name',             models.CharField(blank=True, db_index=True, max_length=255)),
                ('centre_id',               models.CharField(blank=True, db_index=True, max_length=100)),
                ('batch_actual_start_date', models.DateField(blank=True, null=True)),
                ('batch_actual_end_date',   models.DateField(blank=True, null=True)),
                ('slab',                    models.CharField(blank=True, max_length=100)),
                ('candidate_id',            models.CharField(blank=True, max_length=100)),
                ('course_name',             models.CharField(blank=True, max_length=255)),
                ('qp_name',                 models.CharField(blank=True, db_index=True, max_length=255)),
                ('naps_eligible',           models.CharField(blank=True, db_index=True, max_length=10)),
                ('estimated_revenue',       models.IntegerField(default=0)),
                ('candidate_name',          models.CharField(blank=True, max_length=255)),
            ],
            options={
                'indexes': [models.Index(fields=['batch_id', 'qp_name'], name='dashboard_n_batch_i_8c2b7e_idx')],
            },
        ),
        migrations.CreateModel(
            name='NAPSPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('projects_fy',                  models.CharField(blank=True, max_length=100)),
                ('batch_id',                     models.CharField(db_index=True, max_length=100)),
                ('centre_name',                  models.CharField(blank=True, db_index=True, max_length=255)),
                ('centre_id',                    models.CharField(blank=True, db_index=True, max_length=100)),
                ('qp_name',                      models.CharField(blank=True, db_index=True, max_length=255)),
                ('naps_eligible',                models.CharField(blank=True, db_index=True, max_length=10)),
                ('sub_cluster_id',               models.CharField(blank=True, max_length=100)),
                ('cluster',                      models.CharField(blank=True, db_index=True, max_length=255)),
                ('sub_cluster',                  models.CharField(blank=True, db_index=True, max_length=255)),
                ('project_name',                 models.CharField(blank=True, db_index=True, max_length=255)),
                ('sub_project_name',             models.CharField(blank=True, max_length=255)),
                ('batch_planned_start_date',     models.DateField(blank=True, null=True)),
                ('certification_start_date',     models.DateField(blank=True, null=True)),
                ('placement_end_date',           models.DateField(blank=True, null=True)),
                ('final_enrolment_planned',      models.IntegerField(default=0)),
                ('final_certification_planned',  models.IntegerField(default=0)),
                ('final_placement_planned',      models.FloatField(default=0)),
                ('estimated_revenue',            models.IntegerField(default=0)),
            ],
            options={
                'indexes': [models.Index(fields=['centre_id', 'qp_name'], name='dashboard_n_centre_eb4f1a_idx')],
            },
        ),
    ]
