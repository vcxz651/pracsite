from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0015_recurringexception_reason_alter_oneoffblock_reason_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='oneoffblock',
            name='is_generated',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='oneoffblock',
            name='source_meeting',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='generated_oneoff_blocks', to='pracapp.meeting'),
        ),
        migrations.AddField(
            model_name='oneoffblock',
            name='source_song',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='generated_oneoff_blocks', to='pracapp.song'),
        ),
    ]
