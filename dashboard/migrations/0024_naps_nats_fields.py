# Generated manually – adds NAPS/NATS alignment fields to NapsEligible
# and NAPS/NATS actuals to BatchPlan.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0023_batchplan_entity'),
    ]

    operations = [
        # NapsEligible – NAPS/NATS alignment flags
        migrations.AddField(
            model_name='napseligible',
            name='naps_aligned',
            field=models.CharField(blank=True, max_length=10, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='napseligible',
            name='nats_aligned',
            field=models.CharField(blank=True, max_length=10, default=''),
            preserve_default=False,
        ),
        # BatchPlan – NAPS/NATS actuals from Batch_Plan_New.xlsx
        migrations.AddField(
            model_name='batchplan',
            name='fy_naps_act',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='batchplan',
            name='fy_nats_act',
            field=models.IntegerField(default=0),
        ),
    ]
