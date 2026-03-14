# pracapp/views/home_views.py

import calendar
import datetime
from collections import defaultdict
import os

from django.contrib import messages
from django.views.generic import TemplateView

from pracapp.models import (
    Band, Membership, RecurringBlock, SchedulePeriodPreset,
    Session, PracticeSchedule, ExtraPracticeSchedule,
    OneOffBlock, RecurringException,
)

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


def _resolve_today_override(request):
    def _parse_flexible_date(raw_value: str):
        value = (raw_value or '').strip()
        if not value:
            return None
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            pass

        normalized = value.replace('.', '-').replace('/', '-')
        parts = [p.strip() for p in normalized.split('-') if p.strip()]
        if len(parts) == 3:
            try:
                y, m, d = (int(parts[0]), int(parts[1]), int(parts[2]))
                return datetime.date(y, m, d)
            except (TypeError, ValueError):
                return None
        if len(parts) == 2:
            today = datetime.date.today()
            try:
                m, d = (int(parts[0]), int(parts[1]))
                return datetime.date(today.year, m, d)
            except (TypeError, ValueError):
                return None
        return None

    param_keys = ('today', 'mock_today', 'override_today')
    query_raw = ''
    query_key_used = ''
    for key in param_keys:
        v = (request.GET.get(key) or '').strip()
        if v:
            query_raw = v
            query_key_used = key
            break

    # 명시적으로 해제: ?today=off | clear | 0
    if query_key_used and query_raw.lower() in {'off', 'clear', '0'}:
        request.session.pop('home_today_override', None)
        return datetime.date.today(), ''

    # 쿼리 값이 있으면 우선 적용 + 세션 저장
    if query_key_used:
        parsed = _parse_flexible_date(query_raw)
        if parsed is None:
            request.session.pop('home_today_override', None)
            return datetime.date.today(), ''
        request.session['home_today_override'] = query_raw
        return parsed, query_raw

    # 세션 오버라이드가 있으면 유지
    session_raw = (request.session.get('home_today_override') or '').strip()
    if session_raw:
        parsed = _parse_flexible_date(session_raw)
        if parsed is not None:
            return parsed, session_raw
        else:
            request.session.pop('home_today_override', None)

    raw = (os.environ.get('HOME_TODAY_OVERRIDE') or '').strip()
    if not raw:
        return datetime.date.today(), ''
    parsed = _parse_flexible_date(raw)
    if parsed is None:
        return datetime.date.today(), ''
    return parsed, raw


def _build_my_week_rehearsals(user, today=None):
    base_date = today or datetime.date.today()
    monday = base_date - datetime.timedelta(days=base_date.weekday())
    sunday = monday + datetime.timedelta(days=6)
    weekday_kor = ['월', '화', '수', '목', '금', '토', '일']

    my_song_ids = list(
        Session.objects.filter(assignee=user).values_list('song_id', flat=True).distinct()
    )
    if not my_song_ids:
        return {
            'week_start': monday,
            'week_end': sunday,
            'items': [],
        }

    items = []
    regular_qs = (
        PracticeSchedule.objects.filter(
            song_id__in=my_song_ids,
            date__range=[monday, sunday],
        )
        .select_related('meeting', 'meeting__band', 'song', 'room')
        .order_by('date', 'start_index', 'meeting__title', 'song__title')
    )
    for ps in regular_qs:
        d = ps.date
        items.append({
            'kind': '정규',
            'meeting_title': ps.meeting.title,
            'song_title': ps.song.title,
            'song_artist': ps.song.artist,
            'room_name': ps.room.name,
            'date_text': f"{d.month}/{d.day}({weekday_kor[d.weekday()]})",
            'time_text': f"{int(ps.start_index // 2):02d}:{'30' if ps.start_index % 2 else '00'}~{int(ps.end_index // 2):02d}:{'30' if ps.end_index % 2 else '00'}",
            'sort_date': d,
            'sort_start': int(ps.start_index),
        })

    extra_qs = (
        ExtraPracticeSchedule.objects.filter(
            song_id__in=my_song_ids,
            date__range=[monday, sunday],
        )
        .select_related('meeting', 'song', 'room')
        .order_by('date', 'start_index', 'meeting__title', 'song__title')
    )
    for eps in extra_qs:
        d = eps.date
        items.append({
            'kind': '추가',
            'meeting_title': eps.meeting.title,
            'song_title': eps.song.title,
            'song_artist': eps.song.artist,
            'room_name': eps.room.name,
            'date_text': f"{d.month}/{d.day}({weekday_kor[d.weekday()]})",
            'time_text': f"{int(eps.start_index // 2):02d}:{'30' if eps.start_index % 2 else '00'}~{int(eps.end_index // 2):02d}:{'30' if eps.end_index % 2 else '00'}",
            'sort_date': d,
            'sort_start': int(eps.start_index),
        })

    items.sort(key=lambda x: (x['sort_date'], x['sort_start'], x['meeting_title'], x['song_title']))
    return {
        'week_start': monday,
        'week_end': sunday,
        'items': items,
    }


def _build_my_week_rehearsal_board(user, today=None, include_personal_blocks=True):
    base_date = today or datetime.date.today()
    monday = base_date - datetime.timedelta(days=base_date.weekday())
    sunday = monday + datetime.timedelta(days=6)
    weekday_kor = ['월', '화', '수', '목', '금', '토', '일']

    my_song_ids = list(
        Session.objects.filter(assignee=user).values_list('song_id', flat=True).distinct()
    )

    rows_by_date = defaultdict(list)

    if my_song_ids:
        regular_qs = (
            PracticeSchedule.objects.filter(
                song_id__in=my_song_ids,
                date__range=[monday, sunday],
            )
            .select_related('meeting', 'song', 'room')
            .order_by('date', 'start_index', 'meeting__title', 'song__title')
        )
        for ps in regular_qs:
            rows_by_date[ps.date].append({
                'kind': '정규',
                'start': int(ps.start_index),
                'end': int(ps.end_index),
                'song_title': ps.song.title,
                'song_artist': ps.song.artist,
                'band_name': ps.meeting.band.name,
                'meeting_title': ps.meeting.title,
                'room_name': ps.room.name,
            })

        extra_qs = (
            ExtraPracticeSchedule.objects.filter(
                song_id__in=my_song_ids,
                date__range=[monday, sunday],
            )
            .select_related('meeting', 'meeting__band', 'song', 'room')
            .order_by('date', 'start_index', 'meeting__title', 'song__title')
        )
        for eps in extra_qs:
            rows_by_date[eps.date].append({
                'kind': '추가',
                'start': int(eps.start_index),
                'end': int(eps.end_index),
                'song_title': eps.song.title,
                'song_artist': eps.song.artist,
                'band_name': eps.meeting.band.name,
                'meeting_title': eps.meeting.title,
                'room_name': eps.room.name,
            })

    personal_ranges_by_date = defaultdict(list)
    if include_personal_blocks:
        # 개인 일정(고정/단발) 블록 계산
        personal_reasons_by_date_slot = defaultdict(lambda: defaultdict(set))
        recurring_qs = (
            RecurringBlock.objects.filter(
                user=user,
                start_date__lte=sunday,
                end_date__gte=monday,
            )
            .order_by('day_of_week', 'start_index', 'end_index')
        )
        oneoff_qs = (
            OneOffBlock.objects.filter(
                user=user,
                date__range=[monday, sunday],
                is_generated=False,
            )
            .order_by('date', 'start_index', 'end_index')
        )
        exc_qs = (
            RecurringException.objects.filter(
                user=user,
                date__range=[monday, sunday],
            )
            .order_by('date', 'start_index', 'end_index')
        )

        exc_payload_by_date = defaultdict(lambda: {'slots': set(), 'targeted': []})
        for ex in exc_qs:
            d_key = ex.date
            target_payload = ex.target_payload or {}
            if isinstance(target_payload, dict) and target_payload:
                exc_payload_by_date[d_key]['targeted'].append({
                    'start': int(ex.start_index),
                    'end': int(ex.end_index),
                    'target': target_payload,
                })
            else:
                for slot in range(int(ex.start_index), int(ex.end_index)):
                    exc_payload_by_date[d_key]['slots'].add(int(slot))

        recurring_by_weekday = defaultdict(list)
        for rb in recurring_qs:
            recurring_by_weekday[int(rb.day_of_week)].append(rb)

        def _target_matches_block(target, block):
            if not isinstance(target, dict):
                return False
            try:
                t_day = int(target.get('day_of_week'))
                t_start = int(target.get('start'))
                t_end = int(target.get('end'))
            except (TypeError, ValueError):
                return False
            t_reason = str(target.get('reason') or '').strip()
            t_scope_start = str(target.get('scope_start') or '')
            t_scope_end = str(target.get('scope_end') or '')
            return (
                t_day == int(block.day_of_week)
                and t_start == int(block.start_index)
                and t_end == int(block.end_index)
                and t_reason == str(block.reason or '').strip()
                and t_scope_start == str((block.start_date or '').isoformat() if block.start_date else '')
                and t_scope_end == str((block.end_date or '').isoformat() if block.end_date else '')
            )

        def _is_recurring_slot_cancelled(date_value, block, slot):
            payload = exc_payload_by_date.get(date_value, {'slots': set(), 'targeted': []})
            if int(slot) in payload['slots']:
                return True
            for row in payload['targeted']:
                start = int(row.get('start', -1))
                end = int(row.get('end', -1))
                if not (start <= int(slot) < end):
                    continue
                if _target_matches_block(row.get('target') or {}, block):
                    return True
            return False

        for i in range(7):
            d = monday + datetime.timedelta(days=i)
            day_idx = int(d.weekday())
            for rb in recurring_by_weekday.get(day_idx, []):
                if not (rb.start_date and rb.end_date and rb.start_date <= d <= rb.end_date):
                    continue
                reason_text = str(rb.reason or '').strip() or '개인 일정'
                for slot in range(int(rb.start_index), int(rb.end_index)):
                    if _is_recurring_slot_cancelled(d, rb, slot):
                        continue
                    personal_reasons_by_date_slot[d][int(slot)].add(reason_text)

        for ob in oneoff_qs:
            reason_text = str(ob.reason or '').strip() or '개인 일정'
            for slot in range(int(ob.start_index), int(ob.end_index)):
                personal_reasons_by_date_slot[ob.date][int(slot)].add(reason_text)

        for d_key, slot_reason_map in personal_reasons_by_date_slot.items():
            sorted_slots = sorted(set(int(s) for s in slot_reason_map.keys()))
            if not sorted_slots:
                continue

            def _slot_reason_text(slot_value):
                reasons = sorted(
                    set(str(r).strip() for r in slot_reason_map.get(int(slot_value), set()) if str(r).strip())
                )
                if not reasons:
                    return '개인 일정'
                return ', '.join(reasons)

            start = sorted_slots[0]
            prev = start
            current_reason_text = _slot_reason_text(start)
            for s in sorted_slots[1:]:
                next_reason_text = _slot_reason_text(s)
                if s == prev + 1 and next_reason_text == current_reason_text:
                    prev = s
                    continue
                personal_ranges_by_date[d_key].append((start, prev + 1, current_reason_text))
                start = s
                prev = s
                current_reason_text = next_reason_text
            personal_ranges_by_date[d_key].append((start, prev + 1, current_reason_text))

    if rows_by_date:
        min_start = None
        max_end = None
        for _date_key, row_list in rows_by_date.items():
            for row in row_list:
                s = int(row.get('start', 18))
                e = int(row.get('end', s + 1))
                min_start = s if min_start is None else min(min_start, s)
                max_end = e if max_end is None else max(max_end, e)
        if include_personal_blocks:
            for _date_key, ranges in personal_ranges_by_date.items():
                for s, e, _reason_text in ranges:
                    min_start = s if min_start is None else min(min_start, int(s))
                    max_end = e if max_end is None else max(max_end, int(e))
        slot_start = min_start if min_start is not None else 18
        slot_end = max_end if max_end is not None else 48
    elif include_personal_blocks:
        # 합주가 없더라도 개인 일정이 있으면 해당 범위로 렌더링
        min_start = None
        max_end = None
        for _date_key, ranges in personal_ranges_by_date.items():
            for s, e, _reason_text in ranges:
                min_start = s if min_start is None else min(min_start, int(s))
                max_end = e if max_end is None else max(max_end, int(e))
        slot_start = min_start if min_start is not None else 18
        slot_end = max_end if max_end is not None else 48
    else:
        slot_start = 18
        slot_end = 48

    slot_start = max(18, min(47, int(slot_start)))
    slot_end = max(slot_start + 1, min(48, int(slot_end)))
    slot_count = slot_end - slot_start
    time_rows = []
    for slot in range(slot_start, slot_end + 1):
        label = ''
        if slot % 2 == 0:
            h = slot // 2
            label = f'{h:02d}:00'
        time_rows.append({'slot': slot, 'label': label})

    days = []
    total_events = 0
    total_personal_blocks = 0
    for i in range(7):
        d = monday + datetime.timedelta(days=i)
        date_rows = rows_by_date.get(d, [])
        date_rows.sort(key=lambda x: (x['start'], x['end'], x['song_title'], x['meeting_title']))

        lane_ends = []
        for row in date_rows:
            lane_idx = -1
            for idx, lane_end in enumerate(lane_ends):
                if lane_end <= row['start']:
                    lane_idx = idx
                    lane_ends[idx] = row['end']
                    break
            if lane_idx < 0:
                lane_idx = len(lane_ends)
                lane_ends.append(row['end'])
            row['lane_index'] = lane_idx
        lane_count = max(1, len(lane_ends))

        events = []
        for row in date_rows:
            start = max(slot_start, min(slot_end, int(row['start'])))
            end = max(start + 1, min(slot_end, int(row['end'])))
            if end <= slot_start or start >= slot_end:
                continue
            events.append({
                'kind': row['kind'],
                'song_title': row['song_title'],
                'song_artist': row['song_artist'],
                'band_name': row['band_name'],
                'meeting_title': row['meeting_title'],
                'room_name': row['room_name'],
                'top_slots': start - slot_start,
                'span_slots': max(1, end - start),
                'lane_index': int(row.get('lane_index', 0)),
                'lane_count': lane_count,
                'time_text': f"{int(start // 2):02d}:{'30' if start % 2 else '00'}~{int(end // 2):02d}:{'30' if end % 2 else '00'}",
            })

        personal_blocks = []
        for p_start, p_end, p_reason_text in personal_ranges_by_date.get(d, []):
            start = max(slot_start, min(slot_end, int(p_start)))
            end = max(start + 1, min(slot_end, int(p_end)))
            if end <= slot_start or start >= slot_end:
                continue
            personal_blocks.append({
                'top_slots': start - slot_start,
                'span_slots': max(1, end - start),
                'reason_text': str(p_reason_text or '').strip() or '개인 일정',
            })

        total_events += len(events)
        total_personal_blocks += len(personal_blocks)
        days.append({
            'date': d,
            'date_text': f"{d.month}/{d.day}({weekday_kor[d.weekday()]})",
            'is_today': d == base_date,
            'events': events,
            'personal_blocks': personal_blocks,
        })

    has_events = (total_events + total_personal_blocks) > 0 if include_personal_blocks else (total_events > 0)
    return {
        'week_start': monday,
        'week_end': sunday,
        'slot_start': slot_start,
        'slot_end': slot_end,
        'slot_count': slot_count,
        'time_rows': time_rows,
        'days': days,
        'has_events': has_events,
    }


class HomeView(TemplateView):
    template_name = 'pracapp/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today_ref, today_override_raw = _resolve_today_override(self.request)
        context['today_override'] = today_override_raw
        context['show_intro_video_modal'] = bool(
            user.is_authenticated and self.request.session.pop('show_intro_video_modal', False)
        )

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
            my_week_rehearsals = _build_my_week_rehearsals(user, today=today_ref)
            context['my_week_rehearsals'] = my_week_rehearsals['items']
            context['my_week_start'] = my_week_rehearsals['week_start']
            context['my_week_end'] = my_week_rehearsals['week_end']
            my_week_board = _build_my_week_rehearsal_board(user, today=today_ref, include_personal_blocks=True)
            context['my_week_board'] = my_week_board
            context['my_week_board_event_only'] = _build_my_week_rehearsal_board(
                user,
                today=today_ref,
                include_personal_blocks=False,
            )
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
            context['my_week_rehearsals'] = []
            context['my_week_start'] = None
            context['my_week_end'] = None
            context['my_week_board'] = None
            context['my_week_board_event_only'] = None
            context['editable_band_ids'] = set()

        return context
