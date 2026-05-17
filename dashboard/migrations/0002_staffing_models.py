from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='DemandSupply',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('new_existing', models.CharField(blank=True, max_length=50)),
                ('region', models.CharField(blank=True, max_length=255)),
                ('city_location', models.CharField(blank=True, max_length=255)),
                ('industrial_estate_cluster', models.CharField(blank=True, max_length=255)),
                ('existing_client', models.CharField(blank=True, max_length=255)),
                ('std_designation', models.CharField(blank=True, max_length=255)),
                ('estimated_monthly_demand', models.IntegerField(blank=True, null=True)),
                ('nearest_center', models.CharField(blank=True, max_length=255)),
                ('centre_id_ref', models.CharField(blank=True, max_length=255)),
                ('center_address', models.TextField(blank=True)),
                ('training_program_match', models.CharField(blank=True, max_length=255)),
                ('estimated_monthly_supply', models.IntegerField(blank=True, null=True)),
                ('training_program_naps_nats', models.CharField(blank=True, max_length=10)),
                ('nearest_iti', models.CharField(blank=True, max_length=255)),
                ('distance_from_center', models.CharField(blank=True, max_length=100)),
                ('iti_trade_match', models.CharField(blank=True, max_length=255)),
                ('centre', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='dashboard.centre', to_field='centre_id')),
            ],
        ),
        migrations.CreateModel(
            name='ITIDiplomaMaster',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sno', models.IntegerField(blank=True, null=True)),
                ('college_name', models.CharField(blank=True, max_length=255)),
                ('college_type', models.CharField(blank=True, max_length=50)),
                ('address', models.TextField(blank=True)),
                ('rating', models.CharField(blank=True, max_length=20)),
                ('phone_number', models.CharField(blank=True, max_length=100)),
                ('working_hours', models.CharField(blank=True, max_length=255)),
                ('website_map', models.CharField(blank=True, max_length=255)),
                ('centre_id_ref', models.CharField(blank=True, max_length=255)),
                ('centre_name', models.CharField(blank=True, max_length=255)),
                ('centre', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='dashboard.centre', to_field='centre_id')),
            ],
        ),
        migrations.CreateModel(
            name='SFInterventionCollege',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name_of_college', models.CharField(blank=True, max_length=255)),
                ('address', models.TextField(blank=True)),
                ('project_name', models.CharField(blank=True, max_length=255)),
                ('qp', models.CharField(blank=True, max_length=255)),
                ('centre_id_ref', models.CharField(blank=True, max_length=255)),
                ('centre_name', models.CharField(blank=True, max_length=255)),
                ('centre', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='dashboard.centre', to_field='centre_id')),
            ],
        ),
    ]
