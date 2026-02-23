from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0023_perf_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='practiceschedule',
            index=models.Index(fields=['meeting', 'date', 'start_index'], name='ps_meet_date_start_idx'),
        ),
        migrations.AddIndex(
            model_name='practiceschedule',
            index=models.Index(fields=['meeting', 'song'], name='ps_meet_song_idx'),
        ),
        migrations.AddIndex(
            model_name='practiceschedule',
            index=models.Index(fields=['meeting', 'room', 'date', 'start_index'], name='ps_meet_room_date_start_idx'),
        ),
    ]
