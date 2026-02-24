from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0039_add_extra_practice_schedule'),
    ]

    operations = [
        migrations.CreateModel(
            name='SchedulePeriodPreset',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('preset_code', models.CharField(choices=[('SEMESTER_1', '1학기'), ('SUMMER_BREAK', '여름방학'), ('SEMESTER_2', '2학기'), ('WINTER_BREAK', '겨울방학'), ('CUSTOM', '기타(직접 설정)')], default='CUSTOM', max_length=20)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='schedule_period_presets', to='pracapp.user')),
            ],
            options={
                'indexes': [models.Index(fields=['user', 'start_date', 'end_date'], name='sched_preset_user_range_idx')],
                'constraints': [models.UniqueConstraint(fields=('user', 'start_date', 'end_date'), name='sched_preset_user_range_unique')],
            },
        ),
    ]
