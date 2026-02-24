from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0041_membership_approval_notified'),
    ]

    operations = [
        migrations.AddField(
            model_name='recurringexception',
            name='target_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterUniqueTogether(
            name='recurringexception',
            unique_together=set(),
        ),
    ]

