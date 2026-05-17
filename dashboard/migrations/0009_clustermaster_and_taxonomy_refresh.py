from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0008_certschedule'),
    ]

    operations = [
        # ── 1. Drop SAHIClusterMap (Center Master now carries cluster + sub_cluster directly) ──
        migrations.DeleteModel(name='SAHIClusterMap'),

        # ── 2. Add sub_cluster_id to Centre ──
        migrations.AddField(
            model_name='centre',
            name='sub_cluster_id',
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
        # Add db_index on existing cluster + sub_cluster
        migrations.AlterField(
            model_name='centre',
            name='cluster',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='centre',
            name='sub_cluster',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),

        # ── 3. Add sub_cluster_id, sub_cluster, location to SAHIDemand ──
        migrations.AddField(
            model_name='sahidemand',
            name='sub_cluster_id',
            field=models.CharField(blank=True, db_index=True, max_length=100),
        ),
        migrations.AddField(
            model_name='sahidemand',
            name='sub_cluster',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AddField(
            model_name='sahidemand',
            name='location',
            field=models.CharField(blank=True, max_length=255),
        ),

        # ── 4. Create ClusterMaster ──
        migrations.CreateModel(
            name='ClusterMaster',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sub_cluster_id', models.CharField(max_length=100, unique=True)),
                ('cluster', models.CharField(db_index=True, max_length=255)),
                ('sub_cluster', models.CharField(db_index=True, max_length=255)),
                ('state', models.CharField(blank=True, max_length=100)),
                ('map_url', models.TextField(blank=True)),
            ],
            options={
                'indexes': [models.Index(fields=['cluster', 'sub_cluster'], name='dashboard_c_cluster_51c95c_idx')],
            },
        ),
    ]
