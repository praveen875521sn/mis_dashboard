from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0015_centre_center_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='clustermaster',
            name='stops',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
