from django.core.management.base import BaseCommand

from pracapp.views.demo_views import _ensure_demo_template_dataset


class Command(BaseCommand):
    help = 'Pre-generate and store demo template datasets for scenarios 1~3.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--scenarios',
            nargs='*',
            type=int,
            default=[1, 2, 3],
            help='Scenario numbers to prepare (default: 1 2 3).',
        )

    def handle(self, *args, **options):
        scenarios = options.get('scenarios') or [1, 2, 3]
        for scenario in scenarios:
            if scenario not in (1, 2, 3):
                self.stdout.write(self.style.WARNING(f'skip invalid scenario={scenario}'))
                continue
            band, meeting, _, songs, users, _, _ = _ensure_demo_template_dataset(scenario)
            self.stdout.write(
                self.style.SUCCESS(
                    f'prepared scenario={scenario} band={band.id} meeting={meeting.id} '
                    f'users={len(users)} songs={len(songs)}'
                )
            )
