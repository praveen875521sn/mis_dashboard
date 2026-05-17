from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0003_candidate_trainer_mobilizer'),
    ]

    operations = [
        migrations.AddField(model_name='centre', name='cluster',
            field=models.CharField(blank=True, max_length=255, null=True)),
        migrations.AddField(model_name='centre', name='sub_cluster',
            field=models.CharField(blank=True, max_length=255, null=True)),
        migrations.AddField(model_name='centre', name='entity',
            field=models.CharField(blank=True, max_length=50, null=True)),
        migrations.CreateModel(
            name='NapsEligible',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('qp', models.CharField(blank=True, max_length=500)),
                ('naps_eligible', models.CharField(blank=True, max_length=10)),
                ('course_name', models.CharField(blank=True, max_length=500)),
                ('course_type', models.CharField(blank=True, max_length=100)),
                ('sector', models.CharField(blank=True, max_length=255)),
                ('minimum_qualification', models.CharField(blank=True, max_length=255)),
                ('on_job_training', models.CharField(blank=True, max_length=100)),
                ('qp_mapped', models.CharField(blank=True, max_length=10)),
            ],
        ),
    ]
