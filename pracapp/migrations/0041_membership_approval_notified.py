from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0040_schedule_period_preset'),
    ]

    operations = [
        migrations.AddField(
            model_name='membership',
            name='approval_notified',
            field=models.BooleanField(default=True),
        ),
    ]
