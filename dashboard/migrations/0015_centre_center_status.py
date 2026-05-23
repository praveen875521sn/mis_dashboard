from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0014_clustermaster_lat_lng'),
    ]

    operations = [
        migrations.AddField(
            model_name='centre',
            name='center_status',
            field=models.CharField(blank=True, db_index=True, max_length=50),
        ),
    ]
