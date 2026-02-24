import datetime
import json
import uuid
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, render

from ..models import (
    Meeting, Song, Session, PracticeRoom, PracticeSchedule,
    ExtraPracticeSchedule, RoomBlock, MemberAvailability,
)
from ..utils import _build_user_unavailable_reason_map, _session_abbr
from ._meeting_common import (
    available_rooms_qs as common_available_rooms_qs,
    has_meeting_manager_permission,
    get_approved_membership,
)


# ──────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────

def _is_song_participant_or_manager(meeting, song, user):
    """해당 곡의 세션 배정자(assignee)이거나 미팅 관리자이면 True."""
    is_manager = has_meeting_manager_permission(meeting, user)
    if is_manager:
        return True
    return Session.objects.filter(song=song, assignee=user).exists()


def _week_bounds(week_offset: int):
    """오늘 기준 week_offset 주 후의 월~일 반환."""
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(weeks=week_offset)
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday


def _default_week_offset(meeting) -> int:
    """
    기존 합주 일정(PracticeSchedule)이 있는 주를 기본 오프셋으로 반환.
    없으면 practice_start_date, 없으면 0(오늘 주).
    """
    today = datetime.date.today()
    monday_today = today - datetime.timedelta(days=today.weekday())

    def _offset_for_date(d: datetime.date) -> int:
        monday = d - datetime.timedelta(days=d.weekday())
        return (monday - monday_today).days // 7

    # 1. 가장 가까운 PracticeSchedule 날짜 (오늘 이후 우선, 없으면 가장 최근)
    qs = PracticeSchedule.objects.filter(meeting=meeting).order_by('date')
    upcoming = qs.filter(date__gte=today).first()
    if upcoming:
        return _offset_for_date(upcoming.date)
    past = qs.last()
    if past:
        return _offset_for_date(past.date)

    # 2. practice_start_date
    if meeting.practice_start_date:
        return _offset_for_date(meeting.practice_start_date)

    return 0


def _build_room_block_maps(rooms_qs, week_start, week_end, exclude_meeting=None):
    """
    roomBlockMap / roomBlockDetailMap 을 지정 날짜 범위로 구성한다.
    기존 matching_views의 로직과 동일한 구조.
    반환: (room_block_map_json, room_block_detail_map_json)
    """
    room_block_map = defaultdict(lambda: defaultdict(list))
    room_block_detail_map = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))

    block_qs = RoomBlock.objects.filter(
        room__in=rooms_qs,
        date__range=[week_start, week_end],
    )
    if exclude_meeting is not None:
        block_qs = block_qs.exclude(source_meeting=exclude_meeting)
    block_qs = block_qs.select_related('room', 'source_meeting')

    source_meeting_ids = set()
    for b in block_qs:
        d_key = b.date.strftime('%Y-%m-%d')
        r_key = str(b.room_id)
        room_block_map[d_key][r_key].extend(range(b.start_index, b.end_index))
        if b.source_meeting_id:
            source_meeting_ids.add(b.source_meeting_id)

    if source_meeting_ids:
        source_rows = PracticeSchedule.objects.filter(
            meeting_id__in=list(source_meeting_ids),
            room__in=rooms_qs,
            date__range=[week_start, week_end],
        ).select_related('meeting', 'song')
        for sch in source_rows:
            if exclude_meeting and sch.meeting_id == exclude_meeting.id:
                continue
            d_key = sch.date.strftime('%Y-%m-%d')
            r_key = str(sch.room_id)
            label = f"[{sch.meeting.title}] - {sch.song.title}"
            for slot in range(int(sch.start_index), int(sch.end_index)):
                room_block_detail_map[d_key][r_key][str(slot)].add(label)

    # JSON 직렬화 형태로 변환
    rbm_ready = {}
    for d_key, per_room in room_block_map.items():
        rbm_ready[d_key] = {r: sorted(set(slots)) for r, slots in per_room.items()}

    rbdm_ready = {}
    for d_key, per_room in room_block_detail_map.items():
        rbdm_ready[d_key] = {}
        for r_key, per_slot in per_room.items():
            rbdm_ready[d_key][r_key] = {slot: sorted(labels) for slot, labels in per_slot.items()}

    return rbm_ready, rbdm_ready


def _build_song_conflict_map_for_week(song, week_start, week_end):
    """
    해당 곡 assignee + applicant 의 불가능 시간을 week 범위로 계산한다.
    assignee 가 없으면 applicant(지원자)로 폴백.
    반환: song_conflict_map (JS의 songConflictMap 구조와 동일)
    {
      song_id: {
        member_count: N,
        members: [{username, display_name, session}],
        data: {date_str: {slot_str: [label, ...]}}
      }
    }
    """
    sessions = list(
        Session.objects.filter(song=song)
        .prefetch_related('applicant')
        .select_related('assignee')
    )
    if not sessions:
        return {}

    members = []
    for sess in sessions:
        sess_abbr = _session_abbr(sess.name)
        # assignee 우선
        if sess.assignee:
            u = sess.assignee
            display = str((u.realname or '').strip() or u.username)
            members.append({
                'user_id': u.id,
                'username': u.username,
                'display_name': display,
                'session': sess_abbr,
            })
        else:
            # assignee 없으면 applicant 전원 포함
            for u in sess.applicant.all():
                display = str((u.realname or '').strip() or u.username)
                members.append({
                    'user_id': u.id,
                    'username': u.username,
                    'display_name': display,
                    'session': sess_abbr,
                })

    if not members:
        return {}

    # 중복 유저 제거
    seen = {}
    unique_members = []
    for m in members:
        if m['username'] not in seen:
            seen[m['username']] = True
            unique_members.append(m)

    member_ids = [m['user_id'] for m in unique_members]
    unavail_map = _build_user_unavailable_reason_map(member_ids, week_start, week_end)

    # MemberAvailability 조회
    avail_lookup = defaultdict(dict)
    for av in MemberAvailability.objects.filter(
        user_id__in=member_ids,
        date__range=[week_start, week_end],
    ):
        avail_lookup[av.user_id][av.date.strftime('%Y-%m-%d')] = set(av.available_slot or [])

    per_date = {}
    date_cursor = week_start
    while date_cursor <= week_end:
        d_str = date_cursor.strftime('%Y-%m-%d')
        slot_reasons = {}
        for m in unique_members:
            uid = m['user_id']
            avail_slots = avail_lookup.get(uid, {}).get(d_str, set())
            for slot in range(18, 48):
                reasons = unavail_map.get(uid, {}).get(d_str, {}).get(slot, set())
                is_unavailable = (slot not in avail_slots) or bool(reasons)
                if is_unavailable:
                    reason_text = ', '.join(sorted(reasons)) if reasons else '사유 없음'
                    who = f"{m['display_name']}({m['session']})" if m['session'] else m['display_name']
                    label = f"{who} - {reason_text}"
                    slot_reasons.setdefault(str(slot), set()).add(label)
        if slot_reasons:
            per_date[d_str] = {k: sorted(v) for k, v in slot_reasons.items()}
        date_cursor += datetime.timedelta(days=1)

    return {
        str(song.id): {
            'member_count': len(unique_members),
            'members': [
                {'username': m['username'], 'display_name': m['display_name'], 'session': m['session']}
                for m in unique_members
            ],
            'data': per_date,
        }
    }


def _build_existing_schedules_json(meeting, rooms_qs, week_start, week_end, exclude_song=None):
    """
    해당 주의 PracticeSchedule + ExtraPracticeSchedule 을 배경 카드용 JSON으로 반환.
    exclude_song 에 해당하는 이 곡의 ExtraPracticeSchedule 은 별도로 내려주므로 여기선 제외.
    """
    schedules = []

    # 기존 PracticeSchedule (읽기 전용 배경)
    for ps in PracticeSchedule.objects.filter(
        meeting=meeting,
        date__range=[week_start, week_end],
    ).select_related('song', 'room'):
        schedules.append({
            'id': str(ps.id),
            'song_id': str(ps.song_id),
            'song_title': ps.song.title,
            'song_artist': ps.song.artist,
            'room_id': str(ps.room_id),
            'room_name': ps.room.name,
            'date': ps.date.strftime('%Y-%m-%d'),
            'start': ps.start_index,
            'end': ps.end_index,
            'is_extra': False,
            'is_mine': False,
        })

    # 다른 곡들의 ExtraPracticeSchedule (읽기 전용 배경)
    extra_qs = ExtraPracticeSchedule.objects.filter(
        meeting=meeting,
        date__range=[week_start, week_end],
    ).select_related('song', 'room')
    if exclude_song:
        extra_qs = extra_qs.exclude(song=exclude_song)
    for eps in extra_qs:
        schedules.append({
            'id': str(eps.id),
            'song_id': str(eps.song_id),
            'song_title': eps.song.title,
            'song_artist': eps.song.artist,
            'room_id': str(eps.room_id),
            'room_name': eps.room.name,
            'date': eps.date.strftime('%Y-%m-%d'),
            'start': eps.start_index,
            'end': eps.end_index,
            'is_extra': True,
            'is_mine': False,
        })

    return schedules


def _build_my_extra_schedules_json(song, meeting, user):
    """이 곡의 ExtraPracticeSchedule 전체 목록 (편집/삭제 가능)."""
    result = []
    for eps in ExtraPracticeSchedule.objects.filter(
        meeting=meeting, song=song
    ).select_related('room', 'created_by').order_by('date', 'start_index'):
        result.append({
            'id': str(eps.id),
            'room_id': str(eps.room_id),
            'room_name': eps.room.name,
            'room_location': eps.room.location or '',
            'date': eps.date.strftime('%Y-%m-%d'),
            'start': eps.start_index,
            'end': eps.end_index,
            'can_delete': (
                eps.created_by_id == user.id
                or has_meeting_manager_permission(meeting, user)
            ),
        })
    return result


# ──────────────────────────────────────────────
# Views
# ──────────────────────────────────────────────

@login_required
def extra_practice(request, meeting_id, song_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    song = get_object_or_404(Song, id=song_id, meeting=meeting)

    if not _is_song_participant_or_manager(meeting, song, request.user):
        raise Http404

    if 'week_offset' in request.GET:
        try:
            week_offset = int(request.GET['week_offset'])
        except (TypeError, ValueError):
            week_offset = 0
    else:
        week_offset = _default_week_offset(meeting)
    week_offset = max(-52, min(52, week_offset))  # 범위 제한

    week_start, week_end = _week_bounds(week_offset)

    rooms_qs = common_available_rooms_qs(meeting, include_temporary=True).order_by('name')

    room_block_map_json, room_block_detail_map_json = _build_room_block_maps(
        rooms_qs, week_start, week_end, exclude_meeting=meeting
    )
    song_conflict_map = _build_song_conflict_map_for_week(song, week_start, week_end)
    existing_schedules = _build_existing_schedules_json(meeting, rooms_qs, week_start, week_end, exclude_song=song)
    my_extra_schedules = _build_my_extra_schedules_json(song, meeting, request.user)

    room_list = [
        {
            'id': str(r.id),
            'name': r.name,
            'location': r.location or '',
            'capacity': r.capacity,
            'is_temporary': r.is_temporary,
        }
        for r in rooms_qs
    ]

    # 주차 일별 데이터
    week_days = []
    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        week_days.append({'date': d, 'date_str': d.strftime('%Y-%m-%d')})

    context = {
        'meeting': meeting,
        'song': song,
        'week_start': week_start,
        'week_end': week_end,
        'week_offset': week_offset,
        'week_days': week_days,
        'room_list_json': json.dumps(room_list, ensure_ascii=False),
        'room_block_map_json': json.dumps(room_block_map_json, ensure_ascii=False),
        'room_block_detail_map_json': json.dumps(room_block_detail_map_json, ensure_ascii=False),
        'song_conflict_map_json': json.dumps(song_conflict_map, ensure_ascii=False),
        'existing_schedules_json': json.dumps(existing_schedules, ensure_ascii=False),
        'my_extra_schedules_json': json.dumps(my_extra_schedules, ensure_ascii=False),
        'save_url': f'/meeting/{meeting_id}/song/{song_id}/extra-practice/save/',
        'delete_url': f'/meeting/{meeting_id}/song/{song_id}/extra-practice/delete/',
        'back_url': f'/meeting/{meeting_id}/final/',
    }
    return render(request, 'pracapp/extra_practice.html', context)


@login_required
def extra_practice_save(request, meeting_id, song_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '허용되지 않는 메서드'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    song = get_object_or_404(Song, id=song_id, meeting=meeting)

    if not _is_song_participant_or_manager(meeting, song, request.user):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식'}, status=400)

    date_str = body.get('date', '')
    start_index = body.get('start_index')
    end_index = body.get('end_index')
    room_id = body.get('room_id')
    is_temp_room = body.get('is_temp_room', False)
    room_name = body.get('room_name', '').strip()
    room_location = body.get('room_location', '').strip()

    # 필수 파라미터 검증
    try:
        date = datetime.date.fromisoformat(date_str)
        start_index = int(start_index)
        end_index = int(end_index)
    except (TypeError, ValueError):
        return JsonResponse({'status': 'error', 'message': '날짜 또는 시간 슬롯 오류'}, status=400)

    if not (18 <= start_index < end_index <= 48):
        return JsonResponse({'status': 'error', 'message': '유효하지 않은 시간 범위'}, status=400)

    # 합주실 결정
    if is_temp_room:
        if not room_name:
            return JsonResponse({'status': 'error', 'message': '임시합주실 이름을 입력해주세요.'}, status=400)
        room, _ = PracticeRoom.objects.get_or_create(
            band=meeting.band,
            name=room_name,
            is_temporary=True,
            defaults={'location': room_location, 'capacity': 7},
        )
    else:
        try:
            room = PracticeRoom.objects.get(id=room_id, band=meeting.band)
        except (PracticeRoom.DoesNotExist, ValueError):
            return JsonResponse({'status': 'error', 'message': '유효하지 않은 합주실'}, status=400)

    # 중복 체크: PracticeSchedule
    ps_conflict = PracticeSchedule.objects.filter(
        room=room,
        date=date,
        start_index__lt=end_index,
        end_index__gt=start_index,
    ).exists()
    if ps_conflict:
        return JsonResponse({'status': 'conflict', 'message': '해당 시간에 이미 합주 일정이 있습니다.'}, status=409)

    # 중복 체크: ExtraPracticeSchedule
    eps_conflict = ExtraPracticeSchedule.objects.filter(
        room=room,
        date=date,
        start_index__lt=end_index,
        end_index__gt=start_index,
    ).exists()
    if eps_conflict:
        return JsonResponse({'status': 'conflict', 'message': '해당 시간에 이미 추가 합주가 있습니다.'}, status=409)

    # 저장
    eps = ExtraPracticeSchedule.objects.create(
        meeting=meeting,
        song=song,
        room=room,
        date=date,
        start_index=start_index,
        end_index=end_index,
        created_by=request.user,
    )

    # RoomBlock 생성 (다른 미팅 충돌 방지)
    block = RoomBlock.objects.create(
        room=room,
        date=date,
        start_index=start_index,
        end_index=end_index,
        source_meeting=meeting,
    )

    return JsonResponse({
        'status': 'ok',
        'schedule_id': str(eps.id),
        'block_id': str(block.id),
        'room_id': str(room.id),
        'room_name': room.name,
        'room_location': room.location or '',
        'is_temporary': room.is_temporary,
    })


@login_required
def extra_practice_delete(request, meeting_id, song_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '허용되지 않는 메서드'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    song = get_object_or_404(Song, id=song_id, meeting=meeting)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식'}, status=400)

    schedule_id = body.get('schedule_id', '')
    try:
        eps = ExtraPracticeSchedule.objects.get(id=schedule_id, song=song, meeting=meeting)
    except (ExtraPracticeSchedule.DoesNotExist, ValueError):
        return JsonResponse({'status': 'error', 'message': '해당 추가 합주를 찾을 수 없습니다.'}, status=404)

    # 권한: 생성자 또는 매니저
    is_manager = has_meeting_manager_permission(meeting, request.user)
    if not is_manager and eps.created_by_id != request.user.id:
        return JsonResponse({'status': 'error', 'message': '삭제 권한이 없습니다.'}, status=403)

    # 연관 RoomBlock 삭제
    RoomBlock.objects.filter(
        room=eps.room,
        date=eps.date,
        start_index=eps.start_index,
        end_index=eps.end_index,
        source_meeting=meeting,
    ).delete()

    eps.delete()
    return JsonResponse({'status': 'ok'})
