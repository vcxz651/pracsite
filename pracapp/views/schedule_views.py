import calendar
import datetime
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Min, Max
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..models import (
    MemberAvailability,
    RecurringBlock,
)

from .. import utils


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

        # MemberAvailability(최종 확정) 기준으로 검사
        overlap_qs = MemberAvailability.objects.filter(
            user=request.user,
            date__range=[start, end]
        )

        if overlap_qs.exists():
            # 겹치면 무조건 거절 (정보 제공)
            min_date = overlap_qs.aggregate(Min('date'))['date__min']
            max_date = overlap_qs.aggregate(Max('date'))['date__max']
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

        # 세션에 기간 저장 (새로운 독립 스케줄)
        request.session['schedule_start'] = start_date
        request.session['schedule_end'] = end_date

        # 임시 데이터 초기화 (완전 백지에서 시작)
        request.session['temp_recurring'] = {}
        request.session['temp_oneoff'] = {}
        request.session['temp_exceptions'] = {}

        return redirect('schedule_recurring')

    return render(request, 'pracapp/schedule_step1.html')


@login_required
def schedule_recurring(request):
    start_str = request.session.get('schedule_start')
    end_str = request.session.get('schedule_end')
    if not start_str: return redirect('schedule_setup')

    # [POST] 세션에 임시 저장
    if request.method == 'POST':
        data = json.loads(request.body)
        # DB 저장(utils.save...) 대신 세션에 JSON 그대로 저장
        request.session['temp_recurring'] = data
        return JsonResponse({'status': 'success'})

    # [GET] 세션 데이터 불러오기
    # 방금 입력하던 게 있으면 그거 보여주고, 없으면 빈 깡통({}) 보여줌 (덮어쓰기니까)
    saved_data = request.session.get('temp_recurring', {})

    # 템플릿에 전달 (json.dumps 필요 없음, 이미 딕셔너리거나 JSON 호환)
    return render(request, 'pracapp/schedule_step2.html', {
        'saved_data': json.dumps(saved_data)
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

    context = {
        'start_date': request.session.get('schedule_start'),
        'end_date': request.session.get('schedule_end'),
        'recurring_data': json.dumps(temp_recurring),
        'oneoff_data': json.dumps(temp_oneoff),
        'exception_data': json.dumps(temp_exceptions),
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

    # [POST] 최종 저장 (Commit)
    if request.method == 'POST':
        # 1. 세션에서 데이터 꺼내기
        recurring_data = request.session.get('temp_recurring', {})
        oneoff_data = request.session.get('temp_oneoff', {})
        exc_data = request.session.get('temp_exceptions', {})

        utils.save_recurring_data(request.user, recurring_data, s_date, e_date)
        utils.save_oneoff_data(request.user, oneoff_data, s_date, e_date)  # 인자 순서 주의
        utils.save_exception_data(request.user, exc_data, s_date, e_date)  # 인자 순서 주의

        # 4. 최종 Availability 계산 및 저장
        utils.confirm_and_save_schedule(request.user, s_date, e_date)

        # 5. 세션 정리 (임시 데이터 삭제)
        for key in ['schedule_start', 'schedule_end', 'temp_recurring', 'temp_oneoff', 'temp_exceptions']:
            request.session.pop(key, None)

        return redirect('my_schedule')

    # [GET] 확정 전 확인 페이지 (DB가 아니라 세션 데이터를 보여줘야 함)

    temp_recurring = request.session.get('temp_recurring', {})
    temp_oneoff = request.session.get('temp_oneoff', {})
    temp_exceptions = request.session.get('temp_exceptions', {})

    fixed_grouped, all_exceptions = utils.get_schedule_summary(
        temp_recurring,
        temp_oneoff,
        temp_exceptions
    )

    return render(request, 'pracapp/schedule_confirm.html', {
        'start_date': start_str,
        'end_date': end_str,
        'fixed_schedules': fixed_grouped,
        'all_exceptions': all_exceptions
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


@login_required
def schedule_list(request):
    """
    [NEW] 스케줄 목록 페이지
    사용자가 등록한 '고정 스케줄'의 기간들을 그룹화해서 보여줍니다.
    """
    # 사용자의 고정 스케줄 블록들을 가져와서 '시작일/종료일' 끼리 묶습니다.
    # 예: (3/1~6/20), (7/1~8/31) 이렇게 독립된 덩어리들을 찾습니다.
    schedule_groups = RecurringBlock.objects.filter(user=request.user) \
        .values('start_date', 'end_date') \
        .distinct() \
        .order_by('start_date')

    # 템플릿에 전달할 데이터 가공
    schedules = []
    for grp in schedule_groups:
        s_date = grp['start_date']
        e_date = grp['end_date']

        if not s_date or not e_date:
            continue

        # 이름 예쁘게 (기간으로)
        title = f"{s_date.strftime('%Y.%m.%d')} ~ {e_date.strftime('%Y.%m.%d')}"

        # 해당 기간의 데이터가 맞는지 식별하기 위한 파라미터 생성
        schedules.append({
            'title': title,
            'start': s_date.strftime('%Y-%m-%d'),
            'end': e_date.strftime('%Y-%m-%d')
        })

    return render(request, 'pracapp/schedule_list.html', {'schedules': schedules})


# views.py (개선 후: 날씬한 뷰)
@login_required
def schedule_edit_loader(request):
    start_str = request.GET.get('start')
    end_str = request.GET.get('end')

    if not start_str or not end_str:
        return redirect('schedule_list')

    # ★ 뷰는 딱 한 줄로 명령만 내립니다. "가져올 거 다 가져와서 준비해!"
    session_data = utils.prepare_edit(request.user, start_str, end_str)

    # 뷰는 세션에 넣기만 합니다.
    for key, value in session_data.items():
        request.session[key] = value

    return redirect('schedule_recurring')
