import datetime
import json
from collections import defaultdict
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Min, Max, F, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse

from ..forms import MatchSettingsForm
from ..models import (
    Meeting, Membership, PracticeSchedule, MemberAvailability,
    MeetingFinalDraft, RoomBlock, Song, User, PracticeRoom, Session,
    MeetingParticipant,
    MeetingScheduleConfirmation, MeetingWorkDraft, ExtraPracticeSchedule,
)
from .. import utils
from ..utils import (
    _session_abbr,
    _build_user_unavailable_reason_map,
    _recompute_forced_flags,
    _build_song_conflict_and_member_maps,
)
from ._meeting_common import (
    is_final_locked as common_is_final_locked,
    final_lock_prefix as common_final_lock_prefix,
    final_lock_message as common_final_lock_message,
    final_lock_state_message as common_final_lock_state_message,
    available_rooms_qs as common_available_rooms_qs,
    is_manager_membership as common_is_manager_membership,
    get_approved_membership as common_get_approved_membership,
    is_meeting_manager_participant as common_is_meeting_manager_participant,
    has_meeting_manager_permission as common_has_meeting_manager_permission,
)

logger = logging.getLogger(__name__)


# Helper functions
def _is_final_locked(meeting):
    return common_is_final_locked(meeting, include_released=False)


def _final_lock_prefix(meeting):
    return common_final_lock_prefix(meeting)


def _final_lock_message(meeting, action_text):
    return common_final_lock_message(meeting, action_text)


def _final_lock_state_message(meeting):
    return common_final_lock_state_message(meeting)


def _merge_contiguous_events(events):
    """
    같은 날짜/같은 곡/같은 방/같은 타입의 연속 구간은 하나로 병합
    """
    buckets = defaultdict(list)
    for e in events:
        key = (
            e['date'],
            str(e['song'].id),
            str(e['room'].id),
            e.get('is_fixed', False),
            e.get('is_forced', False),
        )
        buckets[key].append(e)

    merged = []
    for _, rows in buckets.items():
        rows.sort(key=lambda x: x['start'])
        acc = None
        for row in rows:
            if acc is None:
                acc = dict(row)
                continue
            # 연달아 붙거나 겹치면 병합
            if row['start'] <= acc['end']:
                acc['end'] = max(acc['end'], row['end'])
            else:
                merged.append(acc)
                acc = dict(row)
        if acc is not None:
            merged.append(acc)

    merged.sort(key=lambda x: (x['date'], x['start'], x['song_title']))
    return merged


def _sync_room_blocks_for_confirmed_schedule(meeting):
    """
    최종 확정된 PracticeSchedule을 RoomBlock(source_meeting=meeting)으로 동기화.
    기존 해당 회의의 생성 블록은 먼저 삭제 후 재생성한다.
    """
    RoomBlock.objects.filter(source_meeting=meeting).delete()

    rows = list(
        PracticeSchedule.objects.filter(meeting=meeting)
        .values('room_id', 'date', 'start_index', 'end_index')
        .order_by('room_id', 'date', 'start_index')
    )
    if not rows:
        return

    merged_blocks = []
    acc = None
    for row in rows:
        key = (row['room_id'], row['date'])
        start = int(row['start_index'])
        end = int(row['end_index'])
        if acc is None:
            acc = {'key': key, 'start': start, 'end': end}
            continue
        if acc['key'] == key and start <= acc['end']:
            acc['end'] = max(acc['end'], end)
            continue
        merged_blocks.append(acc)
        acc = {'key': key, 'start': start, 'end': end}
    if acc is not None:
        merged_blocks.append(acc)

    RoomBlock.objects.bulk_create([
        RoomBlock(
            room_id=item['key'][0],
            date=item['key'][1],
            start_index=item['start'],
            end_index=item['end'],
            source_meeting=meeting,
        )
        for item in merged_blocks
    ])


def _clear_room_blocks_for_confirmed_schedule(meeting):
    RoomBlock.objects.filter(source_meeting=meeting).delete()


def _fully_assigned_song_ids(meeting):
    return list(
        meeting.songs.exclude(sessions__assignee__isnull=True)
        .filter(sessions__isnull=False)
        .distinct()
        .values_list('id', flat=True)
    )


def _build_events_signature(events):
    if not isinstance(events, list):
        return ''
    grouped = defaultdict(list)
    for ev in events:
        try:
            start = int(ev.get('start'))
            duration = int(ev.get('duration'))
        except (TypeError, ValueError):
            continue
        song_id = str(ev.get('song_id') or '')
        date_str = str(ev.get('date') or '')
        room_id = str(ev.get('room_id') or '')
        dur = max(1, duration)
        grouped[(song_id, date_str, room_id)].append((start, start + dur))

    normalized = []
    for (song_id, date_str, room_id), ranges in grouped.items():
        ranges.sort(key=lambda x: x[0])
        acc_start, acc_end = None, None
        for start, end in ranges:
            if acc_start is None:
                acc_start, acc_end = start, end
                continue
            if start <= acc_end:
                acc_end = max(acc_end, end)
            else:
                normalized.append({
                    'song_id': song_id,
                    'date': date_str,
                    'start': acc_start,
                    'duration': max(1, acc_end - acc_start),
                    'room_id': room_id,
                })
                acc_start, acc_end = start, end
        if acc_start is not None:
            normalized.append({
                'song_id': song_id,
                'date': date_str,
                'start': acc_start,
                'duration': max(1, acc_end - acc_start),
                'room_id': room_id,
            })
    normalized.sort(key=lambda x: (
        x['date'],
        x['start'],
        x['song_id'],
        x['room_id'],
    ))
    return json.dumps(normalized, ensure_ascii=False, separators=(',', ':'))


def _available_rooms_qs(meeting, include_temporary=False):
    return common_available_rooms_qs(meeting, include_temporary=include_temporary)


def _build_booking_event_key(song_id, date_str, start, duration, room_id):
    return f"{str(song_id or '')}|{str(date_str or '')}|{int(start)}|{int(duration)}|{str(room_id or '')}"


def _get_overlapping_band_meeting_ids(meeting, start_date, end_date, exclude_self=True):
    qs = Meeting.objects.filter(band=meeting.band).filter(
        Q(practice_start_date__isnull=True)
        | Q(practice_end_date__isnull=True)
        | (
            Q(practice_start_date__lte=end_date)
            & Q(practice_end_date__gte=start_date)
        )
    )
    if exclude_self:
        qs = qs.exclude(id=meeting.id)
    return list(qs.values_list('id', flat=True))


def _validate_normalized_events_against_external_conflicts(meeting, normalized_events):
    """
    normalized_events: [
      {'song': Song, 'date': date, 'start': int, 'end': int, 'room': PracticeRoom, ...}, ...
    ]
    반환: (is_ok: bool, message: str)
    """
    if not normalized_events:
        return True, ''

    date_set = sorted({item['date'] for item in normalized_events})
    min_date = date_set[0]
    max_date = date_set[-1]
    overlapping_meeting_ids = _get_overlapping_band_meeting_ids(
        meeting, min_date, max_date, exclude_self=True
    )

    # 1) 합주실 점유 충돌 검사
    candidate_room_ids = sorted({
        str(item['room'].id)
        for item in normalized_events
        if item.get('room') is not None
    })
    room_blocks_by_key = defaultdict(list)
    if candidate_room_ids and date_set:
        room_block_rows = RoomBlock.objects.filter(
            room_id__in=candidate_room_ids,
            date__range=[min_date, max_date],
        ).exclude(source_meeting=meeting).values('room_id', 'date', 'start_index', 'end_index')
        for row in room_block_rows:
            key = (str(row['room_id']), row['date'])
            room_blocks_by_key[key].append((int(row['start_index']), int(row['end_index'])))

    external_room_schedules_by_key = defaultdict(list)
    if overlapping_meeting_ids and candidate_room_ids and date_set:
        ext_room_rows = PracticeSchedule.objects.filter(
            meeting_id__in=overlapping_meeting_ids,
            room_id__in=candidate_room_ids,
            date__range=[min_date, max_date],
        ).select_related('meeting', 'song', 'room')
        for sch in ext_room_rows:
            key = (str(sch.room_id), sch.date)
            external_room_schedules_by_key[key].append(sch)

    for item in normalized_events:
        room_obj = item['room']
        if not room_obj:
            continue
        room_id = str(room_obj.id)
        d = item['date']
        start = int(item['start'])
        end = int(item['end'])
        for b_start, b_end in room_blocks_by_key.get((room_id, d), []):
            if start < b_end and end > b_start:
                return False, f"[{d}] {room_obj.name} 합주실이 이미 사용 중입니다."
        for sch in external_room_schedules_by_key.get((room_id, d), []):
            if start < int(sch.end_index) and end > int(sch.start_index):
                return False, f"[{d}] {room_obj.name} 합주실이 [{sch.meeting.title}] - {sch.song.title}와 겹칩니다."

    # 2) 멤버 중복 검사 (payload 내부 + 외부 미팅)
    payload_song_ids = sorted({str(item['song'].id) for item in normalized_events})
    payload_song_assignees = defaultdict(set)
    if payload_song_ids:
        for sid, uid in Session.objects.filter(
            song_id__in=payload_song_ids,
            assignee__isnull=False,
        ).values_list('song_id', 'assignee_id'):
            payload_song_assignees[str(sid)].add(uid)

    payload_events_by_date = defaultdict(list)
    for item in normalized_events:
        sid = str(item['song'].id)
        payload_events_by_date[item['date']].append({
            'song_id': sid,
            'song_title': item['song'].title,
            'start': int(item['start']),
            'end': int(item['end']),
            'assignees': set(payload_song_assignees.get(sid, set())),
        })

    # payload 내부
    for d, rows in payload_events_by_date.items():
        for i in range(len(rows)):
            a = rows[i]
            if not a['assignees']:
                continue
            for j in range(i + 1, len(rows)):
                b = rows[j]
                if not b['assignees']:
                    continue
                if a['start'] >= b['end'] or b['start'] >= a['end']:
                    continue
                if a['assignees'].isdisjoint(b['assignees']):
                    continue
                return False, f"[{d}] 같은 멤버가 '{a['song_title']}'와 '{b['song_title']}'에 중복 배정되었습니다."

    # 외부 미팅과 중복
    if overlapping_meeting_ids and date_set:
        external_sched_rows = list(
            PracticeSchedule.objects.filter(
                meeting_id__in=overlapping_meeting_ids,
                date__range=[min_date, max_date],
            ).select_related('meeting', 'song')
        )
        external_song_ids = sorted({str(s.song_id) for s in external_sched_rows})
        external_song_assignees = defaultdict(set)
        if external_song_ids:
            for sid, uid in Session.objects.filter(
                song_id__in=external_song_ids,
                assignee__isnull=False,
            ).values_list('song_id', 'assignee_id'):
                external_song_assignees[str(sid)].add(uid)

        for sch in external_sched_rows:
            d = sch.date
            local_rows = payload_events_by_date.get(d, [])
            if not local_rows:
                continue
            ext_start = int(sch.start_index)
            ext_end = int(sch.end_index)
            ext_assignees = set(external_song_assignees.get(str(sch.song_id), set()))
            if not ext_assignees:
                continue
            for local in local_rows:
                if local['start'] >= ext_end or ext_start >= local['end']:
                    continue
                if local['assignees'].isdisjoint(ext_assignees):
                    continue
                return False, f"[{d}] '{local['song_title']}' 멤버가 [{sch.meeting.title}] - {sch.song.title}와 시간 중복입니다."

    return True, ''


def _is_manager_membership(membership):
    return common_is_manager_membership(membership)


def _get_approved_membership(meeting, user):
    return common_get_approved_membership(user, meeting.band)


def _is_meeting_manager_participant(meeting, user):
    return common_is_meeting_manager_participant(meeting, user)


def _has_meeting_manager_permission(meeting, user, membership=None):
    return common_has_meeting_manager_permission(meeting, user, membership=membership)


# Main view functions
@login_required
def schedule_match_settings(request, meeting_id):
    """
    [Step 1] 매칭 설정 페이지
    - 곡당 합주 시간, 횟수 등을 입력받습니다.
    """
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if _is_final_locked(meeting):
        messages.error(request, _final_lock_message(meeting, '자동 매칭을 다시 시작할 수 없습니다.'))
        return redirect('meeting_detail', pk=meeting_id)

    # 권한 체크 (리더/매니저만)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return redirect('meeting_detail', pk=meeting_id)

    if not meeting.practice_start_date or not meeting.practice_end_date:
        messages.error(request, '합주 시작일과 종료일을 먼저 설정해야 매칭을 진행할 수 있습니다.')
        return redirect('meeting_update', pk=meeting_id)

    room_qs = _available_rooms_qs(meeting).order_by('name')
    has_rooms = room_qs.exists()
    room_choices = [(str(r.id), r.name) for r in room_qs]
    room_initial = [str(r.id) for r in room_qs]
    popup_mode = (request.GET.get('popup') == '1') or (request.POST.get('popup_mode') == '1')
    is_simulation = (request.GET.get('simulation') == '1') or (request.POST.get('simulation') == '1')
    settings_session_key = f"match_settings_{meeting_id}"
    saved_settings = request.session.get(settings_session_key)
    assigned_song_ids = _fully_assigned_song_ids(meeting)
    assigned_song_count = len(assigned_song_ids)
    total_song_count = meeting.songs.count()
    unassigned_song_count = max(total_song_count - assigned_song_count, 0)
    unassigned_song_qs = (
        meeting.songs.exclude(id__in=assigned_song_ids)
        .prefetch_related('sessions')
        .order_by('title')
    )
    unassigned_song_titles = []
    unassigned_song_details = []
    for song in unassigned_song_qs:
        missing_sessions = [s.name for s in song.sessions.all() if not s.assignee_id]
        unassigned_song_titles.append(song.title)
        unassigned_song_details.append({
            'title': song.title,
            'missing_sessions': missing_sessions,
        })

    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        if not has_rooms:
            if popup_mode and is_ajax:
                return JsonResponse({'status': 'error', 'message': '합주실이 없어 매칭할 수 없습니다.'}, status=400)
            messages.error(request, '합주실 없슴. 먼저 합주실을 등록해줘.')
            return redirect('meeting_room_create', meeting_id=meeting_id)
        form = MatchSettingsForm(
            request.POST,
            room_choices=room_choices,
            room_initial=room_initial,
        )
        if form.is_valid():
            if assigned_song_count <= 0:
                if popup_mode and is_ajax:
                    return JsonResponse({'status': 'error', 'message': '배정 완료된 곡이 없어 매칭할 수 없습니다.'}, status=400)
                messages.error(request, '배정 완료된 곡이 없어 매칭할 수 없습니다.')
                return redirect('meeting_detail', pk=meeting_id)
            # 입력값을 세션에 잠시 저장하거나, 바로 결과 페이지로 넘기면서 파라미터로 전달
            # 여기선 GET 파라미터로 넘기는 방식 사용 (간단함)
            duration = form.cleaned_data['duration_minutes']
            count = form.cleaned_data['required_count']
            priority_order = form.cleaned_data.get('priority_order', MatchSettingsForm.DEFAULT_PRIORITY_ORDER)
            priority_param = ",".join(priority_order)
            selected_room_ids = [str(x) for x in form.cleaned_data.get('room_ids', [])]
            room_priority_order = [str(x) for x in form.cleaned_data.get('room_priority_order', [])]
            # 사용 여부(room_ids)를 먼저 적용하고, 그 안에서 선호도(room_priority_order) 순 정렬
            preferred_ids = [rid for rid in room_priority_order if rid in selected_room_ids]
            for rid in selected_room_ids:
                if rid not in preferred_ids:
                    preferred_ids.append(rid)
            room_param = ",".join(selected_room_ids)
            room_pref_param = ",".join(preferred_ids)
            weekend_param = '1' if form.cleaned_data.get('exclude_weekends') else '0'
            room_eff_param = '1' if form.cleaned_data.get('room_efficiency_priority') else '0'
            hour_start_param = '1' if form.cleaned_data.get('hour_start_only') else '0'
            limit_start_param = int(form.cleaned_data.get('time_limit_start', 18))
            limit_end_param = int(form.cleaned_data.get('time_limit_end', 48))
            ack_unassigned = request.POST.get('ack_unassigned') == '1'
            if unassigned_song_count > 0 and not ack_unassigned:
                form.add_error(None, f'배정 안 된 노래가 {unassigned_song_count}곡 있으며, 해당 곡은 매칭에서 제외됩니다. 진행하려면 다시 실행해주세요.')
            else:
                request.session[settings_session_key] = {
                    'duration_minutes': int(duration),
                    'required_count': int(count),
                    'priority_order': list(priority_order),
                    'room_ids': selected_room_ids,
                    'room_priority_order': preferred_ids,
                    'advanced_options_used': True,
                    'exclude_weekends': bool(form.cleaned_data.get('exclude_weekends')),
                    'room_efficiency_priority': bool(form.cleaned_data.get('room_efficiency_priority')),
                    'maximize_feasibility': False,
                    'hour_start_only': bool(form.cleaned_data.get('hour_start_only')),
                    'time_limit_start': limit_start_param,
                    'time_limit_end': limit_end_param,
                }

                run_url = f"{reverse('schedule_match_run', args=[meeting_id])}?d={duration}&c={count}&p={priority_param}&r={room_param}&rp={room_pref_param}&w={weekend_param}&re={room_eff_param}&h={hour_start_param}&ts={limit_start_param}&te={limit_end_param}"
                run_url += "&force_rematch=1"
                if is_simulation:
                    run_url += '&simulation=1'

                if popup_mode and is_ajax:
                    return JsonResponse({'status': 'ok', 'run_url': run_url})
                if popup_mode:
                    return redirect(run_url)
                return redirect(run_url)
        if popup_mode and is_ajax:
            errs = form.errors.get_json_data()
            non_field = [e.get('message', '') for e in errs.get('__all__', [])]
            return JsonResponse({'status': 'error', 'message': non_field[0] if non_field else '입력값을 확인해주세요.'}, status=400)
    else:
        initial = None
        get_room_initial = room_initial
        if saved_settings:
            initial = {
                'duration_minutes': saved_settings.get('duration_minutes', 30),
                'required_count': saved_settings.get('required_count', 1),
                'priority_order': ",".join(saved_settings.get('priority_order', MatchSettingsForm.DEFAULT_PRIORITY_ORDER)),
                'room_priority_order': ",".join(saved_settings.get('room_priority_order', saved_settings.get('room_ids', []))),
                'exclude_weekends': saved_settings.get('exclude_weekends', False),
                'room_efficiency_priority': saved_settings.get('room_efficiency_priority', False),
                'maximize_feasibility': False,
                'hour_start_only': saved_settings.get('hour_start_only', False),
                'time_limit_start': saved_settings.get('time_limit_start', 18),
                'time_limit_end': saved_settings.get('time_limit_end', 48),
            }
            saved_rooms = saved_settings.get('room_ids') or []
            get_room_initial = [str(x) for x in saved_rooms] if saved_rooms else room_initial

        form = MatchSettingsForm(
            room_choices=room_choices,
            room_initial=get_room_initial,
            initial=initial,
        )
    weekday_kor = ['월', '화', '수', '목', '금', '토', '일']
    start_weekday = None
    end_weekday = None
    if meeting.practice_start_date:
        start_weekday = weekday_kor[meeting.practice_start_date.weekday()]
    if meeting.practice_end_date:
        end_weekday = weekday_kor[meeting.practice_end_date.weekday()]

    return render(request, 'pracapp/match_settings.html', {
        'meeting': meeting,
        'form': form,
        'start_weekday': start_weekday,
        'end_weekday': end_weekday,
        'popup_mode': popup_mode,
        'simulation': is_simulation,
        'has_rooms': has_rooms,
        'assigned_song_count': assigned_song_count,
        'unassigned_song_count': unassigned_song_count,
        'unassigned_song_titles': unassigned_song_titles,
        'unassigned_song_details': unassigned_song_details,
        'priority_items': [
            {'key': key, 'label': label}
            for key, label in MatchSettingsForm.PRIORITY_CHOICES
        ],
    })


@login_required
def schedule_match_run(request, meeting_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    is_simulation = request.GET.get('simulation') == '1'
    if _is_final_locked(meeting):
        messages.error(request, _final_lock_message(meeting, '자동 매칭을 다시 시작할 수 없습니다.'))
        return redirect('meeting_detail', pk=meeting_id)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return redirect('meeting_detail', pk=meeting_id)
    from_final = request.GET.get('from_final') == '1'
    force_rematch = request.GET.get('force_rematch') == '1'
    load_saved = request.GET.get('load_saved') == '1'
    user_work_draft = MeetingWorkDraft.objects.filter(meeting=meeting, user=request.user).first()
    has_saved_work_draft = bool(user_work_draft and isinstance(user_work_draft.events, list))
    # 기본 정책: 시뮬레이션/최종복귀/강제재매칭이 아니고 저장본이 있으면 저장본을 우선 로드
    if (not is_simulation) and (not from_final) and (not force_rematch) and has_saved_work_draft:
        load_saved = True
    color_palette = [
        '#e03131', '#d9480f', '#f08c00', '#2b8a3e', '#0b7285',
        '#1971c2', '#364fc7', '#5f3dc4', '#862e9c', '#c2255c',
        '#087f5b', '#6741d9', '#1864ab', '#9c36b5',
        '#ff8787', '#f783ac', '#a61e4d', '#ff6b6b', '#ffd43b',
        '#ffa94d', '#e67700', '#fab005', '#69db7c', '#94d82d',
        '#5c940d', '#2f9e44', '#c0eb75', '#3bc9db', '#66d9e8',
        '#1098ad', '#20c997', '#4dabf7', '#748ffc', '#3b5bdb',
        '#4263eb', '#da77f2', '#be4bdb', '#ae3ec9', '#a52a2a'
    ]

    draft_obj = MeetingFinalDraft.objects.filter(meeting=meeting).first()
    # 새로 매칭 시작한 경우(특히 force_rematch)는 기존 공유 draft를 버리고 완전히 새로 시작한다.
    # force_rematch가 아닌 일반 진입에서는 기존 정책(공유 상태면 유지)을 따른다.
    should_drop_existing_shared_draft = bool(
        draft_obj and not from_final and (force_rematch or (not meeting.is_final_schedule_released))
    )
    if should_drop_existing_shared_draft:
        draft_obj.delete()
        draft_obj = None
    # 공유 상태에서 load_saved로 진입했는데 개인 저장본이 없으면, 공유 draft(from_final)로 이어서 조율한다.
    if load_saved and (not has_saved_work_draft) and draft_obj and isinstance(draft_obj.events, list):
        load_saved = False
        from_final = True
    update_fields = []
    if not meeting.is_schedule_coordinating and not meeting.is_final_schedule_released:
        meeting.is_schedule_coordinating = True
        update_fields.append('is_schedule_coordinating')
    if not from_final and meeting.is_booking_in_progress:
        meeting.is_booking_in_progress = False
        update_fields.append('is_booking_in_progress')
    if not from_final and meeting.is_final_schedule_confirmed:
        meeting.is_final_schedule_confirmed = False
        update_fields.append('is_final_schedule_confirmed')
        _clear_room_blocks_for_confirmed_schedule(meeting)
    if update_fields:
        meeting.save(update_fields=update_fields)

    # 1. DB 확정 스케줄
    db_schedules = PracticeSchedule.objects.filter(meeting=meeting)
    pre_assigned = []
    for sch in db_schedules:
        pre_assigned.append({
            'song': sch.song,
            'song_title': sch.song.title,
            'room': sch.room,
            'date': sch.date.strftime('%Y-%m-%d'),
            'start': sch.start_index,
            'end': sch.end_index,
            'is_forced': bool(sch.is_forced),
            'is_fixed': True,
        })

    saved_params = user_work_draft.match_params if (load_saved and user_work_draft and isinstance(user_work_draft.match_params, dict)) else {}
    settings_session_key = f"match_settings_{meeting_id}"
    saved_settings = request.session.get(settings_session_key) or {}
    saved_settings_params = {
        'd': saved_settings.get('duration_minutes'),
        'c': saved_settings.get('required_count'),
        'p': ",".join(saved_settings.get('priority_order', MatchSettingsForm.DEFAULT_PRIORITY_ORDER) or MatchSettingsForm.DEFAULT_PRIORITY_ORDER),
        'r': ",".join([str(x) for x in (saved_settings.get('room_ids') or [])]),
        'rp': ",".join([str(x) for x in (saved_settings.get('room_priority_order') or saved_settings.get('room_ids') or [])]),
        'w': '1' if saved_settings.get('exclude_weekends') else '0',
        're': '1' if saved_settings.get('room_efficiency_priority') else '0',
        'h': '1' if saved_settings.get('hour_start_only') else '0',
        'ts': saved_settings.get('time_limit_start'),
        'te': saved_settings.get('time_limit_end'),
    }

    def _param_with_saved(name, default=''):
        v = request.GET.get(name, None)
        if v is not None and str(v).strip() != '':
            return v
        if name in saved_params:
            return saved_params.get(name)
        if name in saved_settings_params:
            sv = saved_settings_params.get(name)
            if sv is not None and str(sv).strip() != '':
                return sv
        return default

    # 공통 파라미터
    duration = int(_param_with_saved('d', 60))
    count = int(_param_with_saved('c', 1))
    raw_priority = _param_with_saved('p', '')
    if raw_priority:
        priority_order = [x.strip() for x in raw_priority.split(',') if x.strip()]
    else:
        priority_order = MatchSettingsForm.DEFAULT_PRIORITY_ORDER

    raw_rooms = _param_with_saved('r', '')
    selected_room_ids = [x.strip() for x in raw_rooms.split(',') if x.strip()] if raw_rooms else None
    raw_room_pref = _param_with_saved('rp', '')
    room_preferred_ids = [x.strip() for x in raw_room_pref.split(',') if x.strip()] if raw_room_pref else None
    exclude_weekends = str(_param_with_saved('w', '0')) == '1'
    room_efficiency_priority = str(_param_with_saved('re', '0')) == '1'
    maximize_feasibility = False
    hour_start_only = str(_param_with_saved('h', '0')) == '1'
    time_limit_start = int(_param_with_saved('ts', 18))
    time_limit_end = int(_param_with_saved('te', 48))
    duration_slots = max(1, duration // 30)
    confirmed_song_ids = _fully_assigned_song_ids(meeting)
    excluded_song_count = max(meeting.songs.count() - len(confirmed_song_ids), 0)
    effective_match_params = {
        'd': str(duration),
        'c': str(count),
        'p': ",".join(priority_order),
        'r': ",".join(selected_room_ids or []),
        'rp': ",".join(room_preferred_ids or []),
        'w': '1' if exclude_weekends else '0',
        're': '1' if room_efficiency_priority else '0',
        'h': '1' if hour_start_only else '0',
        'ts': str(time_limit_start),
        'te': str(time_limit_end),
    }
    advanced_param_keys = ('w', 're', 'h', 'ts', 'te')
    match_advanced_used = bool(saved_settings.get('advanced_options_used')) or any(
        request.GET.get(k) is not None for k in advanced_param_keys
    ) or any(
        str(saved_params.get(k, '')).strip() != '' for k in advanced_param_keys
    )
    def _slot_label(idx):
        h = idx // 2
        m = '00' if idx % 2 == 0 else '30'
        return f"{h:02d}:{m}"
    match_time_limit_label = f"{_slot_label(time_limit_start)}~{_slot_label(time_limit_end)}"

    # 최종 일정에서 "합주 시간표 조정"으로 돌아온 경우: draft 우선 로드
    if load_saved:
        if not user_work_draft or not isinstance(user_work_draft.events, list):
            messages.error(request, '저장된 작업중 시간표가 없습니다.')
            return redirect('meeting_detail', pk=meeting_id)

        songs_by_id = {str(s.id): s for s in meeting.songs.all()}
        rooms_by_id = {str(r.id): r for r in _available_rooms_qs(meeting)}
        draft_schedule = []
        for ev in user_work_draft.events:
            sid = str(ev.get('song_id') or '')
            song = songs_by_id.get(sid)
            if not song:
                continue
            try:
                d = datetime.date.fromisoformat(str(ev.get('date') or ''))
                start = int(ev.get('start'))
                ev_duration = int(ev.get('duration'))
            except (TypeError, ValueError):
                continue
            end = start + max(1, ev_duration)
            room_id_raw = str(ev.get('room_id') or '')
            room_name_raw = str(ev.get('room_name') or '').strip() or '임시합주실'
            room_location_raw = str(ev.get('room_location') or '').strip()
            room_obj = rooms_by_id.get(room_id_raw)
            if room_obj is None:
                from types import SimpleNamespace
                room_obj = SimpleNamespace(
                    id=room_id_raw or f"temp-{sid}",
                    name=room_name_raw,
                    location=room_location_raw or '-'
                )
            draft_schedule.append({
                'song': song,
                'song_title': song.title,
                'room': room_obj,
                'date': d.strftime('%Y-%m-%d'),
                'start': start,
                'end': end,
                'is_forced': bool(ev.get('is_forced', False)),
                'is_fixed': False,
            })

        result = {
            'status': 'success',
            'schedule': draft_schedule,
            'failed': [],
            'total_count': len(confirmed_song_ids),
            'success_count': len({str(x['song'].id) for x in draft_schedule}),
        }
    elif from_final and draft_obj and isinstance(draft_obj.events, list):
        songs_by_id = {str(s.id): s for s in meeting.songs.all()}
        rooms_by_id = {str(r.id): r for r in _available_rooms_qs(meeting)}
        draft_schedule = []
        for ev in draft_obj.events:
            sid = str(ev.get('song_id') or '')
            song = songs_by_id.get(sid)
            if not song:
                continue
            try:
                d = datetime.date.fromisoformat(str(ev.get('date') or ''))
                start = int(ev.get('start'))
                duration = int(ev.get('duration'))
            except (TypeError, ValueError):
                continue
            end = start + max(1, duration)
            room_id_raw = str(ev.get('room_id') or '')
            room_name_raw = str(ev.get('room_name') or '').strip() or '임시합주실'
            room_location_raw = str(ev.get('room_location') or '').strip()
            room_obj = rooms_by_id.get(room_id_raw)
            if room_obj is None:
                from types import SimpleNamespace
                room_obj = SimpleNamespace(
                    id=room_id_raw or f"temp-{sid}",
                    name=room_name_raw,
                    location=room_location_raw or '-'
                )
            draft_schedule.append({
                'song': song,
                'song_title': song.title,
                'room': room_obj,
                'date': d.strftime('%Y-%m-%d'),
                'start': start,
                'end': end,
                'is_forced': bool(ev.get('is_forced', False)),
                'is_fixed': False,
            })

        result = {
            'status': 'success',
            'schedule': draft_schedule,
            'failed': [],
            'total_count': len(confirmed_song_ids),
            'success_count': len({str(x['song'].id) for x in draft_schedule}),
        }
    else:
        # 2. 알고리즘 실행
        # 미배정 세션이 있는 곡은 자동 매칭에서 제외
        if not confirmed_song_ids:
            return render(request, 'pracapp/match_result.html', {
                'meeting': meeting,
                'error_message': '배정 완료된 곡이 없어 자동 매칭을 진행할 수 없습니다.',
                'missing_members': [],
                'is_error': True,
                'is_simulation': is_simulation,
                'hide_base_chrome': is_simulation,
            })
        result = utils.auto_schedule_match(
            meeting,
            duration,
            count,
            priority_order=priority_order,
            allowed_room_ids=selected_room_ids,
            preferred_room_ids=room_preferred_ids,
            exclude_weekends=exclude_weekends,
            room_efficiency_priority=room_efficiency_priority,
            maximize_feasibility=maximize_feasibility,
            hour_start_only=hour_start_only,
            time_limit_start=time_limit_start,
            time_limit_end=time_limit_end,
            song_ids=confirmed_song_ids,
        )

    # [NEW] 에러 처리
    if result['status'] == 'error':
        return render(request, 'pracapp/match_result.html', {
            'meeting': meeting,
            'error_message': result['message'],
            'missing_members': result.get('missing_members', []),
            'is_error': True,
            'is_simulation': is_simulation,
            'hide_base_chrome': is_simulation,
        })

    # 3. 데이터 병합
    full_schedule = result['schedule'] + pre_assigned

    full_schedule = _merge_contiguous_events(full_schedule)
    scheduled_song_ids_for_calc = {str(item['song'].id) for item in full_schedule if item.get('song')}
    _recompute_forced_flags(meeting, full_schedule, song_ids=scheduled_song_ids_for_calc)

    # 곡별 고정 색상 부여 (같은 곡은 항상 같은 색)
    song_color_map = {}
    sorted_songs = list(meeting.songs.order_by('id').values_list('id', flat=True))
    for idx, sid in enumerate(sorted_songs):
        song_color_map[str(sid)] = color_palette[idx % len(color_palette)]
    for item in full_schedule:
        item['song_color'] = song_color_map.get(str(item['song'].id), '#087f5b')

    # [NEW] 표시할 시간 범위 계산 (동적 범위)
    if full_schedule:
        # 가장 빠른 시작 시간과 가장 늦은 종료 시간 찾기
        min_idx = min(item['start'] for item in full_schedule)
        max_idx = max(item['end'] for item in full_schedule)

        # 앞뒤로 여유시간 1시간(2칸) 정도 주면 예쁨 (옵션)
        # 사용자가 "딱 그 시간만" 원했으므로 여유 없이 타이트하게 가거나,
        # 보기 좋게 짝수로 맞춤
        if min_idx % 2 != 0: min_idx -= 1
        if max_idx % 2 != 0: max_idx += 1
    else:
        min_idx, max_idx = 18, 44  # 기본값 (09:00 ~ 22:00)

    # 템플릿에서 반복문 돌리기 쉽게 range 객체 생성
    # range(start, stop, step) -> 2칸(1시간) 단위
    time_range_list = []
    for i in range(min_idx, max_idx, 2):
        hour = i // 2
        minute = "00" if i % 2 == 0 else "30"
        time_str = f"{hour}:{minute}"
        time_range_list.append((i, time_str))

    # 4. 주차별 그룹핑
    weekly_data = utils.group_schedule_by_week(
        meeting.practice_start_date,
        meeting.practice_end_date,
        full_schedule
    )
    required_slots_per_week = count * duration_slots
    assigned_slots_by_song_week = defaultdict(int)  # {(song_id, week_idx): slots}
    failed_song_weeks_map = defaultdict(set)  # {song_id: {week_idx, ...}}
    for week_idx, week in enumerate(weekly_data):
        for day in week['days']:
            for e in day['events']:
                sid = str(e['song'].id)
                assigned_slots_by_song_week[(sid, week_idx)] += max(1, int(e['end']) - int(e['start']))

    def _format_shortage_hours(slots):
        hours = slots / 2
        if float(hours).is_integer():
            return f"{int(hours)}시간"
        return f"{hours:.1f}시간"

    weekly_failed_map = defaultdict(list)
    week_count = len(weekly_data)
    matched_song_qs = (
        meeting.songs.filter(id__in=confirmed_song_ids)
        .prefetch_related('sessions__assignee')
        .order_by('title')
    )
    for song in matched_song_qs:
        sid = str(song.id)
        for week_idx in range(week_count):
            assigned_slots = assigned_slots_by_song_week.get((sid, week_idx), 0)
            shortage_slots = max(0, required_slots_per_week - assigned_slots)
            if shortage_slots <= 0:
                continue

            failed_song_weeks_map[sid].add(week_idx)
            weekly_failed_map[week_idx].append({
                'song_id': str(song.id),
                'song_title': song.title,
                'song_artist': song.artist or '',
                'song_color': song_color_map.get(str(song.id), '#087f5b'),
                'duration_slots': duration_slots,
                'failed_card_duration_slots': shortage_slots,
                'shortage_slots': shortage_slots,
                'shortage_hours_label': _format_shortage_hours(shortage_slots),
                'sessions': [
                    {
                        'name': sess.name,
                        'assignee': sess.assignee.realname if sess.assignee else None,
                    }
                    for sess in song.sessions.select_related('assignee').all()
                    if sess.assignee
                ],
            })

    failed_song_lookup = {
        str(s.id): s.title
        for s in meeting.songs.all()
    }
    failed_song_list = []
    for sid, weeks in failed_song_weeks_map.items():
        sorted_weeks = sorted(weeks)
        failed_song_list.append({
            'song_id': sid,
            'song_title': failed_song_lookup.get(sid, sid),
            'failed_weeks': [w + 1 for w in sorted_weeks],
            'failed_weeks_label': ", ".join(f"{w + 1}주차" for w in sorted_weeks),
        })
    failed_song_list.sort(key=lambda x: x['song_title'])
    failed_total_instances = sum(len(v) for v in weekly_failed_map.values())
    failed_song_ids = set(failed_song_weeks_map.keys())
    confirmed_song_id_set = {str(sid) for sid in confirmed_song_ids}
    completed_song_count = max(len(confirmed_song_id_set - failed_song_ids), 0)
    result['total_count'] = len(confirmed_song_ids)
    result['success_count'] = completed_song_count

    # 주차별 표시 시간 범위: 기본은 압축(최초 시작~마지막 시작)
    room_priority_rank = {}
    if room_preferred_ids:
        room_priority_rank = {str(rid): idx for idx, rid in enumerate(room_preferred_ids)}
    elif selected_room_ids:
        room_priority_rank = {str(rid): idx for idx, rid in enumerate(selected_room_ids)}

    def _room_rank_for_event(event_row):
        room_obj = event_row.get('room')
        room_id = str(getattr(room_obj, 'id', '') or '')
        return room_priority_rank.get(room_id, len(room_priority_rank) + 999)

    for idx, week in enumerate(weekly_data):
        starts = []
        ends = []
        for d in week['days']:
            for e in d['events']:
                starts.append(e['start'])
                ends.append(e['end'])
        if starts:
            w_min = min(starts)
            w_max_start = max(starts)
            w_max_end = max(ends) if ends else w_max_start + 1
            w_max = max(w_max_start, w_max_end - 1)
        else:
            w_min, w_max = 18, 36

        week['display_start_slot'] = w_min
        week['display_end_slot'] = w_max
        week['slot_count'] = (w_max - w_min + 1)
        week['time_range'] = []
        for i in range(w_min, w_max + 1):
            h = i // 2
            m = "00" if i % 2 == 0 else "30"
            week['time_range'].append((i, f"{h:02d}:{m}"))

        # 일자별 absolute 배치를 위한 좌표 계산 (lane: 같은 시간 겹침 시 가로 분할)
        for day in week['days']:
            events = day['events']
            if not events:
                day['lane_count'] = 1
                continue

            # 시작시각 기준 + 합주실 선호 순서 기준으로 lane 할당
            events.sort(key=lambda x: (x['start'], x['end'], _room_rank_for_event(x), str(x.get('song_title', ''))))
            lane_ends = []  # lane별 마지막 end
            for e in events:
                lane_idx = None
                for i, lane_end in enumerate(lane_ends):
                    if lane_end <= e['start']:
                        lane_idx = i
                        lane_ends[i] = e['end']
                        break
                if lane_idx is None:
                    lane_idx = len(lane_ends)
                    lane_ends.append(e['end'])
                e['lane_index'] = lane_idx
                e['top_slots'] = max(0, e['start'] - w_min)
                e['span_slots'] = max(1, e['end'] - e['start'])

            lane_count = max(1, len(lane_ends))
            day['lane_count'] = lane_count
            for e in events:
                e['lane_count'] = lane_count
                # 하루 전체 lane 수가 아니라, "해당 이벤트와 실제로 겹치는 이벤트 집합" 기준으로 폭 계산.
                # 표시 좌우 순서는 lane 배치 순이 아니라 합주실 선호 순서를 우선한다.
                overlapping = []
                for other in events:
                    if other['start'] < e['end'] and other['end'] > e['start']:
                        overlapping.append(other)
                ordered_overlapping = sorted(
                    overlapping,
                    key=lambda x: (_room_rank_for_event(x), x['start'], x['end'], str(x.get('song_title', '')))
                )
                e['display_lane_count'] = max(1, len(ordered_overlapping))
                e['display_lane_index'] = ordered_overlapping.index(e) if ordered_overlapping else 0
        week['failed_items'] = weekly_failed_map.get(idx, [])
        week['failed_count'] = len(week['failed_items'])
        week['is_complete'] = (week['failed_count'] == 0)

    completed_week_count = sum(1 for w in weekly_data if w.get('is_complete'))
    total_week_count = len(weekly_data)

    # 5. 곡 클릭 시 보여줄 "불가능 시간(사유: 멤버명)" 맵 계산
    # 매칭 단계에서는 미배치(failed) 카드도 오버레이를 보여줘야 하므로
    # "현재 스케줄에 올라간 곡"이 아니라 "배정 완료된 모든 곡" 기준으로 계산한다.
    song_conflict_map, song_member_map = _build_song_conflict_and_member_maps(
        meeting,
        song_ids=confirmed_song_ids,
    )

    active_rooms_qs = (
        _available_rooms_qs(meeting).filter(id__in=selected_room_ids).order_by('name')
        if selected_room_ids else
        _available_rooms_qs(meeting).order_by('name')
    )
    room_block_map = defaultdict(lambda: defaultdict(list))
    room_block_manual_map = defaultdict(lambda: defaultdict(set))
    room_block_detail_map = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    if meeting.practice_start_date and meeting.practice_end_date:
        block_qs = RoomBlock.objects.filter(
            room__in=active_rooms_qs,
            date__range=[meeting.practice_start_date, meeting.practice_end_date]
        ).exclude(source_meeting=meeting).select_related('room', 'source_meeting')
        source_meeting_ids = set()
        for b in block_qs:
            d_key = b.date.strftime('%Y-%m-%d')
            r_key = str(b.room_id)
            room_block_map[d_key][r_key].extend(list(range(b.start_index, b.end_index)))
            if b.source_meeting_id is None:
                room_block_manual_map[d_key][r_key].update(range(b.start_index, b.end_index))
            if b.source_meeting_id:
                source_meeting_ids.add(b.source_meeting_id)

        if source_meeting_ids:
            source_rows = PracticeSchedule.objects.filter(
                meeting_id__in=list(source_meeting_ids),
                room__in=active_rooms_qs,
                date__range=[meeting.practice_start_date, meeting.practice_end_date]
            ).select_related('meeting', 'song')
            for sch in source_rows:
                if sch.meeting_id == meeting.id:
                    continue
                d_key = sch.date.strftime('%Y-%m-%d')
                r_key = str(sch.room_id)
                label = f"[{sch.meeting.title}] - {sch.song.title}"
                for slot in range(int(sch.start_index), int(sch.end_index)):
                    room_block_detail_map[d_key][r_key][str(slot)].add(label)

    room_block_map_json_ready = {}
    for d_key, per_room in room_block_map.items():
        room_block_map_json_ready[d_key] = {}
        for r_key, slots in per_room.items():
            room_block_map_json_ready[d_key][r_key] = sorted(set(slots))

    room_block_manual_map_json_ready = {}
    for d_key, per_room in room_block_manual_map.items():
        room_block_manual_map_json_ready[d_key] = {}
        for r_key, slots in per_room.items():
            room_block_manual_map_json_ready[d_key][r_key] = sorted(set(int(s) for s in slots))

    room_block_detail_map_json_ready = {}
    for d_key, per_room in room_block_detail_map.items():
        room_block_detail_map_json_ready[d_key] = {}
        for r_key, per_slot in per_room.items():
            room_block_detail_map_json_ready[d_key][r_key] = {}
            for slot_key, labels in per_slot.items():
                room_block_detail_map_json_ready[d_key][r_key][slot_key] = sorted(set(labels))

    room_by_id = {str(r.id): r for r in active_rooms_qs}
    def _safe_int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return int(default)

    def _normalize_to_date(value):
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            pass
        try:
            return datetime.date.fromisoformat(raw[:10])
        except Exception:
            return None
    display_duration = _safe_int(effective_match_params.get('d'), duration)
    display_count = _safe_int(effective_match_params.get('c'), count)
    display_priority_order = [
        x.strip() for x in str(effective_match_params.get('p') or '').split(',') if x.strip()
    ] or list(MatchSettingsForm.DEFAULT_PRIORITY_ORDER)
    display_selected_room_ids = [
        x.strip() for x in str(effective_match_params.get('r') or '').split(',') if x.strip()
    ]
    display_room_preferred_ids = [
        x.strip() for x in str(effective_match_params.get('rp') or '').split(',') if x.strip()
    ]
    display_advanced_flags = {
        'exclude_weekends': str(effective_match_params.get('w', '0')) == '1',
        'room_efficiency_priority': str(effective_match_params.get('re', '0')) == '1',
        'hour_start_only': str(effective_match_params.get('h', '0')) == '1',
        'time_limit_start': _safe_int(effective_match_params.get('ts'), time_limit_start),
        'time_limit_end': _safe_int(effective_match_params.get('te'), time_limit_end),
    }
    advanced_option_labels = []
    if display_advanced_flags['exclude_weekends']:
        advanced_option_labels.append('주말 제외')
    if display_advanced_flags['room_efficiency_priority']:
        advanced_option_labels.append('예약 효율 우선')
    if display_advanced_flags['hour_start_only']:
        advanced_option_labels.append('정시 시작만 허용')
    if (
        display_advanced_flags['time_limit_start'] != 18
        or display_advanced_flags['time_limit_end'] != 48
    ):
        advanced_option_labels.append(
            f"시간 제한 {_slot_label(display_advanced_flags['time_limit_start'])}~{_slot_label(display_advanced_flags['time_limit_end'])}"
        )
    ordered_room_ids_for_display = display_room_preferred_ids or display_selected_room_ids or list(room_by_id.keys())
    room_preference_names = [room_by_id[rid].name for rid in ordered_room_ids_for_display if rid in room_by_id]
    shared_schedule_signature = ''
    if draft_obj and isinstance(draft_obj.events, list):
        shared_schedule_signature = _build_events_signature(draft_obj.events)

    context = {
        'meeting': meeting,
        'weeks': weekly_data,
        'failed': failed_song_list,
        'failed_song_list': failed_song_list,
        'failed_total_instances': failed_total_instances,
        'completed_week_count': completed_week_count,
        'total_week_count': total_week_count,
        'duration': duration,
        'count': count,
        'is_error': False,
        'time_range': time_range_list,  # [NEW] 시간 범위 전달
        'result': result,
        'song_conflict_map_json': json.dumps(song_conflict_map),
        'song_member_map_json': json.dumps(song_member_map),
        'song_color_map_json': json.dumps(song_color_map),
        'room_block_map_json': json.dumps(room_block_map_json_ready),
        'room_block_manual_map_json': json.dumps(room_block_manual_map_json_ready),
        'room_block_detail_map_json': json.dumps(room_block_detail_map_json_ready),
        'room_list_json': json.dumps([
            {'id': str(r.id), 'name': r.name, 'location': r.location or '-', 'capacity': int(r.capacity or 0)}
            for r in active_rooms_qs
        ]),
        'room_priority_order_json': json.dumps(
            [str(rid) for rid in (room_preferred_ids or selected_room_ids or list(active_rooms_qs.values_list('id', flat=True)))]
        ),
        'room_count': active_rooms_qs.count(),
        'is_simulation': is_simulation,
        'hide_base_chrome': is_simulation,
        'excluded_song_count': excluded_song_count,
        'is_booking_in_progress': bool(meeting.is_booking_in_progress),
        'share_warning_needed': bool(meeting.is_final_schedule_released),
        'schedule_stage_label': meeting.schedule_stage_label,
        'loaded_user_work_draft': bool(load_saved and user_work_draft),
        'effective_match_params_json': json.dumps(effective_match_params),
        'match_duration_minutes': display_duration,
        'match_required_count': display_count,
        'match_priority_labels': [
            next((label for key, label in MatchSettingsForm.PRIORITY_CHOICES if key == p), p)
            for p in display_priority_order
        ],
        'match_priority_custom': list(display_priority_order) != list(MatchSettingsForm.DEFAULT_PRIORITY_ORDER),
        'match_room_preference_names': room_preference_names,
        'match_advanced_flags': display_advanced_flags,
        'match_advanced_used': bool(match_advanced_used),
        'match_advanced_labels': advanced_option_labels,
        'match_time_limit_label': f"{_slot_label(_safe_int(effective_match_params.get('ts'), time_limit_start))}~{_slot_label(_safe_int(effective_match_params.get('te'), time_limit_end))}",
        'shared_schedule_signature': shared_schedule_signature,
        'booking_room_blocks_json': json.dumps([]),
    }

    # 재매칭 실행 직후 URL을 canonicalize해서 새로고침 시 재매칭 반복을 막는다.
    if (not is_simulation) and force_rematch:
        context['strip_force_rematch'] = True

    # 비시뮬레이션 매칭 결과(저장본 로드 제외)는 현재 사용자 작업 draft를 최신화한다.
    if (not is_simulation) and (not load_saved):
        serialized_events = []
        for item in full_schedule:
            room_obj = item.get('room')
            start_idx = int(item.get('start', 0))
            end_idx = int(item.get('end', start_idx + 1))
            serialized_events.append({
                'song_id': str(item['song'].id),
                'date': str(item['date']),
                'start': start_idx,
                'duration': max(1, end_idx - start_idx),
                'room_id': str(getattr(room_obj, 'id', '') or ''),
                'room_name': str(getattr(room_obj, 'name', '') or '-'),
                'room_location': str(getattr(room_obj, 'location', '') or ''),
                'is_forced': bool(item.get('is_forced', False)),
            })
        MeetingWorkDraft.objects.update_or_create(
            meeting=meeting,
            user=request.user,
            defaults={
                'events': serialized_events,
                'match_params': effective_match_params,
            }
        )

    return render(request, 'pracapp/match_result.html', context)


@login_required
def schedule_match_work_draft_save(request, meeting_id):
    """
    [AJAX] 현재 매칭 보드 상태를 사용자 개인 작업중 시간표로 저장.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    if _is_final_locked(meeting):
        return JsonResponse({'status': 'error', 'message': _final_lock_state_message(meeting)}, status=409)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식입니다.'}, status=400)

    raw_events = data.get('events') or []
    if not isinstance(raw_events, list):
        return JsonResponse({'status': 'error', 'message': 'events 형식이 잘못되었습니다.'}, status=400)
    raw_params = data.get('match_params') or {}
    if not isinstance(raw_params, dict):
        raw_params = {}

    MeetingWorkDraft.objects.update_or_create(
        meeting=meeting,
        user=request.user,
        defaults={
            'events': raw_events,
            'match_params': raw_params,
        }
    )

    return JsonResponse({
        'status': 'success',
        'redirect_url': f"{reverse('schedule_match_run', args=[meeting.id])}?load_saved=1",
    })


@login_required
def schedule_match_resume(request, meeting_id):
    """
    최종 일정 화면에서 조정 화면으로 복귀.
    저장된 매칭 설정을 사용해 match_run으로 이동하고 draft를 복원 로드한다.
    """
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if meeting.is_final_schedule_confirmed:
        messages.error(request, '최종 확정 이후에는 조정 모드로 돌아갈 수 없습니다. 초기화 후 다시 진행해주세요.')
        return redirect('schedule_final', meeting_id=meeting_id)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '권한이 없습니다.')
        return redirect('meeting_detail', pk=meeting_id)

    update_fields = []
    if not meeting.is_schedule_coordinating:
        meeting.is_schedule_coordinating = True
        update_fields.append('is_schedule_coordinating')
    if meeting.is_booking_in_progress:
        meeting.is_booking_in_progress = False
        update_fields.append('is_booking_in_progress')
    if meeting.is_final_schedule_confirmed:
        meeting.is_final_schedule_confirmed = False
        update_fields.append('is_final_schedule_confirmed')
    if update_fields:
        meeting.save(update_fields=update_fields)

    settings_session_key = f"match_settings_{meeting_id}"
    saved = request.session.get(settings_session_key) or {}
    has_user_work_draft = MeetingWorkDraft.objects.filter(
        meeting=meeting,
        user=request.user,
    ).exists()

    duration = int(saved.get('duration_minutes', 60))
    count = int(saved.get('required_count', 1))
    priority_param = ",".join(saved.get('priority_order', MatchSettingsForm.DEFAULT_PRIORITY_ORDER))
    room_param = ",".join(saved.get('room_ids', []))
    room_pref_param = ",".join(saved.get('room_priority_order', saved.get('room_ids', [])))
    weekend_param = '1' if saved.get('exclude_weekends') else '0'
    room_eff_param = '1' if saved.get('room_efficiency_priority', False) else '0'
    hour_start_param = '1' if saved.get('hour_start_only') else '0'
    limit_start_param = int(saved.get('time_limit_start', 18))
    limit_end_param = int(saved.get('time_limit_end', 48))

    resume_mode_param = 'load_saved=1' if has_user_work_draft else 'from_final=1'
    run_url = (
        f"{reverse('schedule_match_run', args=[meeting_id])}"
        f"?d={duration}&c={count}&p={priority_param}&r={room_param}&rp={room_pref_param}"
        f"&w={weekend_param}&re={room_eff_param}&h={hour_start_param}"
        f"&ts={limit_start_param}&te={limit_end_param}&{resume_mode_param}"
    )
    return redirect(run_url)


@login_required
def schedule_match_exit(request, meeting_id):
    """
    매칭 결과 화면을 벗어날 때 조율 상태를 해제한다.
    (최종 일정으로 이동하는 정상 플로우는 클라이언트에서 호출하지 않음)
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    if meeting.is_final_schedule_confirmed:
        return JsonResponse({'status': 'already', 'message': '이미 최종 확정된 일정입니다.', 'redirect_url': reverse('meeting_detail', kwargs={'pk': meeting.id})})

    if meeting.is_schedule_coordinating:
        meeting.is_schedule_coordinating = False
        meeting.save(update_fields=['is_schedule_coordinating'])

    return JsonResponse({'status': 'success'})


@login_required
def schedule_booking_start(request, meeting_id):
    """
    [AJAX] 관리자용 합주실 예약 확정 단계 진입.
    - 일반 멤버 화면은 그대로 두고 stage badge만 '예약중'으로 노출되도록 플래그를 전환한다.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    if meeting.is_final_schedule_confirmed:
        return JsonResponse({
            'status': 'already',
            'message': '이미 최종 확정된 일정입니다.',
            'redirect_url': reverse('schedule_final', args=[meeting.id]),
        })

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식입니다.'}, status=400)

    raw_events = data.get('events')
    if raw_events is not None and not isinstance(raw_events, list):
        return JsonResponse({'status': 'error', 'message': 'events 형식이 잘못되었습니다.'}, status=400)
    if not meeting.is_final_schedule_released:
        return JsonResponse({'status': 'error', 'message': '공유된 일정이 없습니다. 먼저 저장 후 공유를 진행해주세요.'}, status=409)

    # 예약 진입 직전에도 동일한 외부 충돌 검증을 수행해 경계 불일치를 제거한다.
    if isinstance(raw_events, list):
        song_ids = {str(e.get('song_id')) for e in raw_events if e.get('song_id')}
        songs_by_id = {str(s.id): s for s in meeting.songs.filter(id__in=song_ids)}
        rooms_by_id = {str(r.id): r for r in _available_rooms_qs(meeting, include_temporary=True)}
        normalized_preview = []
        for idx, ev in enumerate(raw_events):
            sid = str(ev.get('song_id') or '')
            if sid not in songs_by_id:
                return JsonResponse({'status': 'error', 'message': f'유효하지 않은 song_id (index={idx}).'}, status=400)
            try:
                d = datetime.date.fromisoformat(str(ev.get('date') or ''))
                start = int(ev.get('start'))
                duration = int(ev.get('duration'))
            except (TypeError, ValueError):
                return JsonResponse({'status': 'error', 'message': f'유효하지 않은 이벤트 값 (index={idx}).'}, status=400)
            if duration < 1:
                return JsonResponse({'status': 'error', 'message': f'유효하지 않은 duration (index={idx}).'}, status=400)
            end = start + duration
            if start < 18 or end > 48:
                return JsonResponse({'status': 'error', 'message': f'허용 범위를 벗어난 시간 (index={idx}).'}, status=400)

            room_id_raw = str(ev.get('room_id') or '')
            room_obj = rooms_by_id.get(room_id_raw)
            if room_obj is None:
                from types import SimpleNamespace
                room_obj = SimpleNamespace(
                    id=room_id_raw or f"temp-{sid}",
                    name=str(ev.get('room_name') or '').strip() or '임시합주실',
                    location=str(ev.get('room_location') or '').strip() or '-',
                )

            normalized_preview.append({
                'song': songs_by_id[sid],
                'date': d,
                'start': start,
                'end': end,
                'room': room_obj,
                'is_forced': bool(ev.get('is_forced', False)),
            })

        is_valid, conflict_message = _validate_normalized_events_against_external_conflicts(
            meeting,
            normalized_preview,
        )
        if not is_valid:
            return JsonResponse({
                'status': 'error',
                'message': conflict_message or '외부 일정과 충돌합니다.',
            }, status=409)

    # 예약 모드 진입 시점에 현재 조율 보드 상태를 공용 draft로 동기화한다.
    # (임시합주실 포함) -> booking 페이지에서 곡 소실 방지
    if isinstance(raw_events, list):
        draft_obj = MeetingFinalDraft.objects.filter(meeting=meeting).first()
        if not draft_obj or not isinstance(draft_obj.events, list):
            return JsonResponse({'status': 'error', 'message': '공유 기준 일정이 없습니다. 다시 공유 후 시도해주세요.'}, status=409)
        shared_sig = _build_events_signature(draft_obj.events)
        incoming_sig = _build_events_signature(raw_events)
        if shared_sig != incoming_sig:
            return JsonResponse({'status': 'error', 'message': '공유 이후 일정이 변경되었습니다. 다시 공유 후 예약을 진행해주세요.'}, status=409)
        MeetingFinalDraft.objects.update_or_create(
            meeting=meeting,
            defaults={
                'events': raw_events,
                'updated_by': request.user,
            }
        )

    update_fields = []
    if not meeting.is_booking_in_progress:
        meeting.is_booking_in_progress = True
        update_fields.append('is_booking_in_progress')
    if not meeting.is_final_schedule_released:
        meeting.is_final_schedule_released = True
        update_fields.append('is_final_schedule_released')
    if meeting.is_schedule_coordinating:
        meeting.is_schedule_coordinating = False
        update_fields.append('is_schedule_coordinating')
    if update_fields:
        meeting.save(update_fields=update_fields)

    return JsonResponse({
        'status': 'success',
        'redirect_url': f"{reverse('schedule_final', args=[meeting.id])}?mode=booking",
    })


@login_required
def schedule_final(request, meeting_id):
    """
    최종 확정된 합주 일정 조회 페이지
    - 리더/매니저/일반 멤버(승인됨) 접근 가능
    - match_result 보드 UI를 재사용하되 읽기 전용 모드로 렌더링
    """
    meeting = get_object_or_404(Meeting, id=meeting_id)
    membership = _get_approved_membership(meeting, request.user)
    if not membership:
        messages.error(request, '접근 권한이 없습니다.')
        return redirect('meeting_detail', pk=meeting.id)

    color_palette = [
        '#e03131', '#d9480f', '#f08c00', '#2b8a3e', '#0b7285',
        '#1971c2', '#364fc7', '#5f3dc4', '#862e9c', '#c2255c',
        '#087f5b', '#6741d9', '#1864ab', '#9c36b5',
        '#ff8787', '#f783ac', '#a61e4d', '#ff6b6b', '#ffd43b',
        '#ffa94d', '#e67700', '#fab005', '#69db7c', '#94d82d',
        '#5c940d', '#2f9e44', '#c0eb75', '#3bc9db', '#66d9e8',
        '#1098ad', '#20c997', '#4dabf7', '#748ffc', '#3b5bdb',
        '#4263eb', '#da77f2', '#be4bdb', '#ae3ec9', '#a52a2a'
    ]

    is_manager_role = _has_meeting_manager_permission(meeting, request.user, membership=membership)
    view_mode = str(request.GET.get('mode') or '').strip().lower()
    is_booking_confirm_view = bool(
        is_manager_role
        and (not meeting.is_final_schedule_confirmed)
        and view_mode == 'booking'
    )
    draft_obj = MeetingFinalDraft.objects.filter(meeting=meeting).first()
    draft_events = draft_obj.events if draft_obj else None
    # 예약 페이지(mode=booking)는 항상 공용 공유본(MeetingFinalDraft)을 기준으로 본다.
    # 개인 작업중 저장본(MeetingWorkDraft)은 합주 조율 페이지에서만 로드한다.
    loaded_user_work_draft = False
    has_confirmed_rows = PracticeSchedule.objects.filter(meeting=meeting).exists()
    is_confirmed_final = bool(
        meeting.is_final_schedule_confirmed
        or (
            has_confirmed_rows
            and not draft_events
            and not meeting.is_schedule_coordinating
            and not meeting.is_final_schedule_released
        )
    )
    if is_confirmed_final:
        draft_events = None

    # 일반 멤버는 관리자가 최종 일정을 공개했거나, 이미 최종 확정된 경우에만 접근 가능
    if (not is_manager_role) and (not meeting.is_final_schedule_released) and (not is_confirmed_final):
        messages.error(request, '아직 관리자가 최종 합주 일정을 공개하지 않았습니다.')
        return redirect('meeting_detail', pk=meeting.id)
    # 일반 멤버는 관리자가 조율 중(미공유 변경 존재)인 임시 일정 화면에 접근할 수 없다.
    if (not is_manager_role) and meeting.is_schedule_coordinating and (not is_confirmed_final):
        messages.info(request, '관리자가 임시 합주 일정을 수정 중입니다. 공유 후 다시 확인해주세요.')
        return redirect('meeting_detail', pk=meeting.id)

    db_schedules = (
        PracticeSchedule.objects
        .filter(meeting=meeting)
        .select_related('song', 'room')
        .order_by('date', 'start_index', 'song__title')
    )
    # 공개 상태여도 표시 가능한 공개본 데이터가 비어 있으면 일반 멤버 접근 차단
    if not is_manager_role:
        has_public_draft = bool(draft_events and isinstance(draft_events, list) and len(draft_events) > 0)
        has_public_confirmed = bool(has_confirmed_rows)
        if (not has_public_draft) and (not has_public_confirmed):
            messages.info(request, '공개된 임시 합주 일정이 아직 준비되지 않았습니다.')
            return redirect('meeting_detail', pk=meeting.id)
    full_schedule = []
    if draft_events:
        songs_by_id = {str(s.id): s for s in meeting.songs.all()}
        rooms_by_id = {str(r.id): r for r in _available_rooms_qs(meeting)}
        for ev in draft_events:
            sid = str(ev.get('song_id') or '')
            song = songs_by_id.get(sid)
            if not song:
                continue
            try:
                target_date = datetime.date.fromisoformat(str(ev.get('date') or ''))
                start = int(ev.get('start'))
                duration = int(ev.get('duration'))
            except (TypeError, ValueError):
                continue
            if duration < 1:
                continue
            end = start + duration
            room_id_raw = str(ev.get('room_id') or '')
            room_name_raw = str(ev.get('room_name') or '').strip() or '임시합주실'
            room_location_raw = str(ev.get('room_location') or '').strip()
            room_obj = rooms_by_id.get(room_id_raw)
            if room_obj is None:
                from types import SimpleNamespace
                room_obj = SimpleNamespace(
                    id=room_id_raw or f"temp-{sid}",
                    name=room_name_raw,
                    location=room_location_raw or '-'
                )
            full_schedule.append({
                'song': song,
                'song_title': song.title,
                'room': room_obj,
                'date': target_date.strftime('%Y-%m-%d'),
                'start': start,
                'end': end,
                'is_forced': bool(ev.get('is_forced', False)),
                'is_fixed': True,
            })
    else:
        for sch in db_schedules:
            full_schedule.append({
                'song': sch.song,
                'song_title': sch.song.title,
                'room': sch.room,
                'date': sch.date.strftime('%Y-%m-%d'),
                'start': sch.start_index,
                'end': sch.end_index,
                'is_forced': bool(sch.is_forced),
                'is_fixed': True,
            })

    def _merge_contiguous_events(events):
        buckets = defaultdict(list)
        for e in events:
            key = (
                e['date'],
                str(e['song'].id),
                str(e['room'].id),
                e.get('is_fixed', False),
                e.get('is_forced', False),
            )
            buckets[key].append(e)

        merged = []
        for rows in buckets.values():
            rows.sort(key=lambda x: x['start'])
            acc = None
            for row in rows:
                if acc is None:
                    acc = dict(row)
                    continue
                if row['start'] <= acc['end']:
                    acc['end'] = max(acc['end'], row['end'])
                else:
                    merged.append(acc)
                    acc = dict(row)
            if acc is not None:
                merged.append(acc)
        merged.sort(key=lambda x: (x['date'], x['start'], x['song_title']))
        return merged

    full_schedule = _merge_contiguous_events(full_schedule)
    scheduled_song_ids_for_calc = {str(item['song'].id) for item in full_schedule if item.get('song')}
    _recompute_forced_flags(meeting, full_schedule, song_ids=scheduled_song_ids_for_calc)

    song_color_map = {}
    sorted_songs = list(meeting.songs.order_by('id').values_list('id', flat=True))
    for idx, sid in enumerate(sorted_songs):
        song_color_map[str(sid)] = color_palette[idx % len(color_palette)]
    for item in full_schedule:
        item['song_color'] = song_color_map.get(str(item['song'].id), '#087f5b')

    weekly_data = utils.group_schedule_by_week(
        meeting.practice_start_date,
        meeting.practice_end_date,
        full_schedule
    ) if (meeting.practice_start_date and meeting.practice_end_date) else []

    def _safe_int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return int(default)

    def _normalize_to_date(value):
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        raw = str(value or '').strip()
        if not raw:
            return None
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            pass
        try:
            return datetime.date.fromisoformat(raw[:10])
        except Exception:
            return None

    # 최종 페이지의 미배치 계산은 "현재 보드와 동일한 작업본"의 파라미터를 우선 사용한다.
    # 현재 사용자 작업본이 아니어도 시그니처가 일치하면 동일 보드로 간주한다.
    reliable_params = {}
    current_board_events = []
    for item in full_schedule:
        song_obj = item.get('song')
        room_obj = item.get('room')
        if not song_obj or not room_obj:
            continue
        start = int(item.get('start', 0))
        end = int(item.get('end', start))
        current_board_events.append({
            'song_id': str(song_obj.id),
            'date': str(item.get('date') or ''),
            'start': start,
            'duration': max(1, end - start),
            'room_id': str(getattr(room_obj, 'id', '') or ''),
            'is_forced': bool(item.get('is_forced', False)),
        })
    current_board_signature = _build_events_signature(current_board_events)
    candidate_drafts = MeetingWorkDraft.objects.filter(meeting=meeting).order_by('-updated_at')
    for wd in candidate_drafts:
        if not isinstance(wd.events, list):
            continue
        if _build_events_signature(wd.events) != current_board_signature:
            continue
        if isinstance(wd.match_params, dict):
            reliable_params = wd.match_params
            break

    if not reliable_params:
        my_latest_draft = MeetingWorkDraft.objects.filter(meeting=meeting, user=request.user).order_by('-updated_at').first()
        if my_latest_draft and isinstance(my_latest_draft.match_params, dict):
            reliable_params = my_latest_draft.match_params

    def _parse_csv_or_list(raw):
        if isinstance(raw, (list, tuple)):
            return [str(x).strip() for x in raw if str(x).strip()]
        txt = str(raw or '').strip()
        if not txt:
            return []
        return [x.strip() for x in txt.split(',') if x.strip()]

    selected_room_ids_for_view = _parse_csv_or_list(reliable_params.get('r'))
    preferred_room_ids_for_view = _parse_csv_or_list(reliable_params.get('rp'))
    ordered_room_ids_for_view = [rid for rid in preferred_room_ids_for_view if rid in selected_room_ids_for_view]
    for rid in selected_room_ids_for_view:
        if rid not in ordered_room_ids_for_view:
            ordered_room_ids_for_view.append(rid)

    duration_minutes = _safe_int(reliable_params.get('d'), 30)
    required_count = max(1, _safe_int(reliable_params.get('c'), 1))
    duration_slots = max(1, int(duration_minutes // 30))
    required_slots_per_week = max(1, duration_slots * required_count)

    def _format_shortage_hours(slots):
        hours = (slots * 30) / 60
        if float(hours).is_integer():
            return f"{int(hours)}시간"
        return f"{hours:.1f}시간"

    date_to_week_idx = {}
    for idx, week in enumerate(weekly_data):
        for d in week.get('days', []):
            d_obj = _normalize_to_date(d.get('date'))
            if d_obj:
                date_to_week_idx[d_obj] = idx

    assigned_slots_by_song_week = defaultdict(int)
    for item in full_schedule:
        song_obj = item.get('song')
        if not song_obj:
            continue
        d_obj = _normalize_to_date(item.get('date'))
        week_idx = date_to_week_idx.get(d_obj) if d_obj else None
        if week_idx is None:
            continue
        sid = str(song_obj.id)
        span_slots = max(0, int(item.get('end', 0)) - int(item.get('start', 0)))
        assigned_slots_by_song_week[(sid, week_idx)] += span_slots

    weekly_failed_map = defaultdict(list)
    eligible_song_ids = set(str(sid) for sid in _fully_assigned_song_ids(meeting))
    matched_song_qs = (
        meeting.songs.filter(id__in=eligible_song_ids)
        .prefetch_related('sessions__assignee')
        .order_by('title')
    )
    for song in matched_song_qs:
        sid = str(song.id)
        for week_idx in range(len(weekly_data)):
            assigned_slots = assigned_slots_by_song_week.get((sid, week_idx), 0)
            shortage_slots = max(0, required_slots_per_week - assigned_slots)
            if shortage_slots <= 0:
                continue
            weekly_failed_map[week_idx].append({
                'song_id': str(song.id),
                'song_title': song.title,
                'song_artist': song.artist or '',
                'song_color': song_color_map.get(str(song.id), '#087f5b'),
                'duration_slots': duration_slots,
                'failed_card_duration_slots': shortage_slots,
                'shortage_slots': shortage_slots,
                'shortage_hours_label': _format_shortage_hours(shortage_slots),
                'sessions': [
                    {
                        'name': sess.name,
                        'assignee': sess.assignee.realname if sess.assignee else None,
                    }
                    for sess in song.sessions.select_related('assignee').all()
                    if sess.assignee
                ],
            })

    for idx, week in enumerate(weekly_data):
        starts = []
        ends = []
        for d in week['days']:
            for e in d['events']:
                starts.append(e['start'])
                ends.append(e['end'])
        if starts:
            w_min = min(starts)
            w_max_start = max(starts)
            w_max_end = max(ends) if ends else w_max_start + 1
            w_max = max(w_max_start, w_max_end - 1)
        else:
            w_min, w_max = 18, 36

        week['display_start_slot'] = w_min
        week['display_end_slot'] = w_max
        week['slot_count'] = (w_max - w_min + 1)
        week['time_range'] = []
        for i in range(w_min, w_max + 1):
            h = i // 2
            m = "00" if i % 2 == 0 else "30"
            week['time_range'].append((i, f"{h:02d}:{m}"))

        for day in week['days']:
            events = day['events']
            if not events:
                day['lane_count'] = 1
                continue

            events.sort(key=lambda x: (x['start'], x['end'], x['song_title']))
            lane_ends = []
            for e in events:
                lane_idx = None
                for i, lane_end in enumerate(lane_ends):
                    if lane_end <= e['start']:
                        lane_idx = i
                        lane_ends[i] = e['end']
                        break
                if lane_idx is None:
                    lane_idx = len(lane_ends)
                    lane_ends.append(e['end'])
                e['lane_index'] = lane_idx
                e['top_slots'] = max(0, e['start'] - w_min)
                e['span_slots'] = max(1, e['end'] - e['start'])

            lane_count = max(1, len(lane_ends))
            day['lane_count'] = lane_count
            for e in events:
                overlapping = []
                for other in events:
                    if other['start'] < e['end'] and other['end'] > e['start']:
                        overlapping.append(other)

                active_lane_indices = sorted({x['lane_index'] for x in overlapping})
                e['display_lane_count'] = max(1, len(active_lane_indices))
                e['display_lane_index'] = active_lane_indices.index(e['lane_index']) if active_lane_indices else 0

        week['failed_items'] = weekly_failed_map.get(idx, [])
        week['failed_count'] = len(week['failed_items'])
        week['is_complete'] = (week['failed_count'] == 0)

    completed_week_count = sum(1 for w in weekly_data if w.get('is_complete'))
    total_week_count = len(weekly_data)
    scheduled_song_ids = {str(e.get('song_id')) for e in (draft_events or []) if e.get('song_id')} if draft_events else {
        str(sid) for sid in PracticeSchedule.objects.filter(meeting=meeting).values_list('song_id', flat=True)
    }
    result = {
        'total_count': len(eligible_song_ids),
        'success_count': len(scheduled_song_ids & eligible_song_ids),
    }

    my_song_ids = [
        str(sid) for sid in meeting.songs.filter(sessions__assignee=request.user).distinct().values_list('id', flat=True)
    ]

    participant_ids = list(
        meeting.songs.filter(sessions__assignee__isnull=False)
        .values_list('sessions__assignee_id', flat=True)
        .distinct()
    )
    booking_saved_completed_keys = []
    if is_booking_confirm_view and is_manager_role:
        user_work_draft = MeetingWorkDraft.objects.filter(meeting=meeting, user=request.user).first()
        current_board_signature = _build_events_signature(draft_events) if isinstance(draft_events, list) else ''
        if user_work_draft and isinstance(user_work_draft.match_params, dict):
            saved_keys = user_work_draft.match_params.get('booking_completed_keys') or []
            saved_signature = str(user_work_draft.match_params.get('booking_completed_signature') or '')
            if (
                isinstance(saved_keys, list)
                and saved_signature
                and current_board_signature
                and saved_signature == current_board_signature
            ):
                booking_saved_completed_keys = [str(k) for k in saved_keys if str(k).strip()]
    participants = list(User.objects.filter(id__in=participant_ids).order_by('realname', 'username'))
    confirmed_ids = set(
        MeetingScheduleConfirmation.objects.filter(
            meeting=meeting,
            version=meeting.schedule_version,
            user_id__in=participant_ids,
        )
        .values_list('user_id', flat=True)
    ) if participant_ids else set()
    my_confirm = (
        MeetingScheduleConfirmation.objects.filter(
            meeting=meeting,
            version=meeting.schedule_version,
            user=request.user,
        ).first()
        if request.user.id in participant_ids else None
    )
    unconfirmed_users = [u for u in participants if u.id not in confirmed_ids]
    confirmed_users = [u for u in participants if u.id in confirmed_ids]
    song_conflict_map, song_member_map = _build_song_conflict_and_member_maps(
        meeting,
        song_ids=scheduled_song_ids_for_calc,
    )
    room_rows = list(_available_rooms_qs(meeting).order_by('name'))
    booking_room_blocks = list(
        RoomBlock.objects.filter(
            source_meeting__isnull=True,
            room__in=room_rows,
        ).select_related('room').order_by('date', 'start_index', 'room__name')
    ) if (is_booking_confirm_view and is_manager_role) else []
    booking_all_room_blocks = list(
        RoomBlock.objects.filter(
            room__in=room_rows,
            date__range=[meeting.practice_start_date, meeting.practice_end_date],
        ).exclude(source_meeting=meeting).select_related('room', 'source_meeting').order_by('date', 'start_index', 'room__name')
    ) if (is_booking_confirm_view and is_manager_role and meeting.practice_start_date and meeting.practice_end_date) else []
    room_block_map_json_ready = {}
    room_block_manual_map_json_ready = {}
    room_block_detail_map_json_ready = {}
    my_unavailable_slots_json_ready = {}
    if meeting.practice_start_date and meeting.practice_end_date and request.user.is_authenticated:
        busy_data = utils.get_busy_events(
            request.user,
            meeting.practice_start_date,
            meeting.practice_end_date,
        )
        for d_key, events in (busy_data or {}).items():
            slot_reason_map = defaultdict(set)
            for ev in (events or []):
                try:
                    s_idx = int(ev.get('start'))
                    e_idx = int(ev.get('end'))
                except (TypeError, ValueError):
                    continue
                if e_idx <= s_idx:
                    continue
                reason = str(ev.get('reason') or '').strip() or '개인 일정'
                for slot in range(s_idx, e_idx):
                    slot_reason_map[str(int(slot))].add(reason)

            cleaned_slots = {}
            for slot_idx, reasons in slot_reason_map.items():
                reason_list = sorted(set(str(r).strip() for r in (reasons or set()) if str(r).strip()))
                if reason_list:
                    cleaned_slots[str(slot_idx)] = reason_list
            if cleaned_slots:
                my_unavailable_slots_json_ready[str(d_key)] = cleaned_slots
    if is_booking_confirm_view and meeting.practice_start_date and meeting.practice_end_date:
        source_meeting_ids = set()
        for b in booking_all_room_blocks:
            d_key = b.date.strftime('%Y-%m-%d')
            r_key = str(b.room_id)
            room_block_map_json_ready.setdefault(d_key, {}).setdefault(r_key, [])
            room_block_map_json_ready[d_key][r_key].extend(list(range(b.start_index, b.end_index)))
            if b.source_meeting_id is None:
                room_block_manual_map_json_ready.setdefault(d_key, {}).setdefault(r_key, set())
                room_block_manual_map_json_ready[d_key][r_key].update(range(b.start_index, b.end_index))
            if b.source_meeting_id:
                source_meeting_ids.add(b.source_meeting_id)
        for d_key, per_room in room_block_map_json_ready.items():
            for r_key, slots in per_room.items():
                room_block_map_json_ready[d_key][r_key] = sorted(set(slots))
        for d_key, per_room in room_block_manual_map_json_ready.items():
            for r_key, slots in per_room.items():
                room_block_manual_map_json_ready[d_key][r_key] = sorted(set(int(s) for s in slots))

        if source_meeting_ids:
            source_rows = PracticeSchedule.objects.filter(
                meeting_id__in=list(source_meeting_ids),
                room__in=room_rows,
                date__range=[meeting.practice_start_date, meeting.practice_end_date],
            ).select_related('meeting', 'song')
            for sch in source_rows:
                if sch.meeting_id == meeting.id:
                    continue
                d_key = sch.date.strftime('%Y-%m-%d')
                r_key = str(sch.room_id)
                label = f"[{sch.meeting.title}] - {sch.song.title}"
                for slot in range(int(sch.start_index), int(sch.end_index)):
                    room_block_detail_map_json_ready.setdefault(d_key, {}).setdefault(r_key, {}).setdefault(str(slot), set()).add(label)
            for d_key, per_room in room_block_detail_map_json_ready.items():
                for r_key, per_slot in per_room.items():
                    for slot_key, labels in per_slot.items():
                        per_slot[slot_key] = sorted(set(labels))

    context = {
        'meeting': meeting,
        'weeks': weekly_data,
        'failed': [],
        'failed_song_list': [],
        'failed_total_instances': 0,
        'completed_week_count': completed_week_count,
        'total_week_count': total_week_count,
        'duration': 60,
        'count': 1,
        'is_error': False,
        'result': result,
        'song_conflict_map_json': json.dumps(song_conflict_map),
        'song_member_map_json': json.dumps(song_member_map),
        'song_color_map_json': json.dumps(song_color_map),
        'room_block_map_json': json.dumps(room_block_map_json_ready),
        'room_block_manual_map_json': json.dumps(room_block_manual_map_json_ready),
        'room_block_detail_map_json': json.dumps(room_block_detail_map_json_ready),
        'room_list_json': json.dumps([
            {'id': str(r.id), 'name': r.name, 'location': r.location or '-', 'capacity': int(r.capacity or 0)}
            for r in room_rows
        ]),
        'room_priority_order_json': json.dumps(
            ordered_room_ids_for_view or [str(r.id) for r in room_rows]
        ),
        'effective_match_params_json': json.dumps({
            'r': ",".join(selected_room_ids_for_view),
            'rp': ",".join(ordered_room_ids_for_view),
        }),
        'my_unavailable_slots_json': json.dumps(my_unavailable_slots_json_ready, ensure_ascii=False),
        'room_count': len(room_rows),
        'is_final_view': True,
        'is_booking_confirm_view': is_booking_confirm_view,
        'my_song_ids_json': json.dumps(my_song_ids),
        'is_draft_view': bool(draft_events),
        'can_confirm_final': (
            is_manager_role
            and (not is_confirmed_final)
            and (is_booking_confirm_view or (not meeting.is_booking_in_progress))
        ),
        'is_manager_role': is_manager_role,
        'is_booking_in_progress': bool(meeting.is_booking_in_progress),
        'share_warning_needed': bool(meeting.is_final_schedule_released),
        'schedule_stage_label': meeting.schedule_stage_label,
        'loaded_user_work_draft': bool(loaded_user_work_draft),
        'participant_count': len(participants),
        'confirmed_count': len(confirmed_users),
        'confirmed_users': confirmed_users,
        'unconfirmed_users': unconfirmed_users,
        'can_acknowledge_schedule': (
            (not is_manager_role)
            and (request.user.id in participant_ids)
            and (not meeting.is_booking_in_progress)
        ),
        'has_acknowledged_schedule': bool(my_confirm),
        'my_acknowledged_at': my_confirm.confirmed_at if my_confirm else None,
        'is_confirmed_final': is_confirmed_final,
        'booking_room_blocks_json': json.dumps([
            {
                'id': str(b.id),
                'room_id': str(b.room_id),
                'room_name': b.room.name,
                'date': b.date.strftime('%Y-%m-%d'),
                'start': int(b.start_index),
                'end': int(b.end_index),
            }
            for b in booking_room_blocks
        ]),
        'booking_saved_completed_keys_json': json.dumps(booking_saved_completed_keys),
        'song_participant_song_ids_json': json.dumps([
            str(sid) for sid in Session.objects.filter(
                song__meeting=meeting,
                assignee=request.user,
            ).values_list('song_id', flat=True).distinct()
        ]),
        'extra_practice_schedules_json': json.dumps([
            {
                'id': str(eps.id),
                'song_id': str(eps.song_id),
                'song_title': eps.song.title,
                'song_artist': eps.song.artist,
                'room_id': str(eps.room_id),
                'room_name': eps.room.name,
                'date': eps.date.strftime('%Y-%m-%d'),
                'start': eps.start_index,
                'end': eps.end_index,
            }
            for eps in ExtraPracticeSchedule.objects.filter(
                meeting=meeting
            ).select_related('song', 'room').order_by('date', 'start_index')
        ], ensure_ascii=False),
    }
    return render(request, 'pracapp/match_result.html', context)


@login_required
def schedule_room_block_manage(request, meeting_id):
    """
    [AJAX] 부킹 모드에서 합주실 예약 불가 일정을 추가/삭제.
    """
    if request.method not in ['POST', 'DELETE']:
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    if meeting.is_final_schedule_confirmed:
        return JsonResponse({'status': 'error', 'message': '최종 확정 이후에는 변경할 수 없습니다.'}, status=409)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식입니다.'}, status=400)

    if request.method == 'POST':
        room_id = str(data.get('room_id') or '').strip()
        date_str = str(data.get('date') or '').strip()
        start = data.get('start')
        end = data.get('end')
        if not room_id or not date_str or start is None or end is None:
            return JsonResponse({'status': 'error', 'message': '필수 값이 누락되었습니다.'}, status=400)
        try:
            target_date = datetime.date.fromisoformat(date_str)
            start = int(start)
            end = int(end)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': '날짜/시간 값이 유효하지 않습니다.'}, status=400)
        if start < 18 or end > 48 or start >= end:
            return JsonResponse({'status': 'error', 'message': '시간 범위가 올바르지 않습니다.'}, status=400)

        room = get_object_or_404(_available_rooms_qs(meeting), id=room_id)
        block, created = RoomBlock.objects.get_or_create(
            room=room,
            date=target_date,
            start_index=start,
            end_index=end,
            source_meeting=None,
        )
        return JsonResponse({
            'status': 'success',
            'created': bool(created),
            'block': {
                'id': str(block.id),
                'room_id': str(block.room_id),
                'room_name': room.name,
                'date': target_date.strftime('%Y-%m-%d'),
                'start': start,
                'end': end,
            },
        })

    block_id = str(data.get('block_id') or '').strip()
    if not block_id:
        return JsonResponse({'status': 'error', 'message': 'block_id가 필요합니다.'}, status=400)
    block = get_object_or_404(
        RoomBlock.objects.select_related('room'),
        id=block_id,
        source_meeting__isnull=True,
        room__in=_available_rooms_qs(meeting),
    )
    block.delete()
    return JsonResponse({'status': 'success'})


@login_required
def schedule_final_prepare(request, meeting_id):
    """
    [AJAX] match_result 상태를 DB 저장 없이 공용 draft(DB)로 넘기고 최종 일정 페이지로 이동
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    if _is_final_locked(meeting):
        return JsonResponse({'status': 'error', 'message': _final_lock_state_message(meeting)}, status=409)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식입니다.'}, status=400)

    raw_events = data.get('events') or []
    if not isinstance(raw_events, list):
        return JsonResponse({'status': 'error', 'message': 'events 형식이 잘못되었습니다.'}, status=400)

    # 공유 직전에도 저장 단계와 동일한 외부 충돌 검증을 수행한다.
    song_ids = {str(e.get('song_id')) for e in raw_events if e.get('song_id')}
    songs_by_id = {str(s.id): s for s in meeting.songs.filter(id__in=song_ids)}
    rooms_by_id = {str(r.id): r for r in _available_rooms_qs(meeting, include_temporary=True)}
    normalized_preview = []
    for idx, ev in enumerate(raw_events):
        sid = str(ev.get('song_id') or '')
        if sid not in songs_by_id:
            return JsonResponse({'status': 'error', 'message': f'유효하지 않은 song_id (index={idx}).'}, status=400)
        try:
            d = datetime.date.fromisoformat(str(ev.get('date') or ''))
            start = int(ev.get('start'))
            duration = int(ev.get('duration'))
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': f'유효하지 않은 이벤트 값 (index={idx}).'}, status=400)
        if duration < 1:
            return JsonResponse({'status': 'error', 'message': f'유효하지 않은 duration (index={idx}).'}, status=400)
        end = start + duration
        if start < 18 or end > 48:
            return JsonResponse({'status': 'error', 'message': f'허용 범위를 벗어난 시간 (index={idx}).'}, status=400)

        room_id_raw = str(ev.get('room_id') or '')
        room_obj = rooms_by_id.get(room_id_raw)
        if room_obj is None:
            from types import SimpleNamespace
            room_obj = SimpleNamespace(
                id=room_id_raw or f"temp-{sid}",
                name=str(ev.get('room_name') or '').strip() or '임시합주실',
                location=str(ev.get('room_location') or '').strip() or '-',
            )

        normalized_preview.append({
            'song': songs_by_id[sid],
            'date': d,
            'start': start,
            'end': end,
            'room': room_obj,
            'is_forced': bool(ev.get('is_forced', False)),
        })

    is_valid, conflict_message = _validate_normalized_events_against_external_conflicts(
        meeting,
        normalized_preview,
    )
    if not is_valid:
        return JsonResponse({
            'status': 'error',
            'message': conflict_message or '외부 일정과 충돌합니다.',
        }, status=409)

    with transaction.atomic():
        locked_meeting = Meeting.objects.select_for_update().get(id=meeting.id)
        if _is_final_locked(locked_meeting):
            return JsonResponse({'status': 'error', 'message': _final_lock_state_message(locked_meeting)}, status=409)

        MeetingFinalDraft.objects.update_or_create(
            meeting=locked_meeting,
            defaults={
                'events': raw_events,
                'updated_by': request.user,
            }
        )
        # 공유 직후 조율 페이지를 다시 열어도 동일한 보드를 보도록 개인 작업본도 동기화
        MeetingWorkDraft.objects.update_or_create(
            meeting=locked_meeting,
            user=request.user,
            defaults={
                'events': raw_events,
            }
        )

        update_kwargs = {
            'schedule_version': F('schedule_version') + 1,
        }
        if locked_meeting.is_schedule_coordinating:
            update_kwargs['is_schedule_coordinating'] = False
        if locked_meeting.is_booking_in_progress:
            update_kwargs['is_booking_in_progress'] = False
        if not locked_meeting.is_final_schedule_released:
            update_kwargs['is_final_schedule_released'] = True

        Meeting.objects.filter(id=locked_meeting.id).update(**update_kwargs)

    return JsonResponse({
        'status': 'success',
        'redirect_url': reverse('schedule_final', args=[meeting.id]),
    })


@login_required
def schedule_save_result(request, meeting_id):
    """
    [AJAX] match_result 현재 상태를 최종 확정 저장
    - 화면의 이벤트 목록을 받아 PracticeSchedule로 덮어쓰기 저장
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    if meeting.is_final_schedule_confirmed:
        return JsonResponse({
            'status': 'already',
            'message': '이미 최종 확정된 일정입니다.',
            'redirect_url': reverse('schedule_final', args=[meeting.id]),
        })
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    can_create_room = _has_meeting_manager_permission(meeting, request.user, membership=membership)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식입니다.'}, status=400)

    raw_events = data.get('events') or []
    if not isinstance(raw_events, list):
        return JsonResponse({'status': 'error', 'message': 'events 형식이 잘못되었습니다.'}, status=400)
    booking_completed_keys_raw = data.get('booking_completed_keys') or []
    if booking_completed_keys_raw and not isinstance(booking_completed_keys_raw, list):
        return JsonResponse({'status': 'error', 'message': 'booking_completed_keys 형식이 잘못되었습니다.'}, status=400)
    booking_completed_keys = set(str(x) for x in booking_completed_keys_raw if str(x).strip())

    # 예약 단계에서는 프론트 체크 우회 방지를 위해 서버에서 '예약 완료 여부'를 재검증한다.
    if meeting.is_booking_in_progress:
        normal_room_ids = set(
            str(rid) for rid in _available_rooms_qs(meeting).values_list('id', flat=True)
        )
        candidate_dates = set()
        candidate_room_ids = set()
        parsed_for_booking_gate = []
        for idx, ev in enumerate(raw_events):
            try:
                d = datetime.date.fromisoformat(str(ev.get('date') or ''))
                start = int(ev.get('start'))
                duration = int(ev.get('duration'))
            except (TypeError, ValueError):
                return JsonResponse({'status': 'error', 'message': f'유효하지 않은 예약 검증 값 (index={idx}).'}, status=400)
            if duration < 1:
                return JsonResponse({'status': 'error', 'message': f'유효하지 않은 예약 검증 duration (index={idx}).'}, status=400)
            room_id = str(ev.get('room_id') or '')
            end = start + duration
            parsed_for_booking_gate.append({
                'song_id': str(ev.get('song_id') or ''),
                'date_obj': d,
                'date': d.strftime('%Y-%m-%d'),
                'start': start,
                'duration': duration,
                'end': end,
                'room_id': room_id,
                'is_forced': bool(ev.get('is_forced', False)),
            })
            if room_id in normal_room_ids:
                candidate_dates.add(d)
                candidate_room_ids.add(room_id)

        room_blocks_by_room_date = defaultdict(list)
        if candidate_room_ids and candidate_dates:
            booking_blocks = RoomBlock.objects.filter(
                source_meeting__isnull=True,
                room_id__in=list(candidate_room_ids),
                date__in=list(candidate_dates),
            ).values('room_id', 'date', 'start_index', 'end_index')
            for row in booking_blocks:
                key = (str(row['room_id']), row['date'])
                room_blocks_by_room_date[key].append((int(row['start_index']), int(row['end_index'])))

        required_booking_keys = set()
        for item in parsed_for_booking_gate:
            if item['is_forced']:
                continue
            room_id = item['room_id']
            # 임시합주실은 예약 불가 블록 판정에서 제외(클라이언트와 동일 정책)
            if room_id in normal_room_ids:
                blocked = False
                for b_start, b_end in room_blocks_by_room_date.get((room_id, item['date_obj']), []):
                    if item['start'] < b_end and item['end'] > b_start:
                        blocked = True
                        break
                if blocked:
                    continue
            required_booking_keys.add(
                _build_booking_event_key(
                    item['song_id'],
                    item['date'],
                    item['start'],
                    item['duration'],
                    item['room_id'],
                )
            )

        missing_booking_keys = sorted(required_booking_keys - booking_completed_keys)
        if missing_booking_keys:
            return JsonResponse({
                'status': 'error',
                'message': '아직 예약이 필요한 타일이 남아 있습니다.',
                'remaining_count': len(missing_booking_keys),
            }, status=409)

    song_ids = {str(e.get('song_id')) for e in raw_events if e.get('song_id')}
    songs_by_id = {str(s.id): s for s in meeting.songs.filter(id__in=song_ids)}
    rooms_by_id = {str(r.id): r for r in _available_rooms_qs(meeting)}

    normalized = []
    room_slots = defaultdict(lambda: defaultdict(set))  # {(date): {room_id: {slot...}}}
    date_min = meeting.practice_start_date
    date_max = meeting.practice_end_date
    temp_room_cache = {}

    for idx, ev in enumerate(raw_events):
        sid = str(ev.get('song_id') or '')
        if sid not in songs_by_id:
            return JsonResponse({'status': 'error', 'message': f'유효하지 않은 song_id (index={idx}).'}, status=400)

        date_str = str(ev.get('date') or '')
        try:
            d = datetime.date.fromisoformat(date_str)
        except ValueError:
            return JsonResponse({'status': 'error', 'message': f'유효하지 않은 date (index={idx}).'}, status=400)

        if date_min and date_max and (d < date_min or d > date_max):
            return JsonResponse({'status': 'error', 'message': f'합주 기간 밖의 date (index={idx}).'}, status=400)

        try:
            start = int(ev.get('start'))
            duration = int(ev.get('duration'))
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': f'유효하지 않은 start/duration (index={idx}).'}, status=400)

        if duration < 1:
            return JsonResponse({'status': 'error', 'message': f'유효하지 않은 duration (index={idx}).'}, status=400)
        end = start + duration
        if start < 18 or end > 48:
            return JsonResponse({'status': 'error', 'message': f'허용 범위를 벗어난 시간 (index={idx}).'}, status=400)

        room_id_raw = str(ev.get('room_id') or '')
        room_name_raw = str(ev.get('room_name') or '').strip() or '임시합주실'
        room_location_raw = str(ev.get('room_location') or '').strip()
        temp_confirmed_raw = ev.get('temp_room_confirmed', False)
        if isinstance(temp_confirmed_raw, str):
            temp_room_confirmed = temp_confirmed_raw.strip().lower() in ['1', 'true', 'yes', 'y', 'on']
        else:
            temp_room_confirmed = bool(temp_confirmed_raw)
        has_named_temp_identity = ((room_name_raw and room_name_raw != '임시합주실') or bool(room_location_raw))
        if room_id_raw.startswith('temp-') and not (temp_room_confirmed or has_named_temp_identity):
            return JsonResponse({
                'status': 'error',
                'message': '임시합주실 이름/위치를 먼저 입력한 뒤 저장해주세요.',
            }, status=409)

        if room_id_raw and (not room_id_raw.startswith('temp-')) and (room_id_raw in rooms_by_id):
            room_obj = rooms_by_id[room_id_raw]
        else:
            # 임시합주실은 room_id 단위로 분리 보존한다.
            # (표시 텍스트는 동일해도 서로 다른 temp room_id는 별도 공간으로 저장)
            room_identity = room_id_raw or f"{room_name_raw}|{room_location_raw}"
            cache_key = f"meeting:{meeting.id}:temp:{room_identity}"
            room_obj = temp_room_cache.get(cache_key)
            if room_obj is None:
                if not can_create_room:
                    return JsonResponse({
                        'status': 'error',
                        'message': '합주실 생성은 밴드 매니저만 가능합니다.',
                    }, status=403)
                if room_id_raw.startswith('temp-'):
                    # temp room_id는 프론트의 가상 합주실 식별자이므로 동일 요청 내에서만 재사용.
                    # DB에서는 항상 새 임시 합주실 row를 생성해 room 단위 분리를 보장한다.
                    room_obj = PracticeRoom.objects.create(
                        band=meeting.band,
                        name=room_name_raw,
                        location=room_location_raw,
                        capacity=10,
                        is_temporary=True,
                    )
                else:
                    room_obj, _ = PracticeRoom.objects.get_or_create(
                        band=meeting.band,
                        name=room_name_raw,
                        location=room_location_raw,
                        defaults={'capacity': 10, 'is_temporary': True}
                    )
                    if not room_obj.is_temporary:
                        room_obj.is_temporary = True
                        room_obj.save(update_fields=['is_temporary'])
                    if room_name_raw and room_obj.name != room_name_raw:
                        room_obj.name = room_name_raw
                        room_obj.save(update_fields=['name'])
                    if room_obj.location != room_location_raw:
                        room_obj.location = room_location_raw
                        room_obj.save(update_fields=['location'])
                temp_room_cache[cache_key] = room_obj

        d_key = d.strftime('%Y-%m-%d')
        rid = str(room_obj.id)
        used = room_slots[d_key][rid]
        for slot in range(start, end):
            if slot in used:
                return JsonResponse({'status': 'error', 'message': f'같은 방 시간 충돌 (index={idx}).'}, status=400)
            used.add(slot)

        normalized.append({
            'song': songs_by_id[sid],
            'date': d,
            'start': start,
            'end': end,
            'room': room_obj,
            'is_forced': bool(ev.get('is_forced', False)),
        })

    # 저장 직전 서버측 최종 검증(보수 모드)
    # - 외부 미팅 합주실 점유(RoomBlock/PracticeSchedule) 충돌 차단
    # - 멤버 시간 중복(같은 밴드의 날짜 겹침 미팅 기준) 차단
    is_valid, conflict_message = _validate_normalized_events_against_external_conflicts(
        meeting,
        normalized,
    )
    if not is_valid:
        return JsonResponse({
            'status': 'error',
            'message': conflict_message or '외부 일정과 충돌합니다.',
        }, status=409)

    with transaction.atomic():
        PracticeSchedule.objects.filter(meeting=meeting).delete()
        rows = [
            PracticeSchedule(
                meeting=meeting,
                song=item['song'],
                room=item['room'],
                date=item['date'],
                start_index=item['start'],
                end_index=item['end'],
                is_forced=item['is_forced'],
            )
            for item in normalized
        ]
        if rows:
            PracticeSchedule.objects.bulk_create(rows)
        utils.sync_generated_oneoff_for_meeting(meeting)
        MeetingFinalDraft.objects.filter(meeting=meeting).delete()
        update_fields = []
        if meeting.is_booking_in_progress:
            meeting.is_booking_in_progress = False
            update_fields.append('is_booking_in_progress')
        if meeting.is_final_schedule_released:
            meeting.is_final_schedule_released = False
            update_fields.append('is_final_schedule_released')
        if not meeting.is_final_schedule_confirmed:
            meeting.is_final_schedule_confirmed = True
            update_fields.append('is_final_schedule_confirmed')
        if update_fields:
            meeting.save(update_fields=update_fields)
        _sync_room_blocks_for_confirmed_schedule(meeting)

    return JsonResponse({
        'status': 'success',
        'saved_count': len(normalized),
        'redirect_url': reverse('schedule_final', args=[meeting.id]),
    })


@login_required
def schedule_final_reset(request, meeting_id):
    """
    [AJAX] 최종 확정된 합주 일정을 초기화.
    - PracticeSchedule 삭제
    - generated OneOffBlock 삭제(sync 함수 통해 반영)
    - 확인 제출 현황 초기화
    - 최종 확정/공개 플래그 해제
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    with transaction.atomic():
        PracticeSchedule.objects.filter(meeting=meeting).delete()
        MeetingFinalDraft.objects.filter(meeting=meeting).delete()
        MeetingScheduleConfirmation.objects.filter(meeting=meeting).delete()
        _clear_room_blocks_for_confirmed_schedule(meeting)
        utils.sync_generated_oneoff_for_meeting(meeting)

        update_fields = []
        if meeting.is_final_schedule_confirmed:
            meeting.is_final_schedule_confirmed = False
            update_fields.append('is_final_schedule_confirmed')
        if meeting.is_final_schedule_released:
            meeting.is_final_schedule_released = False
            update_fields.append('is_final_schedule_released')
        if meeting.is_booking_in_progress:
            meeting.is_booking_in_progress = False
            update_fields.append('is_booking_in_progress')
        if meeting.is_schedule_coordinating:
            meeting.is_schedule_coordinating = False
            update_fields.append('is_schedule_coordinating')
        if update_fields:
            meeting.save(update_fields=update_fields)

    return JsonResponse({
        'status': 'success',
        'redirect_url': reverse('meeting_detail', kwargs={'pk': meeting.id}),
    })


@login_required
def schedule_final_acknowledge(request, meeting_id):
    """
    일반 멤버가 현재 버전의 최종 합주 일정을 인지했음을 제출.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    membership = _get_approved_membership(meeting, request.user)
    if not membership:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    if _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '관리자는 확인 제출 대상이 아닙니다.'}, status=400)
    if meeting.is_booking_in_progress:
        return JsonResponse({'status': 'error', 'message': '현재 일정은 예약 반영 중입니다. 공유본에서 다시 확인해주세요.'}, status=409)
    if not (meeting.is_final_schedule_released or meeting.is_final_schedule_confirmed):
        return JsonResponse({'status': 'error', 'message': '아직 최종 합주 일정이 공개되지 않았습니다.'}, status=409)

    participant_ids = set(
        meeting.songs.filter(sessions__assignee__isnull=False)
        .values_list('sessions__assignee_id', flat=True)
        .distinct()
    )
    if request.user.id not in participant_ids:
        return JsonResponse({'status': 'error', 'message': '이번 합주 일정에 참여한 곡이 없습니다.'}, status=400)

    _, created = MeetingScheduleConfirmation.objects.get_or_create(
        meeting=meeting,
        user=request.user,
        version=meeting.schedule_version,
    )
    if not created:
        return JsonResponse({'status': 'already', 'message': '이미 일정 확정을 제출했습니다.'})
    return JsonResponse({'status': 'success'})


@login_required
def schedule_move_event(request, meeting_id):
    """
    [AJAX] 결과 시간표에서 곡 카드 드래그 이동 저장
    - 기본: 가용 시간 내 이동만 허용
    - 불가능 시간이 포함되면 conflict 응답으로 강제 배치 재확인
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    if _is_final_locked(meeting):
        return JsonResponse({'status': 'error', 'message': _final_lock_message(meeting, '배치를 이동할 수 없습니다.')}, status=409)
    membership = _get_approved_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '잘못된 요청 형식입니다.'}, status=400)

    song_id = data.get('song_id')
    target_date_str = data.get('target_date')
    target_start = data.get('target_start')
    duration = data.get('duration')
    force_assign = bool(data.get('force', False))

    if not all([song_id, target_date_str]) or target_start is None or duration is None:
        return JsonResponse({'status': 'error', 'message': '필수 값이 누락되었습니다.'}, status=400)

    song = get_object_or_404(Song, id=song_id, meeting=meeting)

    try:
        target_date = datetime.date.fromisoformat(target_date_str)
        target_start = int(target_start)
        duration = int(duration)
    except (ValueError, TypeError):
        return JsonResponse({'status': 'error', 'message': '날짜/시간 값이 유효하지 않습니다.'}, status=400)

    if duration < 1:
        return JsonResponse({'status': 'error', 'message': '유효하지 않은 duration 입니다.'}, status=400)

    target_end = target_start + duration
    if target_start < 18 or target_end > 48:
        return JsonResponse({'status': 'error', 'message': '허용 범위(09:00~24:00)를 벗어났습니다.'}, status=400)

    source_date = None
    source_start = None
    source_room_id = None
    if data.get('source_date'):
        try:
            source_date = datetime.date.fromisoformat(str(data.get('source_date')))
        except ValueError:
            source_date = None
    if data.get('source_start') is not None:
        try:
            source_start = int(data.get('source_start'))
        except (ValueError, TypeError):
            source_start = None
    if data.get('source_room_id'):
        source_room_id = str(data.get('source_room_id'))

    # 세션 배정 멤버의 가용성 검사
    assigned_user_info = {}
    for sess in song.sessions.select_related('assignee').all():
        if not sess.assignee_id:
            continue
        if sess.assignee_id not in assigned_user_info:
            assigned_user_info[sess.assignee_id] = {
                'user': sess.assignee,
                'session': _session_abbr(sess.name),
            }
    assigned_users = [v['user'] for v in assigned_user_info.values()]
    assigned_member_count = len(assigned_users)

    unavailable_reasons = set()
    if assigned_users:
        unavailable_reason_map = _build_user_unavailable_reason_map(
            [u.id for u in assigned_users],
            target_date,
            target_date,
        )
        avail_map = {}
        for av in MemberAvailability.objects.filter(user__in=assigned_users, date=target_date):
            avail_map[av.user_id] = set(av.available_slot or [])

        for u in assigned_users:
            slots = avail_map.get(u.id, set())
            conflict_slots = []
            reason_set = set()
            for slot in range(target_start, target_end):
                slot_reasons = unavailable_reason_map.get(u.id, {}).get(target_date.strftime('%Y-%m-%d'), {}).get(slot, set())
                # "불가능 일정"은 동일하게 취급:
                # - MemberAvailability 상 불가
                # - 사유 맵(개인 일정/합주 포함)에 잡히는 불가
                if (slot not in slots) or bool(slot_reasons):
                    conflict_slots.append(slot)
                    reason_set.update(slot_reasons)
            if conflict_slots:
                reason_text = ', '.join(sorted(reason_set)) if reason_set else '사유 없음'
                session_abbr = assigned_user_info.get(u.id, {}).get('session', '')
                session_suffix = f"({session_abbr})" if session_abbr else ''
                display_name = str((u.realname or '').strip() or u.username)
                unavailable_reasons.add(f"{display_name}{session_suffix} - {reason_text}")

    if unavailable_reasons and not force_assign:
        logger.warning(
            "schedule_move_event conflict availability_conflict meeting=%s song=%s date=%s start=%s end=%s room=%s reasons=%s",
            meeting.id, song.id, target_date, target_start, target_end, str(data.get('target_room_id') or ''), sorted(unavailable_reasons),
        )
        return JsonResponse({
            'status': 'conflict',
            'kind': 'availability_conflict',
            'message': '합주가 불가능한 칸에 배치하였습니다.',
            'reasons': sorted(unavailable_reasons)
        }, status=409)

    # 기존 확정 스케줄과 멤버 겹침 검사 (강제 배치 불가)
    # - 현재 미팅뿐 아니라 같은 밴드의 다른 미팅까지 포함해 중복을 차단한다.
    assigned_user_ids = {u.id for u in assigned_users}
    if assigned_user_ids:
        overlapping_meeting_ids = _get_overlapping_band_meeting_ids(
            meeting,
            target_date,
            target_date,
            exclude_self=False,
        )
        overlap_qs = PracticeSchedule.objects.filter(
            meeting_id__in=overlapping_meeting_ids,
            date=target_date,
            start_index__lt=target_end,
            end_index__gt=target_start,
        )
        if source_date is not None and source_start is not None and source_room_id and (not str(source_room_id).startswith('temp-')):
            # 현재 미팅에서 이동 중인 "원본 카드"만 제외한다.
            # 같은 밴드의 타 미팅에서 동일 시각/동일 방인 스케줄은 제외하면 안 된다.
            overlap_qs = overlap_qs.exclude(
                meeting=meeting,
                song=song,
                date=source_date,
                start_index=source_start,
                room_id=source_room_id,
            )

        overlapping_song_ids = list(overlap_qs.values_list('song_id', flat=True).distinct())
        song_assignees_map = defaultdict(set)
        if overlapping_song_ids:
            for sid, uid in Session.objects.filter(
                song_id__in=overlapping_song_ids,
                assignee__isnull=False,
            ).values_list('song_id', 'assignee_id'):
                song_assignees_map[sid].add(uid)

        display_name_map = {
            uid: (str((realname or '').strip() or username))
            for uid, realname, username in User.objects.filter(id__in=assigned_user_ids).values_list('id', 'realname', 'username')
        }
        conflicting_names = set()
        for sch in overlap_qs.only('song_id'):
            sch_user_ids = song_assignees_map.get(sch.song_id, set())
            if assigned_user_ids.isdisjoint(sch_user_ids):
                continue
            shared_ids = assigned_user_ids & sch_user_ids
            for uid in shared_ids:
                display_name = display_name_map.get(uid)
                if display_name:
                    conflicting_names.add(display_name)

        if conflicting_names and not force_assign:
            logger.warning(
                "schedule_move_event conflict member_overlap meeting=%s song=%s date=%s start=%s end=%s room=%s reasons=%s",
                meeting.id, song.id, target_date, target_start, target_end, str(data.get('target_room_id') or ''), sorted(conflicting_names),
            )
            return JsonResponse({
                'status': 'conflict',
                'kind': 'member_overlap',
                'message': '한 사람이 동시에 여러 합주는 물리적으로 불가능한데 그래도 할거임?',
                'reasons': sorted(conflicting_names),
            }, status=409)

    # 합주실 정원 초과는 '강제 배치'로만 반영 (배치는 허용)
    capacity_forced = False
    target_room_id = str(data.get('target_room_id') or '')
    if target_room_id and (not target_room_id.startswith('temp-')):
        room_block_qs = RoomBlock.objects.filter(
            room_id=target_room_id,
            date=target_date,
            start_index__lt=target_end,
            end_index__gt=target_start,
        ).exclude(source_meeting=meeting)
        room_blocked = room_block_qs.exists()
        if room_blocked and not force_assign:
            reason_lines = []
            source_meeting_ids = list(
                room_block_qs.exclude(source_meeting__isnull=True)
                .values_list('source_meeting_id', flat=True)
                .distinct()
            )
            if source_meeting_ids:
                source_rows = PracticeSchedule.objects.filter(
                    meeting_id__in=source_meeting_ids,
                    room_id=target_room_id,
                    date=target_date,
                    start_index__lt=target_end,
                    end_index__gt=target_start,
                ).select_related('meeting', 'song')
                reason_lines = sorted({
                    f"[{sch.meeting.title}] - {sch.song.title}"
                    for sch in source_rows
                })
            if not reason_lines and room_block_qs.filter(source_meeting__isnull=True).exists():
                reason_lines = ['사용자 지정 사용 불가 시간']
            logger.warning(
                "schedule_move_event conflict room_blocked meeting=%s song=%s date=%s start=%s end=%s room=%s reasons=%s",
                meeting.id, song.id, target_date, target_start, target_end, target_room_id, reason_lines,
            )
            return JsonResponse({
                'status': 'conflict',
                'kind': 'room_blocked',
                'message': '선택한 합주실은 해당 시간에 이용 불가입니다.',
                'reasons': reason_lines,
            }, status=409)
    if target_room_id and (not target_room_id.startswith('temp-')) and assigned_member_count > 0:
        room_obj = _available_rooms_qs(meeting).filter(id=target_room_id).only('capacity').first()
        if room_obj and assigned_member_count > int(room_obj.capacity or 0):
            capacity_forced = True

    # 여기서는 임시 배치 검증만 수행하고 DB에는 저장하지 않습니다.
    # 실제 저장은 "확정하기" 단계에서만 처리하도록 분리합니다.
    return JsonResponse({
        'status': 'success',
        'target_date': target_date.strftime('%Y-%m-%d'),
        'target_start': target_start,
        'target_end': target_end,
        'forced': (force_assign or capacity_forced),
    })
