from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0026_song_author_note'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='has_sheet',
            field=models.BooleanField(default=False, verbose_name='악보 있음'),
        ),
    ]
