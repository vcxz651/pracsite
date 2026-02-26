from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0044_meeting_meeting_band_prac_range_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SongComment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('content', models.CharField(max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='song_comments', to=settings.AUTH_USER_MODEL)),
                ('song', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comments', to='pracapp.song')),
            ],
        ),
        migrations.AddIndex(
            model_name='songcomment',
            index=models.Index(fields=['song', 'created_at'], name='songcmt_song_created_idx'),
        ),
        migrations.AddIndex(
            model_name='songcomment',
            index=models.Index(fields=['author', 'created_at'], name='songcmt_author_created_idx'),
        ),
    ]
