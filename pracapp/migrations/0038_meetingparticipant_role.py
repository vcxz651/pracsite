from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0037_membership_membership_user_band_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='meetingparticipant',
            name='role',
            field=models.CharField(
                choices=[('MEMBER', '멤버'), ('MANAGER', '미팅 매니저')],
                default='MEMBER',
                max_length=16,
            ),
        ),
    ]
