# Adds SalesPipeline and RecruitmentFunnel models.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0024_naps_nats_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='SalesPipeline',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('opp_id', models.CharField(blank=True, db_index=True, max_length=50)),
                ('created', models.DateField(blank=True, null=True)),
                ('centre_name', models.CharField(blank=True, db_index=True, max_length=255)),
                ('account_client', models.CharField(blank=True, max_length=255)),
                ('client_type', models.CharField(blank=True, max_length=100)),
                ('sector', models.CharField(blank=True, max_length=255)),
                ('service_line', models.CharField(blank=True, max_length=255)),
                ('exp_positions', models.IntegerField(default=0)),
                ('deal_value', models.FloatField(default=0)),
                ('stage', models.CharField(blank=True, db_index=True, max_length=100)),
                ('prob', models.FloatField(default=0)),
                ('weighted', models.FloatField(default=0)),
                ('exp_close', models.DateField(blank=True, null=True)),
                ('status', models.CharField(blank=True, max_length=100)),
                ('next_step', models.CharField(blank=True, max_length=255)),
                ('last_activity', models.DateField(blank=True, null=True)),
                ('centre', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='dashboard.centre', to_field='centre_id')),
            ],
        ),
        migrations.CreateModel(
            name='RecruitmentFunnel',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('req_id', models.CharField(blank=True, db_index=True, max_length=50)),
                ('month', models.CharField(blank=True, max_length=20)),
                ('centre_name', models.CharField(blank=True, db_index=True, max_length=255)),
                ('client', models.CharField(blank=True, max_length=255)),
                ('job_role', models.CharField(blank=True, max_length=255)),
                ('sector', models.CharField(blank=True, max_length=255)),
                ('open_vacancies', models.IntegerField(default=0)),
                ('sourced', models.IntegerField(default=0)),
                ('screened', models.IntegerField(default=0)),
                ('interviewed', models.IntegerField(default=0)),
                ('offered', models.IntegerField(default=0)),
                ('joined', models.IntegerField(default=0)),
                ('dropped', models.IntegerField(default=0)),
                ('centre', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='dashboard.centre', to_field='centre_id')),
            ],
        ),
    ]
