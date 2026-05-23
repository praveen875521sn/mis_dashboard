from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0013_outreach_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='clustermaster',
            name='lat',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='clustermaster',
            name='lng',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
