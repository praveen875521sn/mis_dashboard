from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0021_worksetupinmap'),
    ]

    operations = [
        migrations.AddField(
            model_name='centre',
            name='state',
            field=models.CharField(blank=True, db_index=True, default='', max_length=100),
            preserve_default=False,
        ),
    ]
