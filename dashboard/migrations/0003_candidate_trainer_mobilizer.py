from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0002_staffing_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='candidate',
            name='trainer_id',
            field=models.CharField(max_length=100, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='trainer_name',
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='trainer_employee_id',
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='mobilizer_id',
            field=models.CharField(max_length=100, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='mobilizer_name',
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='candidate',
            name='mobilizer_employee_id',
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
    ]
