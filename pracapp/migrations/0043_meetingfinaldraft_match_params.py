from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0042_recurringexception_target_payload_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='meetingfinaldraft',
            name='match_params',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
