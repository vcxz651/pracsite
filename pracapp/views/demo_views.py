import datetime
import csv
import random
import uuid
import re
from urllib.parse import urlencode
from collections import defaultdict
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
    RecurringBlock,
    OneOffBlock,
    RecurringException,
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

DEMO_TEMPLATE_CSV = Path(__file__).resolve().parents[2] / '김민기_밴드음악_명곡선_선곡템플릿.csv'

SCENARIO_CONFIG = {
    1: {'label': 'A', 'member_count': 40, 'total_songs': 50, 'assigned_songs': 50},
    2: {'label': 'B', 'member_count': 6, 'total_songs': 20, 'assigned_songs': 4},
    3: {'label': 'C', 'member_count': 40, 'total_songs': 80, 'assigned_songs': 25},
}

SCENARIO_DATE_MESSAGES = {
    1: '지금은 4월 3일입니다. 밴드의 선곡회의가 막 끝난 시점입니다.',
    2: '지금은 4월 3일입니다. 오늘 우리 팀의 선곡회의가 있습니다.',
    3: '지금은 5월 18일입니다. 합주가 이미 시작된 시점입니다.',
}

DEMO_TEMPLATE_BAND_PREFIX = '[데모TEMPLATE]'
DEMO_TEMPLATE_MEETING_PREFIX = '[데모TEMPLATE]'
DEMO_WORK_BAND_PREFIX = '[데모WORK]'
DEMO_WORK_MEETING_PREFIX = '[데모WORK]'

DEMO_TUTORIAL_TARGET_TITLES = [
    'ㄷㅅㅎㅅ',
    "Can't We Start It All Over Again",
    '비구름',
    'A',
    '마냥 걷는다',
]


def _normalize_cache_scope(raw_scope):
    scope = re.sub(r'[^a-zA-Z0-9_-]+', '', str(raw_scope or '').strip())
    scope = scope[:24]
    return scope or 'global'


def _template_band_name(scenario):
    cfg = SCENARIO_CONFIG.get(int(scenario), SCENARIO_CONFIG[1])
    return f"{DEMO_TEMPLATE_BAND_PREFIX}[S{int(scenario)}] 락스타즈"


def _template_meeting_title(scenario):
    cfg = SCENARIO_CONFIG.get(int(scenario), SCENARIO_CONFIG[1])
    return f"{DEMO_TEMPLATE_MEETING_PREFIX} 시나리오 {cfg['label']}"


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
    scope = _normalize_cache_scope(uuid.uuid4().hex[:8])
    request.session['demo_cache_scope'] = scope
    return scope


def _tutorial_song_status_class(song):
    sessions = list(song.sessions.all())
    applicant_counts = [sess.applicant.count() for sess in sessions]
    all_assigned = bool(sessions) and all(sess.assignee_id for sess in sessions)
    missing_applicant_session_count = sum(1 for cnt in applicant_counts if cnt <= 0)
    if all_assigned:
        return 'song-card-fully-assigned'
    if missing_applicant_session_count <= 0:
        return 'bg-success bg-opacity-10'
    if missing_applicant_session_count == 1:
        return 'bg-warning bg-opacity-10'
    if missing_applicant_session_count == 2:
        return 'bg-orange bg-opacity-10'
    return 'bg-danger bg-opacity-10'


def _tutorial_song_coverage_key(song):
    sessions = list(song.sessions.all())
    applicant_counts = [sess.applicant.count() for sess in sessions]
    all_assigned = bool(sessions) and all(sess.assignee_id for sess in sessions)
    missing_applicant_session_count = sum(1 for cnt in applicant_counts if cnt <= 0)
    if all_assigned:
        return 'fully_assigned'
    if missing_applicant_session_count <= 0:
        return 'full'
    if missing_applicant_session_count == 1:
        return 'one'
    if missing_applicant_session_count == 2:
        return 'two'
    return 'three_plus'


def _serialize_demo_tutorial_song(song, order_index):
    slots = []
    assigned_names = []
    for item in list(song.get_ordered_sessions())[:6]:
        session = item.get('obj')
        assignee_name = str(getattr(getattr(session, 'assignee', None), 'realname', '') or '') if session else ''
        applicant_names = []
        if session:
            applicant_names = [
                str(getattr(user, 'realname', '') or getattr(user, 'username', '') or '').strip()
                for user in session.applicant.all()
                if str(getattr(user, 'realname', '') or getattr(user, 'username', '') or '').strip()
            ]
        if assignee_name:
            assigned_names.append(assignee_name)
        slots.append({
            'label': str(item.get('abbr') or item.get('role') or ''),
            'assignee_name': assignee_name,
            'applicant_names': applicant_names,
            'is_empty': session is None,
        })
    while len(slots) < 6:
        slots.append({'label': '', 'assignee_name': '', 'applicant_names': [], 'is_empty': True})
    return {
        'title': str(song.title or ''),
        'artist': str(song.artist or '-'),
        'order': int(order_index),
        'status_class': _tutorial_song_status_class(song),
        'coverage_key': _tutorial_song_coverage_key(song),
        'assigned_names': assigned_names,
        'slots': slots,
    }


def _build_demo_tutorial_song_cards(meeting):
    songs = list(
        meeting.songs.prefetch_related('sessions__applicant', 'sessions__assignee').order_by('created_at', 'title', 'id')
    )
    by_title = {str(song.title or ''): song for song in songs}
    selected = []
    used_ids = set()
    for title in DEMO_TUTORIAL_TARGET_TITLES:
        song = by_title.get(title)
        if song:
            selected.append(song)
            used_ids.add(str(song.id))
    for song in songs:
        if len(selected) >= 5:
            break
        if str(song.id) in used_ids:
            continue
        selected.append(song)
        used_ids.add(str(song.id))
    cards = [
        _serialize_demo_tutorial_song(song, idx + 1)
        for idx, song in enumerate(selected[:5])
    ]
    while len(cards) < 5:
        cards.append({
            'title': '곡 정보 없음',
            'artist': '-',
            'order': len(cards) + 1,
            'status_class': 'bg-warning bg-opacity-10',
            'coverage_key': 'one',
            'assigned_names': [],
            'slots': [{'label': '', 'assignee_name': '', 'applicant_names': [], 'is_empty': True} for _ in range(6)],
        })
    member_counts = defaultdict(int)
    for card in cards:
        for name in card.get('assigned_names', []):
            member_counts[name] += 1
    for card in cards:
        card['assigned_names_csv'] = '|'.join(card.get('assigned_names', []))
    return cards, dict(member_counts)


def _tutorial_status_from_counts(non_empty_slots):
    all_assigned = bool(non_empty_slots) and all(str(slot.get('assignee_name') or '').strip() for slot in non_empty_slots)
    missing_applicant_session_count = sum(
        1
        for slot in non_empty_slots
        if not str(slot.get('assignee_name') or '').strip() and not list(slot.get('applicant_names') or [])
    )
    if all_assigned:
        return 'song-card-fully-assigned', 'fully_assigned'
    if missing_applicant_session_count <= 0:
        return 'bg-success bg-opacity-10', 'full'
    if missing_applicant_session_count == 1:
        return 'bg-warning bg-opacity-10', 'one'
    if missing_applicant_session_count == 2:
        return 'bg-orange bg-opacity-10', 'two'
    return 'bg-danger bg-opacity-10', 'three_plus'


def _inflate_tutorial_display_applicants(cards, fallback_names, minimum_per_slot=3):
    unique_pool = []
    seen_pool = set()
    for raw_name in fallback_names or []:
        name = str(raw_name or '').strip()
        if not name or name in seen_pool:
            continue
        unique_pool.append(name)
        seen_pool.add(name)

    for card in cards:
        for slot in card.get('slots', []):
            if slot.get('is_empty'):
                continue
            existing_names = []
            seen_names = set()
            for raw_name in slot.get('applicant_names') or []:
                name = str(raw_name or '').strip()
                if not name or name in seen_names:
                    continue
                existing_names.append(name)
                seen_names.add(name)
            while len(existing_names) < int(minimum_per_slot):
                next_name = next((name for name in unique_pool if name not in seen_names), '')
                if not next_name:
                    break
                existing_names.append(next_name)
                seen_names.add(next_name)
            slot['applicant_names'] = existing_names

        non_empty_slots = [slot for slot in card.get('slots', []) if not slot.get('is_empty')]
        status_class, coverage_key = _tutorial_status_from_counts(non_empty_slots)
        card['status_class'] = status_class
        card['coverage_key'] = coverage_key


def _clear_demo_session(request):
    for key in DEMO_SESSION_KEYS:
        request.session.pop(key, None)


def _cleanup_demo_assets_from_session(request):
    band_id = request.session.get('demo_band_id')
    if band_id:
        working_band = Band.objects.filter(id=band_id).first()
        if working_band and str(getattr(working_band, 'name', '') or '').startswith(DEMO_WORK_BAND_PREFIX):
            Band.objects.filter(id=working_band.id).delete()

    meeting_id = request.session.get('demo_meeting_id')
    if meeting_id:
        working_meeting = Meeting.objects.filter(id=meeting_id).first()
        if working_meeting and str(getattr(working_meeting, 'title', '') or '').startswith(DEMO_WORK_MEETING_PREFIX):
            Meeting.objects.filter(id=working_meeting.id).delete()

    if band_id:
        Band.objects.filter(id=band_id, name__startswith='[데모CACHE]').delete()
    _clear_demo_session(request)


def _begin_demo_scenario(request, scenario):
    scenario = int(scenario or 1)
    if scenario not in (1, 2, 3):
        scenario = 1

    if request.session.get('demo_mode'):
        _cleanup_demo_assets_from_session(request)

    band, template_meeting, _rooms, _songs, demo_users, manager_user, member_user = _ensure_demo_template_dataset(scenario)
    meeting = template_meeting if scenario == 1 else _clone_demo_working_meeting(template_meeting, manager_user)
    if scenario == 1:
        MeetingWorkDraft.objects.filter(meeting=meeting, user=manager_user).delete()

    login(request, manager_user, backend='django.contrib.auth.backends.ModelBackend')
    request.session['demo_mode'] = True
    request.session['demo_role'] = 'manager'
    request.session['demo_scenario'] = scenario
    request.session['demo_band_id'] = str(meeting.band_id)
    request.session['demo_meeting_id'] = str(meeting.id)
    request.session['demo_user_manager_id'] = str(manager_user.id)
    request.session['demo_user_member_id'] = str(member_user.id)
    request.session['demo_user_ids'] = []
    return redirect('demo_scenario', scenario=scenario)


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
        'sd': '0',
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
    if not DEMO_TEMPLATE_CSV.exists():
        raise FileNotFoundError(f"데모 템플릿 CSV를 찾을 수 없습니다: {DEMO_TEMPLATE_CSV}")
    rows = []
    with DEMO_TEMPLATE_CSV.open(newline='', encoding='utf-8') as f:
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


def _pick_seed_assignee_for_session(sess_name, instrument_users, manager_user, seeded_role_counts):
    if sess_name.startswith('Vocal'):
        pool = list(instrument_users['Vocal'])
    elif sess_name.startswith('Guitar'):
        pool = list(instrument_users['Guitar'])
    elif sess_name.startswith('Bass'):
        pool = list(instrument_users['Bass'])
    elif sess_name.startswith('Drum'):
        pool = list(instrument_users['Drum'])
        if pool:
            min_count = min(seeded_role_counts['Drum'].get(u.id, 0) for u in pool)
            candidates = [u for u in pool if seeded_role_counts['Drum'].get(u.id, 0) == min_count]
            picked = random.choice(candidates)
            seeded_role_counts['Drum'][picked.id] += 1
            return picked
    elif sess_name.startswith('Keyboard'):
        pool = list(instrument_users['Keyboard'])
    else:
        return manager_user

    if not pool:
        return manager_user
    return random.choice(pool)


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
        realname='체험 캐시 매니저',
        instrument='Guitar',
    )
    member_user = User.objects.create_user(
        username=f"{cache_prefix}member",
        password=uuid.uuid4().hex,
        realname='체험 캐시 멤버',
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
    meeting.title = f"[체험CACHE] 시나리오 {cfg['label']}"
    meeting.save(update_fields=['title'])
    _backfill_assignee_to_applicant(meeting)
    return band, meeting, rooms, songs, demo_users, manager_user, member_user


def _ensure_demo_template_dataset(scenario):
    scenario = int(scenario)
    cfg = SCENARIO_CONFIG.get(scenario, SCENARIO_CONFIG[1])
    band_name = _template_band_name(scenario)
    meeting_title = _template_meeting_title(scenario)
    user_prefix = f"demo_template_s{scenario}_"

    band = Band.objects.filter(name=band_name).first()
    if band:
        meeting = band.meetings.filter(title=meeting_title).order_by('created_at').first()
        users = _collect_band_users(band)
        manager_user = next((u for u in users if band.memberships.filter(user=u, role='LEADER').exists()), None)
        member_user = next((u for u in users if u != manager_user), None)
        template_user_count_ok = len(users) >= int(cfg['member_count'])
        template_participant_count_ok = bool(meeting and meeting.participants.count() >= int(cfg['member_count']))
        template_song_count_ok = bool(meeting and meeting.songs.count() == int(cfg['total_songs']))
        template_assigned_song_count_ok = False
        template_song_session_count_ok = False
        template_song_complexity_ok = True
        template_extra_session_assignment_ok = True
        if meeting:
            songs_with_required_sessions = [
                song for song in meeting.songs.all()
                if song.sessions.filter(is_extra=False).exists()
            ]
            template_song_session_count_ok = len(songs_with_required_sessions) == int(cfg['total_songs'])
            fully_assigned_song_count = sum(
                1 for song in songs_with_required_sessions
                if all(sess.assignee_id for sess in song.sessions.filter(is_extra=False))
            )
            template_assigned_song_count_ok = fully_assigned_song_count >= int(cfg['assigned_songs'])
            if scenario == 1:
                template_song_complexity_ok = all(song.sessions.count() <= 6 for song in meeting.songs.all())
                extra_sessions = [
                    sess
                    for song in meeting.songs.all()
                    for sess in song.sessions.all()
                    if sess.is_extra
                ]
                template_extra_session_assignment_ok = all(sess.assignee_id for sess in extra_sessions)
        if (
            meeting
            and manager_user
            and member_user
            and template_user_count_ok
            and template_participant_count_ok
            and template_song_count_ok
            and template_song_session_count_ok
            and template_assigned_song_count_ok
            and template_song_complexity_ok
            and template_extra_session_assignment_ok
        ):
            _backfill_assignee_to_applicant(meeting)
            if scenario == 1:
                MeetingWorkDraft.objects.filter(meeting=meeting, user=manager_user).delete()
            rooms = list(band.rooms.filter(is_temporary=False).order_by('name'))
            songs = list(meeting.songs.order_by('created_at', 'title', 'id'))
            return band, meeting, rooms, songs, users, manager_user, member_user
        Band.objects.filter(id=band.id).delete()

    User.objects.filter(username__startswith=user_prefix).delete()
    manager_user = User.objects.create_user(
        username=f"{user_prefix}manager",
        password=uuid.uuid4().hex,
        realname='체험 템플릿 매니저',
        instrument='Guitar',
    )
    member_user = User.objects.create_user(
        username=f"{user_prefix}member",
        password=uuid.uuid4().hex,
        realname='체험 템플릿 멤버',
        instrument='Vocal',
    )
    band, meeting, rooms, songs, demo_users = _seed_demo_meeting_data(
        manager_user=manager_user,
        member_user=member_user,
        member_count=cfg['member_count'],
        total_songs=cfg['total_songs'],
        assigned_songs=cfg['assigned_songs'],
    )
    band.name = band_name
    band.save(update_fields=['name'])
    meeting.title = meeting_title
    meeting.save(update_fields=['title'])
    _apply_scenario_state(meeting, manager_user, rooms, songs, scenario, assigned_songs=cfg['assigned_songs'])
    _backfill_assignee_to_applicant(meeting)
    return band, meeting, rooms, songs, demo_users, manager_user, member_user


def _remap_event_payload_rooms(events, room_map):
    if not isinstance(events, list):
        return events
    remapped = []
    for row in events:
        if not isinstance(row, dict):
            remapped.append(row)
            continue
        copied = dict(row)
        room_obj = room_map.get(str(row.get('room_id')))
        if room_obj:
            copied['room_id'] = str(room_obj.id)
            copied['room_name'] = room_obj.name
            copied['room_location'] = room_obj.location
        remapped.append(copied)
    return remapped


def _remap_match_params(match_params, room_map):
    if not isinstance(match_params, dict):
        return match_params
    remapped = dict(match_params)
    for key in ('r', 'rp'):
        raw = remapped.get(key)
        if not raw:
            continue
        mapped_ids = []
        for room_id in str(raw).split(','):
            room_obj = room_map.get(str(room_id))
            mapped_ids.append(str(room_obj.id) if room_obj else str(room_id))
        remapped[key] = ','.join(mapped_ids)
    return remapped


def _remap_booking_completed_keys(keys, room_map):
    if not isinstance(keys, list):
        return keys
    remapped = []
    for raw in keys:
        parts = str(raw or '').split('|')
        if len(parts) == 5:
            room_obj = room_map.get(parts[4])
            if room_obj:
                parts[4] = str(room_obj.id)
            remapped.append('|'.join(parts))
        else:
            remapped.append(raw)
    return remapped


def _build_intro_personal_board(user, base_date):
    monday = base_date - datetime.timedelta(days=base_date.weekday())
    sunday = monday + datetime.timedelta(days=6)
    weekday_kor = ['월', '화', '수', '목', '금', '토', '일']

    personal_ranges_by_date = defaultdict(list)
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

    # 인트로 프리뷰는 멤버마다 시간축이 흔들리면 비교가 어려우므로 고정 범위로 유지한다.
    slot_start = 18  # 09:00
    slot_end = 48    # 24:00
    slot_count = slot_end - slot_start

    time_rows = []
    for slot in range(slot_start, slot_end + 1):
        label = ''
        if slot % 2 == 0:
            h = slot // 2
            label = f'{h:02d}:00'
        time_rows.append({'slot': slot, 'label': label})

    days = []
    total_personal_blocks = 0
    for i in range(7):
        d = monday + datetime.timedelta(days=i)
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
        total_personal_blocks += len(personal_blocks)
        days.append({
            'date': d,
            'date_text': f"{d.month}/{d.day}({weekday_kor[d.weekday()]})",
            'is_today': d == base_date,
            'events': [],
            'personal_blocks': personal_blocks,
        })

    return {
        'week_start': monday,
        'week_end': sunday,
        'slot_start': slot_start,
        'slot_end': slot_end,
        'slot_count': slot_count,
        'time_rows': time_rows,
        'days': days,
        'has_events': total_personal_blocks > 0,
    }


def _clone_demo_working_meeting(template_meeting, manager_user):
    suffix = uuid.uuid4().hex[:8]
    template_band = template_meeting.band
    working_band = Band.objects.create(
        name=f"{DEMO_WORK_BAND_PREFIX} {suffix}",
        school=template_band.school,
        department=template_band.department,
        department_detail=template_band.department_detail,
        introduce=template_band.introduce,
        description=template_band.description,
        is_public=False,
    )
    template_memberships = list(template_band.memberships.select_related('user').order_by('date_joined', 'id'))
    membership_rows = []
    for membership in template_memberships:
        membership_rows.append(Membership(
            user=membership.user,
            band=working_band,
            message=membership.message,
            is_approved=membership.is_approved,
            approval_notified=membership.approval_notified,
            role=membership.role,
            date_joined=membership.date_joined,
        ))
    if membership_rows:
        Membership.objects.bulk_create(membership_rows)

    room_map = {}
    template_rooms = list(template_band.rooms.order_by('name', 'id'))
    for template_room in template_rooms:
        cloned_room = PracticeRoom.objects.create(
            band=working_band,
            name=template_room.name,
            capacity=template_room.capacity,
            location=template_room.location,
            is_temporary=template_room.is_temporary,
        )
        room_map[str(template_room.id)] = cloned_room

    working_meeting = Meeting.objects.create(
        band=working_band,
        title=f"{DEMO_WORK_MEETING_PREFIX} {template_meeting.title.replace(DEMO_TEMPLATE_MEETING_PREFIX, '').strip()} {suffix}",
        description=template_meeting.description,
        practice_start_date=template_meeting.practice_start_date,
        practice_end_date=template_meeting.practice_end_date,
        is_schedule_coordinating=template_meeting.is_schedule_coordinating,
        is_final_schedule_released=template_meeting.is_final_schedule_released,
        is_booking_in_progress=template_meeting.is_booking_in_progress,
        is_final_schedule_confirmed=template_meeting.is_final_schedule_confirmed,
        schedule_version=template_meeting.schedule_version,
    )

    participant_rows = []
    template_participants = list(
        template_meeting.participants.select_related('user', 'approved_by').order_by('approved_at', 'requested_at', 'id')
    )
    for participant in template_participants:
        participant_rows.append(MeetingParticipant(
            meeting=working_meeting,
            user=participant.user,
            status=participant.status,
            role=participant.role,
            approved_at=participant.approved_at,
            approved_by=participant.approved_by,
        ))
    if participant_rows:
        MeetingParticipant.objects.bulk_create(participant_rows)

    song_map = {}
    template_songs = list(template_meeting.songs.order_by('created_at', 'title', 'id'))
    for template_song in template_songs:
        cloned_song = Song.objects.create(
            meeting=working_meeting,
            author=template_song.author,
            title=template_song.title,
            artist=template_song.artist,
            url=template_song.url,
            author_note=template_song.author_note,
        )
        song_map[str(template_song.id)] = cloned_song

    session_applicants = []
    for template_song in template_songs:
        cloned_song = song_map.get(str(template_song.id))
        if not cloned_song:
            continue
        template_sessions = list(template_song.sessions.order_by('id'))
        for template_session in template_sessions:
            cloned_session = Session.objects.create(
                song=cloned_song,
                name=template_session.name,
                is_extra=template_session.is_extra,
                assignee=template_session.assignee,
            )
            applicant_ids = list(template_session.applicant.values_list('id', flat=True))
            for user_id in applicant_ids:
                session_applicants.append(Session.applicant.through(session_id=cloned_session.id, user_id=user_id))
    if session_applicants:
        Session.applicant.through.objects.bulk_create(session_applicants, ignore_conflicts=True)

    work_drafts = list(MeetingWorkDraft.objects.filter(meeting=template_meeting))
    for draft in work_drafts:
        MeetingWorkDraft.objects.create(
            meeting=working_meeting,
            user=draft.user,
            events=_remap_event_payload_rooms(draft.events, room_map),
            match_params=_remap_match_params(draft.match_params, room_map),
        )

    final_drafts = list(MeetingFinalDraft.objects.filter(meeting=template_meeting))
    for draft in final_drafts:
        MeetingFinalDraft.objects.create(
            meeting=working_meeting,
            match_params=_remap_match_params(draft.match_params, room_map),
            events=_remap_event_payload_rooms(draft.events, room_map),
            booking_completed_keys=_remap_booking_completed_keys(draft.booking_completed_keys, room_map),
        )

    schedule_rows = []
    for row in PracticeSchedule.objects.filter(meeting=template_meeting).select_related('song', 'room'):
        cloned_song = song_map.get(str(row.song_id))
        cloned_room = room_map.get(str(row.room_id))
        if not cloned_song or not cloned_room:
            continue
        schedule_rows.append(PracticeSchedule(
            meeting=working_meeting,
            song=cloned_song,
            room=cloned_room,
            date=row.date,
            start_index=row.start_index,
            end_index=row.end_index,
            is_forced=row.is_forced,
        ))
    if schedule_rows:
        PracticeSchedule.objects.bulk_create(schedule_rows)

    confirmations = []
    for ack in MeetingScheduleConfirmation.objects.filter(meeting=template_meeting):
        confirmations.append(MeetingScheduleConfirmation(
            meeting=working_meeting,
            user=ack.user,
            version=ack.version,
        ))
    if confirmations:
        MeetingScheduleConfirmation.objects.bulk_create(confirmations, ignore_conflicts=True)

    ghost_meeting_map = {}
    template_ghosts = list(
        template_band.meetings.filter(title__startswith='[체험B]').exclude(id=template_meeting.id).order_by('created_at', 'id')
    )
    for ghost in template_ghosts:
        cloned_ghost = Meeting.objects.create(
            band=working_band,
            title=ghost.title,
            description=ghost.description,
            practice_start_date=ghost.practice_start_date,
            practice_end_date=ghost.practice_end_date,
            is_schedule_coordinating=ghost.is_schedule_coordinating,
            is_final_schedule_released=ghost.is_final_schedule_released,
            is_booking_in_progress=ghost.is_booking_in_progress,
            is_final_schedule_confirmed=ghost.is_final_schedule_confirmed,
            schedule_version=ghost.schedule_version,
        )
        ghost_meeting_map[str(ghost.id)] = cloned_ghost

    room_blocks = []
    template_blocks = RoomBlock.objects.filter(
        source_meeting__in=template_ghosts
    ).select_related('room', 'source_meeting').order_by('date', 'start_index', 'id')
    for block in template_blocks:
        cloned_room = room_map.get(str(block.room_id))
        cloned_source_meeting = ghost_meeting_map.get(str(block.source_meeting_id))
        if not cloned_room or not cloned_source_meeting:
            continue
        room_blocks.append(RoomBlock(
            room=cloned_room,
            date=block.date,
            start_index=block.start_index,
            end_index=block.end_index,
            source_meeting=cloned_source_meeting,
        ))
    if room_blocks:
        RoomBlock.objects.bulk_create(room_blocks)

    return working_meeting


def _seed_demo_meeting_data(manager_user, member_user, member_count=40, total_songs=80, assigned_songs=25):
    random.seed(20260225)
    suffix = uuid.uuid4().hex[:8]
    band = Band.objects.create(
        name=f"[체험DB] 락스타즈-{suffix}",
        school='Demo School',
        department='ETC',
        department_detail='체험 전용',
        introduce='체험 전용 밴드',
        description='체험 전용 데이터',
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
        title='[체험] 합주 일정 시뮬레이션',
        description='체험 시나리오용 선곡회의',
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
    seeded_role_counts = defaultdict(lambda: defaultdict(int))

    # 더미데이터 규칙: 멤버 일정(수업/알바/oneoff) -> 가용 슬롯 동기화
    for user in demo_users:
        _create_weekly_schedule_for_user(user, practice_start_date, practice_end_date)
    _apply_weekly_club_activity_rules(demo_users, practice_start_date, practice_end_date)
    _apply_weekly_random_oneoff_rules(demo_users, practice_start_date, practice_end_date)
    for user in demo_users:
        _sync_member_availability_from_blocks(user, practice_start_date, practice_end_date)

    songs = []
    template_rows = _load_demo_song_template_rows(limit=None)
    created_song_count = 0
    for row in template_rows:
        if created_song_count >= int(total_songs):
            break
        title = str(row.get('title') or '').strip()
        artist = str(row.get('artist') or '').strip()
        needed = [s.strip() for s in str(row.get('needed_session') or '').split(',') if s.strip()]
        extras = [s.strip() for s in str(row.get('extra_session') or '').split(',') if s.strip()]

        if (not title) or (not needed):
            continue
        if len(needed) + len(extras) > 6:
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
        should_assign = created_song_count < int(assigned_songs)
        created_song_count += 1
        for sess_name in needed:
            sess = Session.objects.create(song=song, name=sess_name, is_extra=False)
            if should_assign:
                assignee = _pick_seed_assignee_for_session(
                    sess_name=sess_name,
                    instrument_users=instrument_users,
                    manager_user=manager_user,
                    seeded_role_counts=seeded_role_counts,
                )
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
            extra_sess = Session.objects.create(song=song, name=sess_name, is_extra=True)
            if should_assign:
                extra_assignee = _pick_seed_assignee_for_session(
                    sess_name=sess_name,
                    instrument_users=instrument_users,
                    manager_user=manager_user,
                    seeded_role_counts=seeded_role_counts,
                )
                extra_sess.assignee = extra_assignee
                extra_sess.save(update_fields=['assignee'])
                extra_sess.applicant.add(extra_assignee)
            else:
                extra_applicants = _pick_session_applicants(
                    sess_name=sess_name,
                    instrument_users=instrument_users,
                    fallback_users=demo_users,
                    count=(2 if random.random() < 0.35 else 1),
                )
                if extra_applicants:
                    extra_sess.applicant.add(*extra_applicants)

    return band, meeting, rooms, songs, demo_users


def _build_events_for_songs(songs, rooms, start_date, max_events=None, fixed_duration_slots=None):
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
        duration = int(fixed_duration_slots) if fixed_duration_slots is not None else duration_cycle[idx % len(duration_cycle)]
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
    Meeting.objects.filter(band=band, title__startswith='[체험B]').delete()
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
            title=f'[체험B] {team_name} 예약',
            description='체험 시나리오 B 보조 미팅',
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
    RoomBlock.objects.filter(source_meeting__band=meeting.band, source_meeting__title__startswith='[체험B]').delete()
    Meeting.objects.filter(band=meeting.band, title__startswith='[체험B]').delete()

    start_date = meeting.practice_start_date or (datetime.date.today() + datetime.timedelta(days=1))
    match_params = _build_match_params(rooms)
    schedulable_songs = [song for song in songs if song.is_session_full]
    fixed_duration_slots = 2 if scenario == 1 else None
    base_events = _build_events_for_songs(
        schedulable_songs,
        rooms,
        start_date,
        max_events=assigned_songs,
        fixed_duration_slots=fixed_duration_slots,
    )
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
        rooms = list(PracticeRoom.objects.filter(band=meeting.band, is_temporary=False).order_by('name', 'id'))
        match_params = _build_match_params(rooms)
        query = {
            'd': str(match_params.get('d') or '60'),
            'c': str(match_params.get('c') or '1'),
            'p': str(match_params.get('p') or ''),
            'r': str(match_params.get('r') or ''),
            'rp': str(match_params.get('rp') or ''),
            'w': str(match_params.get('w') or '0'),
            're': str(match_params.get('re') or '0'),
            'h': str(match_params.get('h') or '0'),
            'sd': str(match_params.get('sd') or '0'),
            'ts': str(match_params.get('ts') or '18'),
            'te': str(match_params.get('te') or '48'),
            'force_rematch': '1',
        }
        run_url = f"{reverse('schedule_match_run', args=[meeting.id])}?{urlencode(query)}"
        return redirect(run_url)
    if scenario == 2:
        return redirect('demo_dashboard')
    return redirect('schedule_final', meeting_id=meeting.id)


def demo_home(request):
    band, meeting, rooms, songs, users, manager_user, member_user = _ensure_demo_template_dataset(1)
    intro_users = list(users)[:40]
    member_index_by_id = {str(user.id): idx for idx, user in enumerate(intro_users)}
    base_date = meeting.practice_start_date or timezone.localdate()
    show_intro_video_modal = bool(
        request.user.is_authenticated and request.session.pop('show_intro_video_modal', False)
    )

    intro_member_schedules = []
    intro_member_preview_map = {}
    intro_board_template = None
    for idx, user in enumerate(intro_users):
        board = _build_intro_personal_board(user, base_date)
        if intro_board_template is None:
            intro_board_template = {
                'slot_count': board['slot_count'],
                'time_rows': list(board['time_rows']),
                'days': [
                    {
                        'date_text': day['date_text'],
                        'is_today': day['is_today'],
                        'personal_blocks': [],
                        'events': [],
                    }
                    for day in board['days']
                ],
            }
        intro_member_schedules.append({
            'index': idx,
            'name': str(getattr(user, 'realname', '') or getattr(user, 'username', '') or f'멤버 {idx + 1}'),
            'summary': f"실제 create_dummy 규칙으로 생성된 개인 일정",
            'board': board,
        })
        intro_member_preview_map[str(idx)] = {
            'name': str(getattr(user, 'realname', '') or getattr(user, 'username', '') or f'멤버 {idx + 1}'),
            'days': [
                {
                    'personal_blocks': [
                        {
                            'top_slots': int(pb.get('top_slots', 0)),
                            'span_slots': int(pb.get('span_slots', 1)),
                            'reason_text': str(pb.get('reason_text', '') or ''),
                        }
                        for pb in day.get('personal_blocks', [])
                    ]
                }
                for day in board['days']
            ],
        }

    intro_song_list = []
    actual_songs = list(songs)[:50]
    for idx, song in enumerate(actual_songs, start=1):
        assignees = []
        assignee_indices = []
        for sess in song.sessions.filter(assignee__isnull=False).select_related('assignee').order_by('is_extra', 'name', 'id'):
            assignee_name = str(getattr(sess.assignee, 'realname', '') or getattr(sess.assignee, 'username', '') or '-')
            assignees.append(f"{sess.name}: {assignee_name}")
            member_index = member_index_by_id.get(str(sess.assignee_id))
            if member_index is not None and member_index not in assignee_indices:
                assignee_indices.append(member_index)
        intro_song_list.append({
            'order': idx,
            'title': song.title,
            'artist': song.artist,
            'assignees': assignees,
            'assignee_indices': assignee_indices,
        })
    return render(request, 'pracapp/demo/demo_home.html', {
        'intro_member_schedules': intro_member_schedules,
        'intro_member_preview_map': intro_member_preview_map,
        'intro_board_template': intro_board_template,
        'intro_song_list': intro_song_list,
        'show_intro_video_modal': show_intro_video_modal,
    })


@login_required
def demo_dashboard(request):
    if not request.session.get('demo_mode'):
        messages.info(request, '먼저 체험을 시작해주세요.')
        return redirect('demo_home')
    scenario = int(request.session.get('demo_scenario') or 1)
    if scenario != 2:
        return redirect('demo_scenario', scenario=scenario)
    meeting_id = request.session.get('demo_meeting_id')
    meeting = get_object_or_404(Meeting, id=meeting_id)
    room_blocks = RoomBlock.objects.filter(
        source_meeting__band=meeting.band,
        source_meeting__title__startswith='[체험B]',
    ).select_related('room', 'source_meeting').order_by('date', 'start_index')

    team_map = {}
    for rb in room_blocks:
        title = str(getattr(rb.source_meeting, 'title', '') or '')
        team_name = title.replace('[체험B] ', '').replace(' 예약', '').strip() or '팀'
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


@login_required
def demo_feature_tutorial(request):
    if not request.session.get('demo_mode'):
        messages.info(request, '먼저 체험을 시작해주세요.')
        return redirect('demo_home')

    meeting_id = request.session.get('demo_meeting_id')
    meeting = get_object_or_404(Meeting, id=meeting_id)
    match_settings_url = reverse('schedule_match_settings', kwargs={'meeting_id': meeting.id})
    tutorial_cards, tutorial_member_counts = _build_demo_tutorial_song_cards(meeting)
    tutorial_member_rows = sorted(
        (
            {'name': name, 'count': count}
            for name, count in tutorial_member_counts.items()
        ),
        key=lambda row: (-int(row['count']), str(row['name'])),
    )
    participant_names = [
        str(getattr(part.user, 'realname', '') or getattr(part.user, 'username', '') or '').strip()
        for part in meeting.participants.select_related('user').all()
        if str(getattr(part.user, 'realname', '') or getattr(part.user, 'username', '') or '').strip()
    ]
    _inflate_tutorial_display_applicants(tutorial_cards, participant_names, minimum_per_slot=3)
    step1_slot = None
    step2_slot = None
    if tutorial_cards:
        primary_slots = tutorial_cards[0].get('slots', [])
        step1_slot = next((slot for slot in primary_slots if str(slot.get('label') or '') == 'G1'), None)
        step2_slot = next((slot for slot in primary_slots if not slot.get('is_empty')), None)
    step1_applicants = list((step1_slot or {}).get('applicant_names') or [])
    step2_assign_choices = list((step2_slot or {}).get('applicant_names') or [])
    if not step1_applicants:
        step1_applicants = participant_names[:3]
    if not step2_assign_choices:
        step2_assign_choices = participant_names[:3]
    manage_primary_names = list(step2_assign_choices[:3])
    manage_secondary_names = [name for name in participant_names if name not in manage_primary_names][:3]
    if not manage_primary_names:
        manage_primary_names = participant_names[:2]
    if not manage_secondary_names:
        manage_secondary_names = participant_names[2:4]
    demo_user_name = str(
        getattr(request.user, 'realname', '') or getattr(request.user, 'username', '') or '체험 매니저'
    ).strip() or '체험 매니저'

    return render(request, 'pracapp/demo/demo_feature_tutorial.html', {
        'meeting': meeting,
        'match_settings_url': match_settings_url,
        'tutorial_cards': tutorial_cards,
        'tutorial_member_rows': tutorial_member_rows[:10],
        'tutorial_step1_applicants': step1_applicants[:5],
        'tutorial_step2_assign_choices': step2_assign_choices[:5],
        'tutorial_manage_primary_names': manage_primary_names,
        'tutorial_manage_secondary_names': manage_secondary_names,
        'tutorial_demo_user_name': demo_user_name,
    })


@transaction.atomic
def demo_start(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    return _begin_demo_scenario(request, request.POST.get('scenario') or 1)


@login_required
def demo_scenario(request, scenario):
    if not request.session.get('demo_mode'):
        messages.info(request, '먼저 체험을 시작해주세요.')
        return redirect('demo_home')
    if scenario not in (1, 2, 3):
        scenario = 1
    current_scenario = int(request.session.get('demo_scenario') or 1)
    meeting_id = request.session.get('demo_meeting_id')
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if current_scenario != scenario:
        current_role = str(request.session.get('demo_role') or 'manager')
        _cleanup_demo_assets_from_session(request)
        band, template_meeting, _rooms, _songs, demo_users, manager_user, member_user = _ensure_demo_template_dataset(scenario)
        meeting = _clone_demo_working_meeting(template_meeting, manager_user)
        login_user = member_user if current_role == 'member' else manager_user
        login(request, login_user, backend='django.contrib.auth.backends.ModelBackend')
        request.session['demo_mode'] = True
        request.session['demo_role'] = current_role
        request.session['demo_band_id'] = str(meeting.band_id)
        request.session['demo_meeting_id'] = str(meeting.id)
        request.session['demo_user_manager_id'] = str(manager_user.id)
        request.session['demo_user_member_id'] = str(member_user.id)
        request.session['demo_user_ids'] = []
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
        return redirect('app_home')
    _cleanup_demo_assets_from_session(request)
    if request.user.is_authenticated:
        logout(request)
    return redirect('app_home')
