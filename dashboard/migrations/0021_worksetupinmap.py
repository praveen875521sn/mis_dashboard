from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0020_designationqpmap'),
    ]

    operations = [
        migrations.CreateModel(
            name='WorkSetuPINMap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('supply_state',         models.CharField(blank=True, db_index=True, max_length=100)),
                ('supply_district',      models.CharField(blank=True, db_index=True, max_length=100)),
                ('supply_pin',           models.CharField(db_index=True, max_length=10, unique=True)),
                ('worksetu_sub_cluster', models.CharField(blank=True, db_index=True, max_length=255)),
            ],
            options={
                'verbose_name':        'WorkSetu PIN Mapping',
                'verbose_name_plural': 'WorkSetu PIN Mappings',
            },
        ),
        migrations.AddIndex(
            model_name='worksetupinmap',
            index=models.Index(fields=['worksetu_sub_cluster'], name='dashboard_w_worksetu_idx'),
        ),
    ]
