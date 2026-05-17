from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0009_clustermaster_and_taxonomy_refresh'),
    ]

    operations = [
        migrations.CreateModel(
            name='SambhavCommunity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('project',        models.CharField(blank=True, db_index=True, max_length=255)),
                ('sub_cluster',    models.CharField(blank=True, db_index=True, max_length=255)),
                ('sub_cluster_id', models.CharField(blank=True, db_index=True, max_length=100)),
                ('cluster',        models.CharField(blank=True, db_index=True, max_length=255)),
                ('location',       models.CharField(blank=True, max_length=500)),
                ('project_brief',  models.TextField(blank=True)),
                ('tm',             models.CharField(blank=True, max_length=255)),
            ],
            options={
                'indexes': [models.Index(fields=['cluster', 'sub_cluster'], name='dashboard_s_cluster_b9f7a3_idx')],
            },
        ),
    ]
