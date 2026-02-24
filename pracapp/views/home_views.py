# pracapp/views/home_views.py

import calendar
import datetime

from django.contrib import messages
from django.views.generic import TemplateView

from pracapp.models import Band, Membership, RecurringBlock, SchedulePeriodPreset

PRESET_LABELS = {
    SchedulePeriodPreset.PRESET_SEMESTER_1: '1학기',
    SchedulePeriodPreset.PRESET_SUMMER_BREAK: '여름방학',
    SchedulePeriodPreset.PRESET_SEMESTER_2: '2학기',
    SchedulePeriodPreset.PRESET_WINTER_BREAK: '겨울방학',
}


def _format_period_kor_short(start_date: datetime.date, end_date: datetime.date) -> str:
    start_year = str(start_date.year)[-2:]
    end_year = str(end_date.year)[-2:]
    start_text = f'{start_year}년 {start_date.month}월 {start_date.day}일'
    if start_date.year == end_date.year:
        return f'{start_text} ~ {end_date.month}월 {end_date.day}일'
    return f'{start_text} ~ {end_year}년 {end_date.month}월 {end_date.day}일'


def _build_preset_candidates(base_year: int):
    winter_end_day = calendar.monthrange(base_year + 1, 2)[1]
    return [
        ('1학기', datetime.date(base_year, 3, 2), datetime.date(base_year, 6, 21)),
        ('여름방학', datetime.date(base_year, 6, 22), datetime.date(base_year, 8, 31)),
        ('2학기', datetime.date(base_year, 9, 1), datetime.date(base_year, 12, 20)),
        ('겨울방학', datetime.date(base_year, 12, 21), datetime.date(base_year + 1, 2, winter_end_day)),
    ]


def _resolve_schedule_display_label(start_date: datetime.date, end_date: datetime.date) -> str:
    candidate_years = {start_date.year - 1, start_date.year, start_date.year + 1, end_date.year}
    for year in sorted(candidate_years):
        for label, p_start, p_end in _build_preset_candidates(year):
            if start_date == p_start and end_date == p_end:
                return label
    return _format_period_kor_short(start_date, end_date)


def _resolve_schedule_display_label_with_saved_preset(user, start_date, end_date):
    preset_code = SchedulePeriodPreset.objects.filter(
        user=user,
        start_date=start_date,
        end_date=end_date,
    ).values_list('preset_code', flat=True).first()
    if preset_code in PRESET_LABELS:
        return PRESET_LABELS[preset_code]
    return _resolve_schedule_display_label(start_date, end_date)


def _pick_primary_schedule_range(user):
    ranges = list(
        RecurringBlock.objects.filter(user=user)
        .values('start_date', 'end_date')
        .distinct()
    )
    if not ranges:
        return None

    today = datetime.date.today()

    containing = [
        r for r in ranges
        if r['start_date'] and r['end_date'] and r['start_date'] <= today <= r['end_date']
    ]
    if containing:
        return sorted(containing, key=lambda r: r['start_date'], reverse=True)[0]

    valid_ranges = [r for r in ranges if r['start_date'] and r['end_date']]
    if not valid_ranges:
        return None
    return min(valid_ranges, key=lambda r: abs((r['start_date'] - today).days))


def _build_schedule_cards(user):
    # 홈 목록은 "기간 스케줄(프리셋 저장 단위)"만 노출한다.
    # 특수 기간 고정 일정(추가 recurring 범위)은 카드로 분리 노출하지 않음.
    preset_ranges = list(
        SchedulePeriodPreset.objects.filter(user=user)
        .values('start_date', 'end_date')
        .distinct()
    )

    valid_ranges = [
        {'start_date': r['start_date'], 'end_date': r['end_date']}
        for r in preset_ranges
        if r.get('start_date') and r.get('end_date')
    ]
    valid_ranges.sort(key=lambda r: (r['start_date'], r['end_date']), reverse=True)

    cards = []
    for r in valid_ranges:
        start_date = r['start_date']
        end_date = r['end_date']
        cards.append({
            'start_date': start_date,
            'end_date': end_date,
            'start_str': start_date.strftime('%Y-%m-%d'),
            'end_str': end_date.strftime('%Y-%m-%d'),
            'label': _resolve_schedule_display_label_with_saved_preset(user, start_date, end_date),
            'period_text': _format_period_kor_short(start_date, end_date),
        })
    return cards


class HomeView(TemplateView):
    template_name = 'pracapp/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        if user.is_authenticated:
            pending_notice_qs = Membership.objects.filter(
                user=user,
                is_approved=True,
                approval_notified=False,
                role='MEMBER',
            ).select_related('band')
            pending_notices = list(pending_notice_qs)
            for membership in pending_notices:
                messages.success(
                    self.request,
                    f"[{membership.band.name}] 가입이 승인되었습니다."
                )
            if pending_notices:
                Membership.objects.filter(
                    id__in=[m.id for m in pending_notices]
                ).update(approval_notified=True)

            my_band_qs = Band.objects.filter(
                memberships__user=user,
                memberships__is_approved=True
            ).distinct().order_by('name')
            context['my_band'] = my_band_qs
            schedule_cards = _build_schedule_cards(user)
            context['schedule_cards'] = schedule_cards
            context['has_schedule'] = bool(schedule_cards)
            context['schedule_display_label'] = schedule_cards[0]['label'] if schedule_cards else None
            context['editable_band_ids'] = set(
                Membership.objects.filter(
                    user=user,
                    is_approved=True,
                    role__in=['LEADER', 'MANAGER'],
                ).values_list('band_id', flat=True)
            )

        else:
            context['my_band'] = None
            context['has_schedule'] = False
            context['schedule_cards'] = []
            context['schedule_display_label'] = None
            context['editable_band_ids'] = set()

        return context
