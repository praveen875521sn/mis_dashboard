from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0019_sahidemand_zone'),
    ]

    operations = [
        migrations.CreateModel(
            name='DesignationQPMap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('designation', models.CharField(db_index=True, max_length=255)),
                ('qp', models.CharField(db_index=True, max_length=255)),
            ],
            options={
                'verbose_name': 'Designation → QP Mapping',
                'verbose_name_plural': 'Designation → QP Mappings',
            },
        ),
        migrations.AlterUniqueTogether(
            name='designationqpmap',
            unique_together={('designation', 'qp')},
        ),
    ]
