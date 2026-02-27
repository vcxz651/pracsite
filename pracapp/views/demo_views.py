import datetime
import csv
import random
import uuid
import re
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import (
    Band,
    Meeting,
    MeetingFinalDraft,
    MeetingParticipant,
    MeetingScheduleConfirmation,
    MeetingWorkDraft,
    Membership,
    PracticeRoom,
    RoomBlock,
    PracticeSchedule,
    Session,
    Song,
)
from create_dummy import (
    _create_weekly_schedule_for_user,
    _apply_weekly_club_activity_rules,
    _apply_weekly_random_oneoff_rules,
    _sync_member_availability_from_blocks,
)

User = get_user_model()


DEMO_SESSION_KEYS = [
    'demo_mode',
    'demo_role',
    'demo_scenario',
    'demo_band_id',
    'demo_meeting_id',
    'demo_user_manager_id',
    'demo_user_member_id',
    'demo_user_ids',
    'demo_cache_scope',
]


DEMO_MEMBER_NAMES = [
    '김경석', '이태준', '박한섭', '최윤성', '정원탁', '조덕삼', '강희수', '윤봉식', '임철민', '한동우',
    '송재익', '오정식', '서진태', '신문수', '권태호', '유영필', '황치영', '안명보', '고기찬', '양덕수',
    '김옥순', '이정선', '박영숙', '최춘희', '정해숙', '조경애', '강금자', '윤혜순', '임복희', '한명옥',
    '송정자', '오말순', '서화자', '신덕예', '권보배', '유순남', '황점숙', '안인자', '고숙자', '양길순',
]

DEMO_TEMPLATE_CSV_PRIMARY = Path(__file__).resolve().parents[2] / 'demo_songs_rock_80.csv'
DEMO_TEMPLATE_CSV_FALLBACK = Path(__file__).resolve().parents[2] / '김민기_밴드음악_명곡선_선곡템플릿.csv'

SCENARIO_CONFIG = {
    1: {'label': 'A', 'member_count': 40, 'total_songs': 80, 'assigned_songs': 25},
    2: {'label': 'B', 'member_count': 6, 'total_songs': 20, 'assigned_songs': 4},
    3: {'label': 'C', 'member_count': 40, 'total_songs': 80, 'assigned_songs': 25},
}

SCENARIO_DATE_MESSAGES = {
    1: '지금은 4월 3일입니다. 밴드의 선곡회의가 막 끝난 시점입니다.',
    2: '지금은 4월 3일입니다. 오늘 우리 팀의 선곡회의가 있습니다.',
    3: '지금은 5월 18일입니다. 합주가 이미 시작된 시점입니다.',
}


def _normalize_cache_scope(raw_scope):
    scope = re.sub(r'[^a-zA-Z0-9_-]+', '', str(raw_scope or '').strip())
    scope = scope[:24]
    return scope or 'global'


def _scenario_cache_prefix(scenario, cache_scope):
    scope = _normalize_cache_scope(cache_scope)
    return f"demo_cache_s{int(scenario)}_{scope}_"


def _scenario_cache_band_name(scenario, cache_scope):
    scope = _normalize_cache_scope(cache_scope)
    return f"[데모CACHE][S{int(scenario)}][{scope}] 락스타즈"


def _ensure_demo_cache_scope(request):
    existing = request.session.get('demo_cache_scope')
    if existing:
        normalized = _normalize_cache_scope(existing)
        if normalized != existing:
            request.session['demo_cache_scope'] = normalized
        return normalized

    if not request.session.session_key:
        request.session.save()
    base = str(request.session.session_key or uuid.uuid4().hex)
    scope = _normalize_cache_scope(base[:12])
    request.session['demo_cache_scope'] = scope
    return scope


def _clear_demo_session(request):
    for key in DEMO_SESSION_KEYS:
        request.session.pop(key, None)


def _cleanup_demo_assets_from_session(request):
    band_id = request.session.get('demo_band_id')
    raw_user_ids = request.session.get('demo_user_ids') or []
    user_ids = [uid for uid in raw_user_ids if uid]
    if not user_ids:
        manager_id = request.session.get('demo_user_manager_id')
        member_id = request.session.get('demo_user_member_id')
        user_ids = [uid for uid in [manager_id, member_id] if uid]
    if band_id:
        Band.objects.filter(id=band_id, name__startswith='[데모').delete()
    if user_ids:
        User.objects.filter(id__in=user_ids, username__startswith='demo_cache_').delete()
        User.objects.filter(id__in=user_ids, username__startswith='demo_member_').delete()
    _clear_demo_session(request)


def _build_match_params(rooms):
    room_ids = [str(r.id) for r in rooms]
    room_csv = ",".join(room_ids)
    return {
        'd': '60',
        'c': '1',
        'p': 'member_overlap,late_slots,fair_share,consecutive_days,room_priority,today_priority',
        'r': room_csv,
        'rp': room_csv,
        'w': '0',
        're': '1',
        'h': '0',
        'ts': '18',
        'te': '48',
    }


def _last_weekday_of_month(year, month, weekday):
    if month == 12:
        first_next = datetime.date(year + 1, 1, 1)
    else:
        first_next = datetime.date(year, month + 1, 1)
    d = first_next - datetime.timedelta(days=1)
    while d.weekday() != weekday:
        d -= datetime.timedelta(days=1)
    return d


def _first_weekday_of_month(year, month, weekday):
    d = datetime.date(year, month, 1)
    while d.weekday() != weekday:
        d += datetime.timedelta(days=1)
    return d


def _resolve_demo_practice_range():
    year = timezone.localdate().year
    start_date = _last_weekday_of_month(year, 4, 0)  # 4월 마지막 월요일
    end_date = _first_weekday_of_month(year, 6, 4)   # 6월 첫째 주 금요일
    return start_date, end_date


def _load_demo_song_template_rows(limit=None):
    template_csv = DEMO_TEMPLATE_CSV_PRIMARY if DEMO_TEMPLATE_CSV_PRIMARY.exists() else DEMO_TEMPLATE_CSV_FALLBACK
    if not template_csv.exists():
        raise FileNotFoundError(f"데모 템플릿 CSV를 찾을 수 없습니다: {template_csv}")
    rows = []
    with template_csv.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            if limit is not None and len(rows) >= int(limit):
                break
    if not rows:
        raise ValueError('데모 템플릿 CSV가 비어 있습니다.')
    return rows


def _build_booking_event_key(song_id, date_str, start, duration, room_id):
    return f"{str(song_id or '')}|{str(date_str or '')}|{int(start)}|{int(duration)}|{str(room_id or '')}"


def _serialize_event(song, date_obj, start_idx, duration, room_id, room_name, room_location, is_forced=False, temp_room_confirmed=False):
    payload = {
        'song_id': str(song.id),
        'date': date_obj.strftime('%Y-%m-%d'),
        'start': int(start_idx),
        'duration': int(duration),
        'room_id': str(room_id),
        'room_name': str(room_name or ''),
        'room_location': str(room_location or ''),
        'is_forced': bool(is_forced),
    }
    if str(room_id).startswith('temp-'):
        payload['temp_room_confirmed'] = bool(temp_room_confirmed)
    return payload


def _pick_session_applicants(sess_name, instrument_users, fallback_users, count=1):
    if sess_name.startswith('Vocal'):
        pool = instrument_users.get('Vocal') or []
    elif sess_name.startswith('Guitar'):
        pool = instrument_users.get('Guitar') or []
    elif sess_name.startswith('Bass'):
        pool = instrument_users.get('Bass') or []
    elif sess_name.startswith('Drum'):
        pool = instrument_users.get('Drum') or []
    elif sess_name.startswith('Keyboard'):
        pool = instrument_users.get('Keyboard') or []
    else:
        pool = list(fallback_users or [])
    if not pool:
        pool = list(fallback_users or [])
    if not pool:
        return []
    k = max(1, min(int(count), len(pool)))
    return random.sample(pool, k=k)


def _collect_band_users(band):
    return list(User.objects.filter(user_memberships__band=band).distinct().order_by('date_joined', 'username'))


def _backfill_assignee_to_applicant(meeting):
    through = Session.applicant.through
    pending = []
    sessions = Session.objects.filter(song__meeting=meeting, assignee__isnull=False).prefetch_related('applicant')
    for sess in sessions:
        assignee_id = str(sess.assignee_id or '')
        if not assignee_id:
            continue
        applicant_ids = {str(u.id) for u in sess.applicant.all()}
        if assignee_id in applicant_ids:
            continue
        pending.append(through(session_id=sess.id, user_id=sess.assignee_id))
    if pending:
        through.objects.bulk_create(pending, ignore_conflicts=True)


def _ensure_cached_demo_dataset(scenario, cache_scope):
    scenario = int(scenario)
    cfg = SCENARIO_CONFIG.get(scenario, SCENARIO_CONFIG[1])
    cache_prefix = _scenario_cache_prefix(scenario, cache_scope)
    cache_band_name = _scenario_cache_band_name(scenario, cache_scope)

    band = Band.objects.filter(name=cache_band_name).first()
    if band:
        meeting = band.meetings.order_by('created_at').first()
        users = _collect_band_users(band)
        manager_user = next((u for u in users if band.memberships.filter(user=u, role='LEADER').exists()), None)
        member_user = next((u for u in users if u != manager_user), None)
        if meeting and manager_user and member_user:
            _backfill_assignee_to_applicant(meeting)
            rooms = list(band.rooms.filter(is_temporary=False).order_by('name'))
            songs = list(meeting.songs.order_by('created_at', 'title', 'id'))
            return band, meeting, rooms, songs, users, manager_user, member_user

    Band.objects.filter(name=cache_band_name).delete()
    User.objects.filter(username__startswith=cache_prefix).delete()

    manager_user = User.objects.create_user(
        username=f"{cache_prefix}manager",
        password=uuid.uuid4().hex,
        realname='데모 캐시 매니저',
        instrument='Guitar',
    )
    member_user = User.objects.create_user(
        username=f"{cache_prefix}member",
        password=uuid.uuid4().hex,
        realname='데모 캐시 멤버',
        instrument='Vocal',
    )
    band, meeting, rooms, songs, demo_users = _seed_demo_meeting_data(
        manager_user=manager_user,
        member_user=member_user,
        member_count=cfg['member_count'],
        total_songs=cfg['total_songs'],
        assigned_songs=cfg['assigned_songs'],
    )
    band.name = cache_band_name
    band.save(update_fields=['name'])
    meeting.title = f"[데모CACHE] 시나리오 {cfg['label']}"
    meeting.save(update_fields=['title'])
    _backfill_assignee_to_applicant(meeting)
    return band, meeting, rooms, songs, demo_users, manager_user, member_user


def _seed_demo_meeting_data(manager_user, member_user, member_count=40, total_songs=80, assigned_songs=25):
    random.seed(20260225)
    suffix = uuid.uuid4().hex[:8]
    band = Band.objects.create(
        name=f"[데모DB] 락스타즈-{suffix}",
        school='Demo School',
        department='ETC',
        department_detail='데모 전용',
        introduce='데모 전용 밴드',
        description='데모 전용 데이터',
        is_public=False,
    )

    demo_users = [manager_user, member_user]
    instrument_cycle = ['Vocal', 'Guitar', 'Bass', 'Drum', 'Keyboard']
    extra_count = max(0, int(member_count) - 2)
    for idx in range(extra_count):
        name = DEMO_MEMBER_NAMES[idx % len(DEMO_MEMBER_NAMES)]
        u = User.objects.create_user(
            username=f"demo_member_{suffix}_{idx+1:02d}",
            password=uuid.uuid4().hex,
            realname=name,
            instrument=instrument_cycle[idx % len(instrument_cycle)],
        )
        demo_users.append(u)

    now = timezone.now()
    for u in demo_users:
        role = 'MEMBER'
        if u.id == manager_user.id:
            role = 'LEADER'
        Membership.objects.create(
            user=u,
            band=band,
            is_approved=True,
            role=role,
            date_joined=now,
        )

    practice_start_date, practice_end_date = _resolve_demo_practice_range()
    meeting = Meeting.objects.create(
        band=band,
        title='[데모] 합주 일정 시뮬레이션',
        description='데모 시나리오용 선곡회의',
        practice_start_date=practice_start_date,
        practice_end_date=practice_end_date,
    )

    rooms = [
        PracticeRoom.objects.create(band=band, name='A룸', location='3F', capacity=6, is_temporary=False),
        PracticeRoom.objects.create(band=band, name='B룸', location='3F', capacity=5, is_temporary=False),
    ]

    for u in demo_users:
        p_role = MeetingParticipant.ROLE_MANAGER if u.id == manager_user.id else MeetingParticipant.ROLE_MEMBER
        MeetingParticipant.objects.create(
            meeting=meeting,
            user=u,
            status=MeetingParticipant.STATUS_APPROVED,
            role=p_role,
            approved_at=now,
            approved_by=manager_user,
        )

    instrument_users = {
        'Vocal': [],
        'Guitar': [],
        'Bass': [],
        'Drum': [],
        'Keyboard': [],
    }
    for u in demo_users:
        inst = str(getattr(u, 'instrument', '') or '')
        if inst in instrument_users:
            instrument_users[inst].append(u)
    for key in instrument_users:
        if not instrument_users[key]:
            instrument_users[key] = [manager_user]

    # 더미데이터 규칙: 멤버 일정(수업/알바/oneoff) -> 가용 슬롯 동기화
    for user in demo_users:
        _create_weekly_schedule_for_user(user, practice_start_date, practice_end_date)
    _apply_weekly_club_activity_rules(demo_users, practice_start_date, practice_end_date)
    _apply_weekly_random_oneoff_rules(demo_users, practice_start_date, practice_end_date)
    for user in demo_users:
        _sync_member_availability_from_blocks(user, practice_start_date, practice_end_date)

    songs = []
    template_rows = _load_demo_song_template_rows(limit=max(1, int(total_songs)))
    for song_idx, row in enumerate(template_rows):
        title = str(row.get('title') or '').strip()
        artist = str(row.get('artist') or '').strip()
        needed = [s.strip() for s in str(row.get('needed_session') or '').split(',') if s.strip()]
        extras = [s.strip() for s in str(row.get('extra_session') or '').split(',') if s.strip()]

        if not title:
            continue
        song = Song.objects.create(
            meeting=meeting,
            author=manager_user,
            title=title,
            artist=artist or '-',
            url=str(row.get('url') or '').strip(),
            author_note=str(row.get('author_note') or '').strip(),
        )
        songs.append(song)
        should_assign = song_idx < int(assigned_songs)
        for sess_name in needed:
            sess = Session.objects.create(song=song, name=sess_name, is_extra=False)
            if should_assign:
                if sess_name.startswith('Vocal'):
                    assignee = random.choice(instrument_users['Vocal'])
                elif sess_name.startswith('Guitar'):
                    assignee = random.choice(instrument_users['Guitar'])
                elif sess_name.startswith('Bass'):
                    assignee = random.choice(instrument_users['Bass'])
                elif sess_name.startswith('Drum'):
                    assignee = random.choice(instrument_users['Drum'])
                elif sess_name.startswith('Keyboard'):
                    assignee = random.choice(instrument_users['Keyboard'])
                else:
                    assignee = manager_user
                sess.assignee = assignee
                sess.save(update_fields=['assignee'])
                sess.applicant.add(assignee)
            else:
                # 미배정 곡도 "지원이 어느 정도 있는 상태"로 만들어 선곡시트 현실감을 높인다.
                if random.random() < 0.72:
                    applicants = _pick_session_applicants(
                        sess_name=sess_name,
                        instrument_users=instrument_users,
                        fallback_users=demo_users,
                        count=(2 if random.random() < 0.22 else 1),
                    )
                    if applicants:
                        sess.applicant.add(*applicants)
        for sess_name in extras:
            Session.objects.create(song=song, name=sess_name, is_extra=True)

    return band, meeting, rooms, songs, demo_users


def _build_events_for_songs(songs, rooms, start_date, max_events=None):
    events = []
    duration_cycle = [2, 3, 2, 2, 3]
    start_cycle = [34, 36, 38, 40, 42]
    room_count = max(1, len(rooms))
    for idx, song in enumerate(songs):
        if max_events is not None and idx >= int(max_events):
            break
        week = idx // 10
        day_offset = idx % 5
        day = start_date + datetime.timedelta(days=(week * 7) + day_offset)
        start = start_cycle[(idx // room_count) % len(start_cycle)]
        duration = duration_cycle[idx % len(duration_cycle)]
        room = rooms[idx % room_count]
        events.append(_serialize_event(
            song=song,
            date_obj=day,
            start_idx=start,
            duration=duration,
            room_id=room.id,
            room_name=room.name,
            room_location=room.location,
            is_forced=False,
        ))
    return events


def _inject_scenario_b_roomblocks(band, rooms, start_date):
    Meeting.objects.filter(band=band, title__startswith='[데모B]').delete()
    team_specs = [
        ('팀 B', [('A', 0, 36, 42), ('B', 1, 38, 44)]),
        ('팀 C', [('A', 1, 34, 40), ('B', 0, 34, 39)]),
        ('팀 D', [('A', 2, 38, 44), ('B', 2, 34, 40)]),
        ('팀 E', [('B', 3, 36, 42), ('A', 3, 40, 44)]),
        ('팀 F', [('A', 4, 34, 42), ('B', 4, 38, 44)]),
    ]
    room_by_name = {r.name: r for r in rooms}
    for team_name, blocks in team_specs:
        ghost = Meeting.objects.create(
            band=band,
            title=f'[데모B] {team_name} 예약',
            description='데모 시나리오 B 유령 미팅',
            practice_start_date=start_date,
            practice_end_date=start_date + datetime.timedelta(days=60),
            is_schedule_coordinating=False,
            is_final_schedule_confirmed=True,
        )
        for room_short, day_offset, start_idx, end_idx in blocks:
            room_name = f'{room_short}룸'
            room = room_by_name.get(room_name)
            if not room:
                continue
            RoomBlock.objects.create(
                room=room,
                date=start_date + datetime.timedelta(days=day_offset),
                start_index=start_idx,
                end_index=end_idx,
                source_meeting=ghost,
            )


def _apply_scenario_state(meeting, manager_user, rooms, songs, scenario, assigned_songs):
    PracticeSchedule.objects.filter(meeting=meeting).delete()
    MeetingFinalDraft.objects.filter(meeting=meeting).delete()
    MeetingWorkDraft.objects.filter(meeting=meeting).delete()
    MeetingScheduleConfirmation.objects.filter(meeting=meeting).delete()
    RoomBlock.objects.filter(source_meeting__band=meeting.band, source_meeting__title__startswith='[데모B]').delete()
    Meeting.objects.filter(band=meeting.band, title__startswith='[데모B]').delete()

    start_date = meeting.practice_start_date or (datetime.date.today() + datetime.timedelta(days=1))
    match_params = _build_match_params(rooms)
    schedulable_songs = [song for song in songs if song.is_session_full]
    base_events = _build_events_for_songs(schedulable_songs, rooms, start_date, max_events=assigned_songs)
    _backfill_assignee_to_applicant(meeting)

    if scenario == 1:
        meeting.is_schedule_coordinating = True
        meeting.is_final_schedule_released = False
        meeting.is_booking_in_progress = False
        meeting.is_final_schedule_confirmed = False
        meeting.save(update_fields=[
            'is_schedule_coordinating',
            'is_final_schedule_released',
            'is_booking_in_progress',
            'is_final_schedule_confirmed',
        ])
        return

    if scenario == 2:
        _inject_scenario_b_roomblocks(meeting.band, rooms, start_date)
        meeting.is_schedule_coordinating = True
        meeting.is_final_schedule_released = False
        meeting.is_booking_in_progress = False
        meeting.is_final_schedule_confirmed = False
        meeting.save(update_fields=[
            'is_schedule_coordinating',
            'is_final_schedule_released',
            'is_booking_in_progress',
            'is_final_schedule_confirmed',
        ])
        MeetingWorkDraft.objects.update_or_create(
            meeting=meeting,
            user=manager_user,
            defaults={'events': base_events, 'match_params': match_params},
        )
        return

    # scenario 3: final confirmed
    rows = []
    for ev in base_events:
        room = next((r for r in rooms if str(r.id) == str(ev['room_id'])), None)
        song = next((s for s in songs if str(s.id) == str(ev['song_id'])), None)
        if not room or not song:
            continue
        target_date = datetime.date.fromisoformat(str(ev['date']))
        start_idx = int(ev['start'])
        end_idx = start_idx + int(ev['duration'])
        rows.append(PracticeSchedule(
            meeting=meeting,
            song=song,
            room=room,
            date=target_date,
            start_index=start_idx,
            end_index=end_idx,
            is_forced=bool(ev.get('is_forced', False)),
        ))
    if rows:
        PracticeSchedule.objects.bulk_create(rows)

    meeting.is_schedule_coordinating = False
    meeting.is_final_schedule_released = False
    meeting.is_booking_in_progress = False
    meeting.is_final_schedule_confirmed = True
    meeting.save(update_fields=[
        'is_schedule_coordinating',
        'is_final_schedule_released',
        'is_booking_in_progress',
        'is_final_schedule_confirmed',
    ])

    participant_ids = list(
        meeting.participants.filter(status=MeetingParticipant.STATUS_APPROVED).values_list('user_id', flat=True)
    )
    ack_ids = participant_ids[: max(1, min(4, len(participant_ids)))]
    for uid in ack_ids:
        MeetingScheduleConfirmation.objects.get_or_create(
            meeting=meeting,
            user_id=uid,
            version=meeting.schedule_version,
        )


def _redirect_for_scenario(request, meeting, scenario):
    if scenario == 1:
        return redirect('meeting_detail', pk=meeting.id)
    if scenario == 2:
        return redirect('demo_dashboard')
    return redirect('schedule_final', meeting_id=meeting.id)


def demo_home(request):
    return render(request, 'pracapp/demo/demo_home.html')


@login_required
def demo_dashboard(request):
    if not request.session.get('demo_mode'):
        messages.info(request, '먼저 데모를 시작해주세요.')
        return redirect('demo_home')
    scenario = int(request.session.get('demo_scenario') or 1)
    if scenario != 2:
        return redirect('demo_scenario', scenario=scenario)
    meeting_id = request.session.get('demo_meeting_id')
    meeting = get_object_or_404(Meeting, id=meeting_id)
    room_blocks = RoomBlock.objects.filter(
        source_meeting__band=meeting.band,
        source_meeting__title__startswith='[데모B]',
    ).select_related('room', 'source_meeting').order_by('date', 'start_index')

    team_map = {}
    for rb in room_blocks:
        title = str(getattr(rb.source_meeting, 'title', '') or '')
        team_name = title.replace('[데모B] ', '').replace(' 예약', '').strip() or '팀'
        team_map.setdefault(team_name, []).append(rb)

    team_rows = [{
        'name': '팀 A (우리 팀)',
        'status': '선곡회의 진행 중',
        'details': '아직 합주 예약 전',
        'is_done': False,
    }]
    for team_name in ['팀 B', '팀 C', '팀 D', '팀 E', '팀 F']:
        blocks = team_map.get(team_name, [])
        details = []
        for block in blocks:
            start_hour = int(block.start_index // 2)
            start_min = '30' if int(block.start_index % 2) else '00'
            end_hour = int(block.end_index // 2)
            end_min = '30' if int(block.end_index % 2) else '00'
            details.append(f"{block.date.strftime('%m/%d')} {block.room.name} {start_hour}:{start_min}-{end_hour}:{end_min}")
        team_rows.append({
            'name': team_name,
            'status': '합주 예약 완료',
            'details': ', '.join(details) if details else '-',
            'is_done': True,
        })
    return render(request, 'pracapp/demo/demo_dashboard.html', {
        'meeting': meeting,
        'team_rows': team_rows,
        'scenario_date_message': SCENARIO_DATE_MESSAGES.get(2, ''),
    })


@transaction.atomic
def demo_start(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    scenario = int(request.POST.get('scenario') or 1)
    if scenario not in (1, 2, 3):
        scenario = 1

    if request.session.get('demo_mode'):
        _cleanup_demo_assets_from_session(request)

    cfg = SCENARIO_CONFIG.get(scenario, SCENARIO_CONFIG[1])
    cache_scope = _ensure_demo_cache_scope(request)
    band, meeting, rooms, songs, demo_users, manager_user, member_user = _ensure_cached_demo_dataset(
        scenario,
        cache_scope=cache_scope,
    )
    _apply_scenario_state(meeting, manager_user, rooms, songs, scenario, assigned_songs=cfg['assigned_songs'])

    login(request, manager_user, backend='django.contrib.auth.backends.ModelBackend')
    request.session['demo_mode'] = True
    request.session['demo_role'] = 'manager'
    request.session['demo_scenario'] = scenario
    request.session['demo_band_id'] = str(band.id)
    request.session['demo_meeting_id'] = str(meeting.id)
    request.session['demo_user_manager_id'] = str(manager_user.id)
    request.session['demo_user_member_id'] = str(member_user.id)
    request.session['demo_user_ids'] = [str(u.id) for u in demo_users]
    request.session['demo_cache_scope'] = cache_scope

    return redirect('demo_scenario', scenario=scenario)


@login_required
def demo_scenario(request, scenario):
    if not request.session.get('demo_mode'):
        messages.info(request, '먼저 데모를 시작해주세요.')
        return redirect('demo_home')
    meeting_id = request.session.get('demo_meeting_id')
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if scenario not in (1, 2, 3):
        scenario = 1
    manager_user_id = request.session.get('demo_user_manager_id')
    manager_user = get_object_or_404(User, id=manager_user_id)
    rooms = list(meeting.band.rooms.filter(is_temporary=False).order_by('name'))
    songs = list(meeting.songs.order_by('created_at', 'title', 'id'))
    cfg = SCENARIO_CONFIG.get(scenario, SCENARIO_CONFIG[1])
    _apply_scenario_state(meeting, manager_user, rooms, songs, scenario, assigned_songs=cfg['assigned_songs'])
    request.session['demo_scenario'] = scenario
    return _redirect_for_scenario(request, meeting, scenario)


@login_required
def demo_switch_role(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not request.session.get('demo_mode'):
        return redirect('demo_home')

    current_role = str(request.session.get('demo_role') or 'manager')
    next_role = 'member' if current_role == 'manager' else 'manager'
    user_key = 'demo_user_member_id' if next_role == 'member' else 'demo_user_manager_id'
    target_user_id = request.session.get(user_key)
    target_user = get_object_or_404(User, id=target_user_id)
    preserved = {key: request.session.get(key) for key in DEMO_SESSION_KEYS}
    login(request, target_user, backend='django.contrib.auth.backends.ModelBackend')
    for key, value in preserved.items():
        if value is not None:
            request.session[key] = value
    request.session['demo_role'] = next_role

    next_url = str(request.POST.get('next') or '').strip()
    if not next_url or not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        scenario = int(request.session.get('demo_scenario') or 1)
        return redirect('demo_scenario', scenario=scenario)
    return redirect(next_url)


@transaction.atomic
def demo_exit(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not request.session.get('demo_mode'):
        return redirect('home')
    _cleanup_demo_assets_from_session(request)
    if request.user.is_authenticated:
        logout(request)
    return redirect('home')
