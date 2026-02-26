from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from pracapp.models import Band

User = get_user_model()


class Command(BaseCommand):
    help = 'Remove stale demo datasets (bands/users) created for /demo flows.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Delete demo data older than N hours (default: 24).',
        )

    def handle(self, *args, **options):
        hours = max(1, int(options['hours'] or 24))
        cutoff = timezone.now() - timedelta(hours=hours)

        # 미팅이 없는 비정상/중단 생성 케이스도 누수 없이 정리한다.
        demo_band_qs = Band.objects.filter(
            name__startswith='[데모DB] 락스타즈-',
        ).filter(
            Q(meetings__created_at__lt=cutoff) | Q(meetings__isnull=True)
        ).distinct()
        demo_user_qs = User.objects.filter(
            username__startswith='demo_',
            date_joined__lt=cutoff,
        ).exclude(
            username__startswith='demo_cache_',
        )

        band_count = demo_band_qs.count()
        user_count = demo_user_qs.count()

        # Band 삭제가 Membership/Meeting 등은 cascade 정리한다.
        deleted_band_rows, _ = demo_band_qs.delete()
        # 데모 계정은 별도로 정리한다.
        deleted_user_rows, _ = demo_user_qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f'cleanup_demo_data: cutoff={cutoff.isoformat()} bands={band_count} users={user_count} '
                f'deleted_band_rows={deleted_band_rows} deleted_user_rows={deleted_user_rows}'
            )
        )
