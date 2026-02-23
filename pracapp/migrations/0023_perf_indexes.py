from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0022_meeting_is_final_schedule_confirmed'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='session',
            index=models.Index(fields=['song', 'name'], name='session_song_name_idx'),
        ),
        migrations.AddIndex(
            model_name='session',
            index=models.Index(fields=['song', 'assignee'], name='session_song_assign_idx'),
        ),
        migrations.AddIndex(
            model_name='membership',
            index=models.Index(fields=['user', 'band', 'is_approved'], name='member_user_band_ok_idx'),
        ),
        migrations.AddIndex(
            model_name='membership',
            index=models.Index(fields=['band', 'is_approved', 'role'], name='member_band_role_ok_idx'),
        ),
        migrations.AddIndex(
            model_name='practiceroom',
            index=models.Index(fields=['band', 'is_temporary', 'name'], name='room_band_temp_name_idx'),
        ),
    ]
