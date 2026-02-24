import calendar
import datetime
import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..models import (
    MemberAvailability,
    OneOffBlock,
    RecurringBlock,
    RecurringException,
    SchedulePeriodPreset,
)

from .. import utils

logger = logging.getLogger(__name__)


def _build_university_period_presets(today: datetime.date):
    current_year = today.year
    previous_year = current_year - 1
    next_year = current_year + 1

    # 대한민국 대학 평균 학사일정 기준(대략치)
    # 1학기: 3월 초 ~ 6월 하순
    # 여름방학: 6월 하순 ~ 8월 말
    # 2학기: 9월 초 ~ 12월 중하순
    # 겨울방학: 12월 하순 ~ 익년 2월 말
    winter_start_year = previous_year if today.month <= 2 else current_year
    winter_end_year = current_year if today.month <= 2 else next_year

    winter_end_day = calendar.monthrange(winter_end_year, 2)[1]

    presets = [
        {
            'code': 'SEMESTER_1',
            'label': '1학기',
            'start': datetime.date(current_year, 3, 2),
            'end': datetime.date(current_year, 6, 21),
        },
        {
            'code': 'SUMMER_BREAK',
            'label': '여름방학',
            'start': datetime.date(current_year, 6, 22),
            'end': datetime.date(current_year, 8, 31),
        },
        {
            'code': 'SEMESTER_2',
            'label': '2학기',
            'start': datetime.date(current_year, 9, 1),
            'end': datetime.date(current_year, 12, 20),
        },
        {
            'code': 'WINTER_BREAK',
            'label': '겨울방학',
            'start': datetime.date(winter_start_year, 12, 21),
            'end': datetime.date(winter_end_year, 2, winter_end_day),
        },
        {
            'code': 'CUSTOM',
            'label': '직접 설정',
            'start': datetime.date(current_year, 7, 27),
            'end': datetime.date(current_year, 12, 25),
        },
    ]

    # 접속일 기준 시작일이 가장 가까운 프리셋을 기본 선택
    # 단, '기타(직접 설정)'는 디폴트 후보에서 제외
    default_candidates = [p for p in presets if p['code'] != 'CUSTOM']
    closest = min(
        default_candidates,
        key=lambda p: abs((p['start'] - today).days)
    )
    default_code = closest['code']

    serialized = [
        {
            'code': p['code'],
            'label': p['label'],
            'start': p['start'].isoformat(),
            'end': p['end'].isoformat(),
        }
        for p in presets
    ]
    return serialized, default_code


def _get_personal_schedule_overlap_range(user, start_date, end_date):
    overlap_min = None
    overlap_max = None

    def touch_range(s_date, e_date):
        nonlocal overlap_min, overlap_max
        if not s_date or not e_date:
            return
        left = max(s_date, start_date)
        right = min(e_date, end_date)
        if left > right:
            return
        overlap_min = left if overlap_min is None else min(overlap_min, left)
        overlap_max = right if overlap_max is None else max(overlap_max, right)

    recurring_qs = RecurringBlock.objects.filter(
        user=user,
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).values_list('start_date', 'end_date')
    for s_date, e_date in recurring_qs:
        touch_range(s_date, e_date)

    preset_qs = SchedulePeriodPreset.objects.filter(
        user=user,
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).values_list('start_date', 'end_date')
    for s_date, e_date in preset_qs:
        touch_range(s_date, e_date)

    oneoff_dates = OneOffBlock.objects.filter(
        user=user,
        is_generated=False,
        date__range=[start_date, end_date],
    ).values_list('date', flat=True)
    for d in oneoff_dates:
        touch_range(d, d)

    exception_dates = RecurringException.objects.filter(
        user=user,
        date__range=[start_date, end_date],
    ).values_list('date', flat=True)
    for d in exception_dates:
        touch_range(d, d)

    if overlap_min is None or overlap_max is None:
        return None
    return overlap_min, overlap_max


@login_required
def schedule_setup(request):
    """
    [엄격한 생성 모드]
    기존 일정과 단 하루라도 겹치면 아예 생성을 막습니다.
    """
    # [1] AJAX: 기간 중복 검사 (엄격 모드)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' and request.method == 'GET':
        start = request.GET.get('start')
        end = request.GET.get('end')

        try:
            start_date = datetime.date.fromisoformat(str(start))
            end_date = datetime.date.fromisoformat(str(end))
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': '유효하지 않은 날짜 형식입니다.'}, status=400)
        if end_date < start_date:
            return JsonResponse({'status': 'error', 'message': '종료일이 시작일보다 빠릅니다.'}, status=400)

        overlap_range = _get_personal_schedule_overlap_range(request.user, start_date, end_date)

        if overlap_range:
            min_date, max_date = overlap_range
            min_str = f"{min_date.month}월 {min_date.day}일"
            max_str = f"{max_date.month}월 {max_date.day}일"

            return JsonResponse({
                'status': 'conflict',
                # "덮어쓰기" 제안 대신 "수정 페이지" 안내
                'message': (
                    f"해당 기간에 이미 등록된 일정이 있습니다.<br>"
                    f"<b>({min_str} ~ {max_str})</b><br><br>"
                    f"기존 일정을 변경하시려면<br>"
                    f"<b>[내 시간표 수정]</b> 메뉴를 이용해주세요."
                )
            })
        else:
            return JsonResponse({'status': 'ok'})

    # [2] POST: 세션 초기화 및 이동
    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        preset_code = request.POST.get('preset_code') or SchedulePeriodPreset.PRESET_CUSTOM

        # 세션에 기간 저장 (새로운 독립 스케줄)
        request.session['schedule_start'] = start_date
        request.session['schedule_end'] = end_date
        request.session['schedule_preset_code'] = preset_code
        request.session['schedule_readonly'] = False
        request.session['schedule_view_label'] = ''

        # 임시 데이터 초기화 (완전 백지에서 시작)
        request.session['temp_recurring'] = {}
        request.session['temp_recurring_additional'] = []
        request.session['temp_oneoff'] = {}
        request.session['temp_exceptions'] = {}

        return redirect('schedule_recurring')

    today = datetime.date.today()
    presets, default_preset_code = _build_university_period_presets(today)
    return render(request, 'pracapp/schedule_step1.html', {
        'period_presets_json': json.dumps(presets),
        'default_preset_code': default_preset_code,
    })


@login_required
def schedule_delete(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식입니다.'}, status=400)

    start_raw = payload.get('start')
    end_raw = payload.get('end')

    try:
        start_date = datetime.date.fromisoformat(str(start_raw))
        end_date = datetime.date.fromisoformat(str(end_raw))
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': '유효하지 않은 날짜 형식입니다.'}, status=400)

    if end_date < start_date:
        return JsonResponse({'status': 'error', 'message': '종료일이 시작일보다 빠릅니다.'}, status=400)

    with transaction.atomic():
        # 기간 단위 삭제: 프리셋(정확히 일치), 개인 시간표 데이터(해당 기간 내)
        preset_deleted = SchedulePeriodPreset.objects.filter(
            user=request.user,
            start_date=start_date,
            end_date=end_date,
        ).delete()[0]

        recurring_deleted = RecurringBlock.objects.filter(
            user=request.user,
            start_date__gte=start_date,
            end_date__lte=end_date,
        ).delete()[0]

        oneoff_deleted = OneOffBlock.objects.filter(
            user=request.user,
            date__range=[start_date, end_date],
            is_generated=False,
        ).delete()[0]

        exception_deleted = RecurringException.objects.filter(
            user=request.user,
            date__range=[start_date, end_date],
        ).delete()[0]

        # 삭제 후 해당 기간의 가용성 재계산
        refreshed = utils.calculate_user_schedule(request.user, start_date, end_date)
        for d_str, slots in refreshed.items():
            MemberAvailability.objects.update_or_create(
                user=request.user,
                date=d_str,
                defaults={'available_slot': slots},
            )

    logger.info(
        "schedule_delete user=%s start=%s end=%s preset=%s recurring=%s oneoff=%s exception=%s",
        request.user.id,
        start_date,
        end_date,
        preset_deleted,
        recurring_deleted,
        oneoff_deleted,
        exception_deleted,
    )

    return JsonResponse({'status': 'success'})


@login_required
def schedule_recurring(request):
    start_str = request.session.get('schedule_start')
    end_str = request.session.get('schedule_end')
    if not start_str: return redirect('schedule_setup')

    # [POST] 세션에 임시 저장
    if request.method == 'POST':
        data = json.loads(request.body)
        # 하위호환: 구형 payload(dict day->blocks)와 신형 payload(base+additional) 모두 수용
        if isinstance(data, dict) and ('base' in data or 'additional_periods' in data):
            request.session['temp_recurring'] = data.get('base', {}) or {}
            request.session['temp_recurring_additional'] = data.get('additional_periods', []) or []
        else:
            request.session['temp_recurring'] = data
            request.session['temp_recurring_additional'] = []
        return JsonResponse({'status': 'success'})

    # [GET] 세션 데이터 불러오기
    # 방금 입력하던 게 있으면 그거 보여주고, 없으면 빈 깡통({}) 보여줌 (덮어쓰기니까)
    saved_data = request.session.get('temp_recurring', {})

    # 템플릿에 전달 (json.dumps 필요 없음, 이미 딕셔너리거나 JSON 호환)
    return render(request, 'pracapp/schedule_step2.html', {
        'saved_data': json.dumps(saved_data),
        'saved_additional_periods': json.dumps(request.session.get('temp_recurring_additional', [])),
        'schedule_start': start_str,
        'schedule_end': end_str,
    })


@login_required
def schedule_oneoff(request):
    start_str = request.session.get('schedule_start')

    # [POST] 세션에 임시 저장
    if request.method == 'POST':
        data = json.loads(request.body)
        request.session['temp_oneoff'] = data.get('oneoff', {})
        request.session['temp_exceptions'] = data.get('exceptions', {})
        return JsonResponse({'status': 'success'})

    # [GET] 화면 표시
    # 여기서는 '시각적 참조'를 위해 Recurring은 세션에서 가져오고,
    # OneOff/Exception은 작업 중이던 세션 데이터를 가져옵니다.

    # 1. 현재 작업 중인 Recurring 데이터 (시각화용)
    temp_recurring = request.session.get('temp_recurring', {})

    # 2. 현재 작업 중인 OneOff/Exception 데이터
    temp_oneoff = request.session.get('temp_oneoff', {})
    temp_exceptions = request.session.get('temp_exceptions', {})
    temp_recurring_additional = request.session.get('temp_recurring_additional', [])

    context = {
        'start_date': request.session.get('schedule_start'),
        'end_date': request.session.get('schedule_end'),
        'recurring_data': json.dumps(temp_recurring),
        'recurring_additional_periods': json.dumps(temp_recurring_additional),
        'oneoff_data': json.dumps(temp_oneoff),
        'exception_data': json.dumps(temp_exceptions),
        'schedule_readonly': bool(request.session.get('schedule_readonly', False)),
        'schedule_view_label': (request.session.get('schedule_view_label') or '').strip(),
    }
    return render(request, 'pracapp/schedule_step3.html', context)

### 수정 1순위 : GET도 유틸에서 처리할 것 ###
@login_required
def schedule_confirm(request):
    start_str = request.session.get('schedule_start')
    end_str = request.session.get('schedule_end')
    if not start_str: return redirect('schedule_setup')

    s_date = datetime.datetime.strptime(start_str, "%Y-%m-%d").date()
    e_date = datetime.datetime.strptime(end_str, "%Y-%m-%d").date()
    schedule_readonly = bool(request.session.get('schedule_readonly', False))
    schedule_view_label = (request.session.get('schedule_view_label') or '').strip()

    # [POST] 최종 저장 (Commit)
    if request.method == 'POST':
        if schedule_readonly:
            return redirect('schedule_confirm')
        # 1. 세션에서 데이터 꺼내기
        recurring_data = request.session.get('temp_recurring', {})
        recurring_additional = request.session.get('temp_recurring_additional', [])
        oneoff_data = request.session.get('temp_oneoff', {})
        exc_data = request.session.get('temp_exceptions', {})

        utils.save_recurring_data(
            request.user,
            recurring_data,
            s_date,
            e_date,
            additional_periods=recurring_additional,
        )
        utils.save_oneoff_data(request.user, oneoff_data, s_date, e_date)  # 인자 순서 주의
        utils.save_exception_data(request.user, exc_data, s_date, e_date)  # 인자 순서 주의

        # 4. 최종 Availability 계산 및 저장
        utils.confirm_and_save_schedule(request.user, s_date, e_date)

        preset_code = request.session.get('schedule_preset_code') or SchedulePeriodPreset.PRESET_CUSTOM
        valid_codes = {code for code, _ in SchedulePeriodPreset.PRESET_CHOICES}
        if preset_code not in valid_codes:
            preset_code = SchedulePeriodPreset.PRESET_CUSTOM
        SchedulePeriodPreset.objects.update_or_create(
            user=request.user,
            start_date=s_date,
            end_date=e_date,
            defaults={'preset_code': preset_code},
        )

        # 5. 세션 정리 (임시 데이터 삭제)
        for key in [
            'schedule_start', 'schedule_end', 'schedule_preset_code',
            'schedule_readonly', 'schedule_view_label',
            'temp_recurring', 'temp_recurring_additional', 'temp_oneoff', 'temp_exceptions'
        ]:
            request.session.pop(key, None)

        return redirect('my_schedule')

    # [GET] 확정 전 확인 페이지 (DB가 아니라 세션 데이터를 보여줘야 함)

    temp_recurring = request.session.get('temp_recurring', {})
    temp_recurring_additional = request.session.get('temp_recurring_additional', [])
    temp_oneoff = request.session.get('temp_oneoff', {})
    temp_exceptions = request.session.get('temp_exceptions', {})

    fixed_grouped, special_period_grouped, all_exceptions = utils.get_schedule_summary(
        temp_recurring,
        temp_oneoff,
        temp_exceptions,
        additional_periods=temp_recurring_additional,
    )

    return render(request, 'pracapp/schedule_confirm.html', {
        'start_date': start_str,
        'end_date': end_str,
        'fixed_schedules': fixed_grouped,
        'special_period_schedules': special_period_grouped,
        'all_exceptions': all_exceptions,
        'schedule_readonly': schedule_readonly,
        'schedule_view_label': schedule_view_label,
    })


@login_required
def my_schedule(request):
    """ 내 시간표 보기 (월별 달력 + Busy 사유 표시) """

    today = datetime.date.today()

    try:
        current_year = int(request.GET.get('year', today.year))
        current_month = int(request.GET.get('month', today.month))
    except ValueError:
        current_year = today.year
        current_month = today.month

    _, last_day = calendar.monthrange(current_year, current_month)
    month_start = datetime.date(current_year, current_month, 1)
    month_end = datetime.date(current_year, current_month, last_day)

    # 1. 가능한 시간 (초록색 렌더링용) - 기존 로직 유지
    timeline_data = utils.calculate_user_schedule(
        request.user,
        month_start,
        month_end,
        include_generated_oneoff=True,
    )

    # 2. 불가능한 시간 (회색 렌더링 + 사유 표시용) - NEW!
    busy_data = utils.get_busy_events(request.user, month_start, month_end)

    prev_month_date = month_start - datetime.timedelta(days=1)
    next_month_date = month_end + datetime.timedelta(days=1)

    context = {
        'current_year': current_year,
        'current_month': current_month,
        'start_date': month_start.strftime("%Y-%m-%d"),
        'end_date': month_end.strftime("%Y-%m-%d"),
        'timeline_data': json.dumps(timeline_data),
        'busy_data': json.dumps(busy_data),  # 템플릿으로 전달
        'prev_year': prev_month_date.year,
        'prev_month': prev_month_date.month,
        'next_year': next_month_date.year,
        'next_month': next_month_date.month,
        'no_data': False
    }

    return render(request, 'pracapp/my_schedule.html', context)


# views.py (개선 후: 날씬한 뷰)
@login_required
def schedule_edit_loader(request):
    start_str = request.GET.get('start')
    end_str = request.GET.get('end')

    if not start_str or not end_str:
        return redirect('home')

    # ★ 뷰는 딱 한 줄로 명령만 내립니다. "가져올 거 다 가져와서 준비해!"
    session_data = utils.prepare_edit(request.user, start_str, end_str)

    # 뷰는 세션에 넣기만 합니다.
    for key, value in session_data.items():
        request.session[key] = value

    preset = SchedulePeriodPreset.objects.filter(
        user=request.user,
        start_date=start_str,
        end_date=end_str,
    ).values_list('preset_code', flat=True).first()
    request.session['schedule_preset_code'] = preset or SchedulePeriodPreset.PRESET_CUSTOM
    request.session['schedule_readonly'] = request.GET.get('readonly') == '1'
    request.session['schedule_view_label'] = (request.GET.get('view_label') or '').strip()

    next_step = (request.GET.get('next') or '').strip().lower()
    if next_step == 'oneoff':
        return redirect('schedule_oneoff')
    if next_step == 'confirm':
        return redirect('schedule_confirm')
    return redirect('schedule_recurring')
