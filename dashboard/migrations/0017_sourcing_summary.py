from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0016_clustermaster_stops'),
    ]

    operations = [
        migrations.CreateModel(
            name='SourcingChannelMaster',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('community_source',   models.CharField(db_index=True, max_length=255)),
                ('community_category', models.CharField(db_index=True, max_length=255)),
            ],
            options={
                'indexes': [models.Index(fields=['community_source', 'community_category'],
                                         name='dashboard_s_communi_2ff03d_idx')],
                'unique_together': {('community_source', 'community_category')},
            },
        ),
        migrations.CreateModel(
            name='SourcingActual',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('centre_id_raw',      models.CharField(blank=True, db_index=True, max_length=100)),
                ('centre_name',        models.CharField(blank=True, max_length=255)),
                ('batch_id',           models.CharField(blank=True, db_index=True, max_length=100)),
                ('candidate_age',      models.IntegerField(blank=True, null=True)),
                ('community_source',   models.CharField(blank=True, db_index=True, max_length=255)),
                ('community_category', models.CharField(blank=True, db_index=True, max_length=255)),
                ('centre',             models.ForeignKey(blank=True, null=True,
                                                         on_delete=django.db.models.deletion.SET_NULL,
                                                         to='dashboard.centre', to_field='centre_id')),
            ],
            options={
                'indexes': [
                    models.Index(fields=['community_source', 'community_category'],
                                 name='dashboard_s_communi_e1a2bc_idx'),
                    models.Index(fields=['centre_id_raw', 'community_source'],
                                 name='dashboard_s_centre__d77c4f_idx'),
                ],
            },
        ),
    ]
