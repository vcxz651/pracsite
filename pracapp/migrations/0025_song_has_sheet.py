from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pracapp', '0024_admin_practice_schedule_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='song',
            name='has_sheet',
            field=models.BooleanField(default=False, verbose_name='악보 있음'),
        ),
    ]
