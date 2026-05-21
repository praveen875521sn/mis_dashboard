from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0010_sambhavcommunity'),
    ]

    operations = [
        migrations.AddField(
            model_name='communitycollege',
            name='source',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='communitycollege',
            name='category',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
    ]
