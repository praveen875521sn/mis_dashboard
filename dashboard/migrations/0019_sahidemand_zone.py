from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0018_productivity_associate_iti'),
    ]

    operations = [
        migrations.AddField(
            model_name='sahidemand',
            name='zone',
            field=models.CharField(blank=True, db_index=True, default='', max_length=100),
            preserve_default=False,
        ),
    ]
