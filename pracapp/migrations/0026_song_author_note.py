from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0025_song_has_sheet'),
    ]

    operations = [
        migrations.AddField(
            model_name='song',
            name='author_note',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='작성자 한 마디'),
        ),
    ]
