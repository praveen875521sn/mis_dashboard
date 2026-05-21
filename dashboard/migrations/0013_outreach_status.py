from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0012_naps_data_and_plan'),
    ]

    operations = [
        migrations.AddField(
            model_name='hyperlocaljob',
            name='discovered_employer_id',
            field=models.CharField(blank=True, db_index=True, max_length=50),
        ),
        migrations.CreateModel(
            name='OutreachStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('discovered_employer',      models.CharField(blank=True, max_length=255)),
                ('discovered_employer_id',   models.CharField(db_index=True, max_length=50)),
                ('status',                   models.CharField(blank=True, db_index=True, max_length=50)),
                ('hr_name',                  models.CharField(blank=True, max_length=255)),
                ('email',                    models.CharField(blank=True, max_length=255)),
                ('hr_contact_name',          models.CharField(blank=True, max_length=100)),
                ('number_of_open_positions', models.IntegerField(blank=True, null=True)),
                ('shortlisted',              models.IntegerField(blank=True, null=True)),
                ('centre_name',              models.CharField(blank=True, max_length=255)),
                ('centre_id',                models.CharField(blank=True, db_index=True, max_length=100)),
            ],
            options={
                'indexes': [models.Index(fields=['centre_id', 'status'], name='dashboard_o_centre__9d4ec5_idx')],
            },
        ),
    ]
