# utils.py (새로 생성)
from .models import RecurringBlock, OneOffBlock, RecurringException, MemberAvailability, PracticeSchedule, PracticeRoom, RoomBlock
from datetime import timedelta
from collections import defaultdict
from .models import Session
from django.db.models import Q
from django.db import transaction
from collections import defaultdict
import datetime
import uuid


SESSION_ABBR_MAP = {
    'Vocal': 'V',
    'Drum': 'D',
    'Guitar1': 'G1',
    'Guitar2': 'G2',
    'Keyboard': 'K',
    'Bass': 'B',
}


def _session_abbr(name):
    return SESSION_ABBR_MAP.get(name, name)


def _normalize_exception_day_payload(day_payload):
    if isinstance(day_payload, dict):
        slots = day_payload.get('slots', []) or []
        targeted = day_payload.get('targeted', []) or []
        return {'slots': list(slots), 'targeted': list(targeted)}
    if isinstance(day_payload, list):
        return {'slots': list(day_payload), 'targeted': []}
    return {'slots': [], 'targeted': []}


def _block_target_payload(day_of_week, start_idx, end_idx, reason, scope_start, scope_end):
    return {
        'day_of_week': int(day_of_week),
        'start': int(start_idx),
        'end': int(end_idx),
        'reason': str(reason or '').strip(),
        'scope_start': str(scope_start or ''),
        'scope_end': str(scope_end or ''),
    }


def _target_matches_block(target, block_day, block_start, block_end, block_reason, block_scope_start, block_scope_end):
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
        t_day == int(block_day)
        and t_start == int(block_start)
        and t_end == int(block_end)
        and t_reason == str(block_reason or '').strip()
        and t_scope_start == str(block_scope_start or '')
        and t_scope_end == str(block_scope_end or '')
    )


def _is_block_slot_cancelled(slot, day_payload, block_day, block_start, block_end, block_reason, block_scope_start, block_scope_end):
    normalized = _normalize_exception_day_payload(day_payload)
    if slot in set(normalized['slots']):
        return True
    for target_row in normalized['targeted']:
        t_start = int(target_row.get('start', -1))
        t_end = int(target_row.get('end', -1))
        if not (t_start <= slot < t_end):
            continue
        target = target_row.get('target') or {}
        if _target_matches_block(
            target,
            block_day=block_day,
            block_start=block_start,
            block_end=block_end,
            block_reason=block_reason,
            block_scope_start=block_scope_start,
            block_scope_end=block_scope_end,
        ):
            return True
    return False


def _build_user_unavailable_reason_map(user_ids, start_date, end_date):
    """
    user/date/slot 단위로 불가능 사유(reason) 집합을 계산
    반환 형식: {user_id: {date_str: {slot_idx: set([reason, ...])}}}
    """
    result = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    user_ids = [uid for uid in user_ids if uid]
    if not user_ids or not start_date or not end_date:
        return result

    recurring_qs = RecurringBlock.objects.filter(
        user_id__in=user_ids,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    oneoff_qs = OneOffBlock.objects.filter(
        user_id__in=user_ids,
        date__range=[start_date, end_date],
    )
    exc_qs = RecurringException.objects.filter(
        user_id__in=user_ids,
        date__range=[start_date, end_date],
    )

    recurring_by_user_weekday = defaultdict(lambda: defaultdict(list))
    for rb in recurring_qs:
        recurring_by_user_weekday[rb.user_id][rb.day_of_week].append(rb)

    oneoff_by_user_date = defaultdict(lambda: defaultdict(list))
    for ob in oneoff_qs:
        d_key = ob.date.strftime('%Y-%m-%d')
        oneoff_by_user_date[ob.user_id][d_key].append(ob)

    exc_payload_by_user_date = defaultdict(lambda: defaultdict(lambda: {'slots': [], 'targeted': []}))
    for ex in exc_qs:
        d_key = ex.date.strftime('%Y-%m-%d')
        target_payload = ex.target_payload or {}
        if isinstance(target_payload, dict) and target_payload:
            exc_payload_by_user_date[ex.user_id][d_key]['targeted'].append({
                'start': int(ex.start_index),
                'end': int(ex.end_index),
                'target': target_payload,
            })
            continue
        for slot in range(ex.start_index, ex.end_index):
            exc_payload_by_user_date[ex.user_id][d_key]['slots'].append(int(slot))

    for uid in user_ids:
        cursor = start_date
        while cursor <= end_date:
            d_key = cursor.strftime('%Y-%m-%d')
            day_idx = cursor.weekday()
            exc_payload = exc_payload_by_user_date[uid].get(d_key, {'slots': [], 'targeted': []})

            for rb in recurring_by_user_weekday[uid].get(day_idx, []):
                block_start = rb.start_date or start_date
                block_end = rb.end_date or end_date
                if not (block_start <= cursor <= block_end):
                    continue
                reason = (rb.reason or '').strip() or '고정 일정'
                block_scope_start = block_start.strftime('%Y-%m-%d')
                block_scope_end = block_end.strftime('%Y-%m-%d')
                for slot in range(rb.start_index, rb.end_index):
                    if _is_block_slot_cancelled(
                        slot,
                        exc_payload,
                        block_day=rb.day_of_week,
                        block_start=rb.start_index,
                        block_end=rb.end_index,
                        block_reason=rb.reason,
                        block_scope_start=block_scope_start,
                        block_scope_end=block_scope_end,
                    ):
                        continue
                    result[uid][d_key][slot].add(reason)

            for ob in oneoff_by_user_date[uid].get(d_key, []):
                reason = (ob.reason or '').strip() or '개인 일정'
                for slot in range(ob.start_index, ob.end_index):
                    result[uid][d_key][slot].add(reason)

            cursor += datetime.timedelta(days=1)

    return result


def _recompute_forced_flags(meeting, schedule_events, song_ids=None):
    """
    화면 렌더링 직전에 이벤트의 강제 배정 여부를 재계산.
    - 기존 is_forced=True 는 유지
    - 배정 멤버의 가용 시간이 부족하면 강제로 간주
    - 같은 시간대 동일 멤버 중복 배정이면 강제로 간주
    - 배정 인원이 방 정원을 초과하면 강제로 간주
    """
    if not schedule_events:
        return

    # 곡별 배정 멤버 맵
    song_user_ids_map = {}
    all_user_ids = set()
    songs_qs = meeting.songs.prefetch_related('sessions__assignee')
    if song_ids:
        normalized_song_ids = {str(sid) for sid in song_ids if sid}
        songs_qs = songs_qs.filter(id__in=list(normalized_song_ids))
    for song in songs_qs:
        uids = sorted({
            sess.assignee_id
            for sess in song.sessions.all()
            if sess.assignee_id
        })
        song_user_ids_map[str(song.id)] = uids
        all_user_ids.update(uids)

    # 이벤트 날짜 범위
    event_dates = []
    for ev in schedule_events:
        try:
            d = ev.get('date')
            if isinstance(d, datetime.date):
                event_dates.append(d)
            else:
                event_dates.append(datetime.date.fromisoformat(str(d)))
        except Exception:
            continue

    avail_map = defaultdict(dict)  # {user_id: {date_str: set(slots)}}
    if all_user_ids and event_dates:
        min_date = min(event_dates)
        max_date = max(event_dates)
        av_qs = MemberAvailability.objects.filter(
            user_id__in=list(all_user_ids),
            date__range=[min_date, max_date],
        )
        for av in av_qs:
            avail_map[av.user_id][av.date.strftime('%Y-%m-%d')] = set(av.available_slot or [])

    # 0) 합주실 점유(RoomBlock) 맵
    event_room_ids = set()
    event_dates = set()
    for ev in schedule_events:
        room_obj = ev.get('room')
        room_id = getattr(room_obj, 'id', None)
        if room_id:
            try:
                event_room_ids.add(uuid.UUID(str(room_id)))
            except (ValueError, TypeError, AttributeError):
                # 프론트 가상 임시합주실 id(temp-*)는 RoomBlock 조회 대상에서 제외
                pass
        d_raw = ev.get('date')
        if isinstance(d_raw, datetime.date):
            event_dates.add(d_raw)
        else:
            try:
                event_dates.add(datetime.date.fromisoformat(str(d_raw)))
            except Exception:
                pass

    room_block_slots = defaultdict(set)  # {(room_id_str, date): {slot...}}
    if event_room_ids and event_dates:
        rb_qs = RoomBlock.objects.filter(
            room_id__in=list(event_room_ids),
            date__in=list(event_dates),
        ).exclude(source_meeting=meeting)
        for rb in rb_qs:
            key = (str(rb.room_id), rb.date)
            for slot in range(int(rb.start_index), int(rb.end_index)):
                room_block_slots[key].add(slot)

    # 1) 가용 시간/합주실 점유 기준 강제 여부
    for ev in schedule_events:
        sid = str(ev.get('song').id)
        user_ids = song_user_ids_map.get(sid, [])
        ev['_assigned_user_ids'] = set(user_ids)

        forced = bool(ev.get('is_forced', False))
        if user_ids:
            d_raw = ev.get('date')
            d_key = d_raw.strftime('%Y-%m-%d') if isinstance(d_raw, datetime.date) else str(d_raw)
            d_obj = d_raw if isinstance(d_raw, datetime.date) else None
            if d_obj is None:
                try:
                    d_obj = datetime.date.fromisoformat(d_key)
                except Exception:
                    d_obj = None
            start = int(ev.get('start', 0))
            end = int(ev.get('end', start + 1))

            for uid in user_ids:
                slots = avail_map.get(uid, {}).get(d_key, set())
                for slot in range(start, end):
                    if slot not in slots:
                        forced = True
                        break
                if forced:
                    break

            # 타 미팅/수동 점유 RoomBlock과 겹치면 강제
            room_obj = ev.get('room')
            room_id = getattr(room_obj, 'id', None)
            if (not forced) and room_id and d_obj is not None:
                blocked_slots = room_block_slots.get((str(room_id), d_obj), set())
                for slot in range(start, end):
                    if slot in blocked_slots:
                        forced = True
                        break

        # 1-2) 방 정원 초과 기준 강제 여부
        room_obj = ev.get('room')
        if (not forced) and room_obj is not None:
            try:
                room_capacity = int(getattr(room_obj, 'capacity', 0) or 0)
            except (TypeError, ValueError):
                room_capacity = 0
            if room_capacity > 0 and len(user_ids) > room_capacity:
                forced = True

        ev['is_forced'] = forced

    # 2) 멤버 겹침 기준 강제 여부
    by_date = defaultdict(list)
    for ev in schedule_events:
        d_raw = ev.get('date')
        d_key = d_raw.strftime('%Y-%m-%d') if isinstance(d_raw, datetime.date) else str(d_raw)
        by_date[d_key].append(ev)

    for _, events in by_date.items():
        for i in range(len(events)):
            a = events[i]
            a_users = a.get('_assigned_user_ids', set())
            if not a_users:
                continue
            a_start = int(a.get('start', 0))
            a_end = int(a.get('end', a_start + 1))

            for j in range(i + 1, len(events)):
                b = events[j]
                b_users = b.get('_assigned_user_ids', set())
                if not b_users:
                    continue
                b_start = int(b.get('start', 0))
                b_end = int(b.get('end', b_start + 1))

                overlap_time = (a_start < b_end) and (a_end > b_start)
                overlap_member = not a_users.isdisjoint(b_users)
                if overlap_time and overlap_member:
                    a['is_forced'] = True
                    b['is_forced'] = True

    for ev in schedule_events:
        ev.pop('_assigned_user_ids', None)


def _build_song_conflict_and_member_maps(meeting, song_ids=None):
    """
    곡별 불가능 시간/사유 맵과 멤버 맵을 계산.
    반환: (song_conflict_map, song_member_map)
    """
    song_conflict_map = {}
    song_member_map = {}
    start_date = meeting.practice_start_date
    end_date = meeting.practice_end_date

    if not start_date or not end_date:
        return song_conflict_map, song_member_map

    songs_qs = meeting.songs.prefetch_related('sessions__assignee')
    if song_ids:
        normalized_song_ids = {str(sid) for sid in song_ids if sid}
        songs_qs = songs_qs.filter(id__in=list(normalized_song_ids))
    songs_for_map = list(songs_qs)
    all_assignee_ids = sorted({
        sess.assignee_id
        for song in songs_for_map
        for sess in song.sessions.all()
        if sess.assignee_id
    })
    unavailable_reason_map = _build_user_unavailable_reason_map(
        all_assignee_ids,
        start_date,
        end_date,
    )

    def _format_reason_label(reason_text):
        text = str(reason_text or '').strip()
        if not text:
            return '개인 일정'
        # 합주 사유도 일반 불가와 동일하게 처리하되, 화면에서는 합주임을 명확히 강조.
        if text.startswith('합주:'):
            title = text.split(':', 1)[1].strip() if ':' in text else ''
            return f'합주({title})' if title else '합주'
        return text

    # 곡별로 반복 조회하지 않도록 가용 시간은 전체 assignee 기준으로 한 번에 로드
    global_user_avail = defaultdict(dict)  # {user_id: {date_str: set(slots)}}
    if all_assignee_ids:
        for av in MemberAvailability.objects.filter(
            user_id__in=all_assignee_ids,
            date__range=[start_date, end_date],
        ):
            d_str = av.date.strftime('%Y-%m-%d')
            global_user_avail[av.user_id][d_str] = set(av.available_slot or [])

    for song in songs_for_map:
        assigned_members = []
        for sess in song.sessions.all():
            if sess.assignee:
                display_name = str((sess.assignee.realname or '').strip() or sess.assignee.username)
                assigned_members.append({
                    'user_id': sess.assignee.id,
                    'username': sess.assignee.username,
                    'display_name': display_name,
                    'session': _session_abbr(sess.name),
                })

        unique_members = {}
        for m in assigned_members:
            key = str(m['username'])
            if key not in unique_members:
                unique_members[key] = {
                    'session': m['session'],
                    'display_name': m.get('display_name') or m['username'],
                }
        song_member_map[str(song.id)] = [
            {
                'username': uname,
                'display_name': unique_members[uname]['display_name'],
                'session': unique_members[uname]['session'],
            }
            for uname in sorted(unique_members.keys(), key=lambda x: str(unique_members[x]['display_name']))
        ]

        if not assigned_members:
            continue

        date_cursor = start_date
        per_date = {}
        while date_cursor <= end_date:
            d_str = date_cursor.strftime('%Y-%m-%d')
            slot_reasons = {}
            for member in assigned_members:
                uid = member['user_id']
                uname = member['username']
                display_name = member.get('display_name') or uname
                session_abbr = member.get('session') or ''
                avail_slots = global_user_avail.get(uid, {}).get(d_str, set())
                for slot in range(18, 48):
                    reasons = unavailable_reason_map.get(uid, {}).get(d_str, {}).get(slot, set())
                    # "불가능 일정"은 동등하게 취급:
                    # - 기존 MemberAvailability 기준 불가
                    # - 사유 맵(고정/단발/생성된 합주 포함)에 잡히는 불가
                    is_unavailable = (slot not in avail_slots) or bool(reasons)
                    if is_unavailable:
                        formatted_reasons = [_format_reason_label(r) for r in sorted(reasons)]
                        reason_text = ', '.join(formatted_reasons) if formatted_reasons else '사유 없음'
                        who = f"{display_name}({session_abbr})" if session_abbr else display_name
                        label = f"{who} - {reason_text}"
                        slot_reasons.setdefault(str(slot), set()).add(label)

            if slot_reasons:
                per_date[d_str] = {k: sorted(v) for k, v in slot_reasons.items()}
            date_cursor += datetime.timedelta(days=1)

        song_conflict_map[str(song.id)] = {
            'member_count': len(song_member_map[str(song.id)]),
            'members': song_member_map[str(song.id)],
            'data': per_date,
        }

    return song_conflict_map, song_member_map


def get_time_str(index):
    """ 18 -> "09:00" 변환 """
    hour = index // 2
    minute = (index % 2) * 30
    return f"{hour:02d}:{minute:02d}"

def _group_indices_to_ranges(indices):
    """
    [Internal Helper] [18, 19, 21] -> [(18, 20), (21, 22)] 변환 로직
    """
    if not indices:
        return []

    indices = sorted(list(map(int, indices)))
    ranges = []

    start = indices[0]
    prev = start

    for x in indices[1:]:
        if x == prev + 1:
            prev = x
        else:
            ranges.append((start, prev + 1))
            start = x
            prev = x
    ranges.append((start, prev + 1))

    return ranges


def sync_song_sessions(song, new_needed_list, new_extra_str):
    """
    [Service] 곡 수정 시, 입력된 세션 목록에 맞춰 기존 세션을 삭제하거나 생성함
    """
    # 1. 입력값 정리
    # new_extra_str: "Vocal2, Chorus" (문자열) -> ["Vocal2", "Chorus"] (리스트)
    new_extra_list = [name.strip() for name in new_extra_str.split(',') if name.strip()]

    # 전체 목표 세션 이름 리스트 (필수 + 추가)
    all_target_names = set(new_needed_list + new_extra_list)

    # 2. 기존 세션 가져오기 (DB)
    current_sessions = {s.name: s for s in song.sessions.all()}

    # 3. 삭제 (Delete): 기존에는 있었는데 목표에는 없는 것
    for name, session in current_sessions.items():
        if name not in all_target_names:
            # (주의) 이미 사람이 배정된 세션이라면 삭제를 막거나 알림을 주는 로직을
            # 나중에 여기에 추가할 수도 있음. 지금은 쿨하게 삭제.
            session.delete()

    # 4. 생성/수정 (Create/Update): 목표에 있는 것 처리
    for name in all_target_names:
        is_extra = (name in new_extra_list)  # 이게 추가 세션인지 판단

        if name not in current_sessions:
            # 없으면 새로 생성
            Session.objects.create(song=song, name=name, is_extra=is_extra)
        else:
            # 있으면 is_extra 속성만 최신화 (옵션)
            session = current_sessions[name]
            if session.is_extra != is_extra:
                session.is_extra = is_extra
                session.save()


def clear_recurring_data(user, start_date, end_date):
    """
    [Helper] 특정 기간 내의 고정 스케줄을 '단순 삭제'합니다.
    (Strict Mode: 겹치는 기간 생성을 원천 봉쇄했으므로, 수정 시에는 해당 기간만 깔끔하게 지우면 됩니다.)
    """
    RecurringBlock.objects.filter(
        user=user,
        start_date__lte=end_date,
        end_date__gte=start_date
    ).delete()


def save_recurring_data(user, data, start_date, end_date, additional_periods=None):
    """
    [Data Saver] 청소 후 저장
    """
    # 1. 해당 기간 데이터 클리어
    clear_recurring_data(user, start_date, end_date)

    # 2. 새 데이터 입력
    for day_idx, blocks in data.items():
        for block in blocks:
            RecurringBlock.objects.create(
                user=user,
                day_of_week=int(day_idx),
                start_index=block['start'],
                end_index=block['end'],
                reason=block['reason'],
                start_date=start_date,
                end_date=end_date
            )

    # 3. 특정 기간 추가 고정 일정 저장
    for period in (additional_periods or []):
        p_start_raw = period.get('start_date')
        p_end_raw = period.get('end_date')
        period_data = period.get('data') or {}
        if not p_start_raw or not p_end_raw:
            continue
        try:
            p_start = datetime.datetime.strptime(str(p_start_raw), "%Y-%m-%d").date()
            p_end = datetime.datetime.strptime(str(p_end_raw), "%Y-%m-%d").date()
        except Exception:
            continue

        # 현재 편집 범위 밖/역전 기간은 무시
        if p_start > p_end:
            continue
        if p_start < start_date or p_end > end_date:
            continue

        for day_idx, blocks in period_data.items():
            for block in blocks:
                RecurringBlock.objects.create(
                    user=user,
                    day_of_week=int(day_idx),
                    start_index=block['start'],
                    end_index=block['end'],
                    reason=block['reason'],
                    start_date=p_start,
                    end_date=p_end
                )


def load_recurring_data(user, start_date=None, end_date=None):
    """
    [Data Loader] 유저의 고정 스케줄을 요일별 딕셔너리로 반환
    기간(start_date, end_date)이 주어지면, 그 기간에 유효한 스케줄만 필터링함.
    """
    data = {}
    blocks = RecurringBlock.objects.filter(user=user)

    # 1. 기간이 주어졌다면 필터링 (핵심!)
    # 조금만 걸쳐져있어도 일단 가져오는데 나중에 가공할 예정
    if start_date and end_date:
        blocks = blocks.filter(
            start_date__lte=end_date,
            end_date__gte=start_date
        )

    for block in blocks:
        if block.day_of_week not in data:
            data[block.day_of_week] = []

        data[block.day_of_week].append({
            'start': block.start_index,
            'end': block.end_index,
            'reason': block.reason,
            # 날짜 정보도 같이 담아주면 나중에 계산할 때 편함
            'start_date': block.start_date,
            'end_date': block.end_date
        })

    return data


def save_oneoff_data(user, data, start_date, end_date):
    """
    [Data Saver] 단발성 스케줄 저장
    :param oneoff_data: { "2026-02-14": [{"start":..., "reason":...}], ... }
    """
    # 1. 해당 기간 내 기존 데이터 삭제
    OneOffBlock.objects.filter(
        user=user,
        date__range=[start_date, end_date],
        is_generated=False,
    ).delete()

    # 2. 새 데이터 생성
    for date_str, blocks in data.items():
        for block in blocks:
            OneOffBlock.objects.create(
                user=user,
                date=date_str,
                start_index=block['start'],
                end_index=block['end'],
                reason=block['reason'],
                is_generated=False,
            )


def load_oneoff_data(user, start_date, end_date, include_generated=False):
    """
    [Data Loader] 기간 내 단발성 스케줄을 날짜별(str) 딕셔너리로 반환
    Returns: { '2026-02-14': [{'start': 18, 'end': 22, 'reason': '병원'}], ... }
    """
    data = {}
    blocks = OneOffBlock.objects.filter(user=user, date__range=[start_date, end_date])
    if not include_generated:
        blocks = blocks.filter(is_generated=False)
    for block in blocks:
        d_str = block.date.strftime('%Y-%m-%d')
        if d_str not in data:
            data[d_str] = []
        data[d_str].append({
            'start': block.start_index,
            'end': block.end_index,
            'reason': block.reason,
            'is_generated': bool(block.is_generated),
        })
    return data


def save_exception_data(user, data, start_date, end_date):
    """
    [Data Saver] 예외 데이터 저장
    지원 형식:
    - 구형: { '2026-02-14': [18, 19, 20], ... }
    - 신형: { '2026-02-14': { 'slots': [...], 'targeted': [{start,end,target{...}}] }, ... }
    """
    # 1. 기존 데이터 삭제 (덮어쓰기 전략)
    RecurringException.objects.filter(
        user=user,
        date__range=[start_date, end_date]
    ).delete()

    # 2. 새 데이터 저장
    for date_str, day_payload in data.items():
        normalized = _normalize_exception_day_payload(day_payload)
        indexes = normalized['slots']
        targeted = normalized['targeted']

        if not indexes and not targeted:
            continue

        if indexes:
            ranges = _group_indices_to_ranges(indexes)

            for r_start, r_end in ranges:
                RecurringException.objects.create(
                    user=user,
                    date=date_str,
                    start_index=r_start,
                    end_index=r_end,
                    reason='취소',
                    target_payload={},
                )

        for t in targeted:
            try:
                t_start = int(t.get('start'))
                t_end = int(t.get('end'))
            except (TypeError, ValueError):
                continue
            if t_end <= t_start:
                continue
            target = t.get('target') or {}
            if not isinstance(target, dict) or not target:
                continue
            RecurringException.objects.create(
                user=user,
                date=date_str,
                start_index=t_start,
                end_index=t_end,
                reason='취소',
                target_payload=target,
            )


def load_exception_data(user, start_date, end_date):
    """
    [Data Loader] 기간 내 예외(취소) 데이터를 날짜별 payload로 반환
    Returns: {
      '2026-02-14': {
        'slots': [18,19],
        'targeted': [{'start':18,'end':22,'target': {...}}]
      }
    }
    """
    data = {}
    excs = RecurringException.objects.filter(user=user, date__range=[start_date, end_date])
    for e in excs:
        d_str = e.date.strftime('%Y-%m-%d')

        if d_str not in data:
            data[d_str] = {'slots': [], 'targeted': []}

        target_payload = e.target_payload or {}
        if isinstance(target_payload, dict) and target_payload:
            data[d_str]['targeted'].append({
                'start': int(e.start_index),
                'end': int(e.end_index),
                'target': target_payload,
            })
        else:
            data[d_str]['slots'].extend(range(e.start_index, e.end_index))
    return data


def prepare_edit(user, start_str, end_str):
    """
    [Service] 수정 모드 진입을 위해 DB 데이터를 세션용 포맷(JSON 호환)으로 변환하여 반환
    """
    import json  # 여기서만 필요하면 안에서 import 해도 됨

    # 1. 날짜 변환
    s_date = datetime.datetime.strptime(start_str, "%Y-%m-%d").date()
    e_date = datetime.datetime.strptime(end_str, "%Y-%m-%d").date()

    # 2. 데이터 로드 (우리가 만든 로더 재사용)
    rec_data = load_recurring_data(user, s_date, e_date)
    one_data = load_oneoff_data(user, s_date, e_date)
    exc_data = load_exception_data(user, s_date, e_date)

    base_data = {}
    additional_grouped = {}
    for day_idx, blocks in rec_data.items():
        for block in blocks:
            b_start = block.get('start_date')
            b_end = block.get('end_date')
            target = base_data
            group_key = None
            if b_start != s_date or b_end != e_date:
                group_key = (str(b_start), str(b_end))
                if group_key not in additional_grouped:
                    additional_grouped[group_key] = {}
                target = additional_grouped[group_key]

            day_key = str(day_idx)
            if day_key not in target:
                target[day_key] = []
            target[day_key].append({
                'start': block.get('start'),
                'end': block.get('end'),
                'reason': block.get('reason'),
            })

    additional_periods = []
    for (p_start, p_end), period_data in additional_grouped.items():
        additional_periods.append({
            'start_date': p_start,
            'end_date': p_end,
            'data': period_data,
        })

    # 3. 세션에 넣기 좋게 포장 (JSON 직렬화)
    # 딕셔너리를 통째로 만들어서 리턴합니다.
    return {
        'schedule_start': start_str,
        'schedule_end': end_str,
        'temp_recurring': json.loads(json.dumps(base_data, default=str)),
        'temp_recurring_additional': json.loads(json.dumps(additional_periods, default=str)),
        'temp_oneoff': json.loads(json.dumps(one_data, default=str)),
        'temp_exceptions': json.loads(json.dumps(exc_data, default=str)),
    }


def calculate_user_schedule(user, start_date, end_date, session_exceptions=None, include_generated_oneoff=False):
    """
    User의 고정, 단발, 예외 일정을 모두 합쳐서
    날짜별 '가능한 시간 인덱스 리스트'를 반환하는 핵심 함수
    """
    # 1. DB 데이터 로드
    recurring_blocks = RecurringBlock.objects.filter(user=user, start_date__lte=end_date, end_date__gte=start_date)
    oneoff_data = load_oneoff_data(user, start_date, end_date, include_generated=include_generated_oneoff)
    if session_exceptions is not None:
        exceptions_map = session_exceptions
    else:
        exceptions_map = load_exception_data(user, start_date, end_date)

    # 2. 날짜별 계산
    result = {}  # { "2026-02-14": [18, 19, 20...] }
    curr = start_date

    while curr <= end_date:
        curr_str = curr.strftime("%Y-%m-%d")
        day_idx = curr.weekday()

        # 기본값: 09:00(18) ~ 24:00(48) 모두 가능
        available_slots = set(range(18, 48))

        day_exceptions = _normalize_exception_day_payload(exceptions_map.get(curr_str, []))

        # (A) 고정 빼기 (해당 블록에 매칭되는 예외만 적용)
        for block in recurring_blocks:
            if block.day_of_week == day_idx:
                block_start = block.start_date or start_date
                block_end = block.end_date or end_date
                if block_start <= curr <= block_end:
                    scope_start = block_start.strftime('%Y-%m-%d')
                    scope_end = block_end.strftime('%Y-%m-%d')
                    for i in range(block.start_index, block.end_index):
                        if _is_block_slot_cancelled(
                            i,
                            day_exceptions,
                            block_day=block.day_of_week,
                            block_start=block.start_index,
                            block_end=block.end_index,
                            block_reason=block.reason,
                            block_scope_start=scope_start,
                            block_scope_end=scope_end,
                        ):
                            continue
                        available_slots.discard(i)

        # (B) 단발 빼기
        if curr_str in oneoff_data:
            for block in oneoff_data[curr_str]:
                for i in range(block['start'], block['end']): available_slots.discard(i)

        result[curr_str] = sorted(list(available_slots))
        curr += timedelta(days=1)

    return result


def confirm_and_save_schedule(user, start_date, end_date):
    """
    [Saver] 최종 스케줄을 계산하여 MemberAvailability에 저장
    (이미 앞 단계에서 예외/단발성 데이터가 DB에 저장되었으므로 session_exceptions 불필요)
    """
    # 1. 최종 계산 (이미 있는 함수 활용)
    final_schedule = calculate_user_schedule(user, start_date, end_date)

    # 2. DB 저장 (Update or Create)
    for d_str, slots in final_schedule.items():
        MemberAvailability.objects.update_or_create(
            user=user,
            date=d_str,
            defaults={'available_slot': slots}
        )


def get_schedule_summary(rec_map, one_map, exc_map, additional_periods=None):
    """
    [Unified Display] 세션(또는 딕셔너리 형태) 데이터를 받아서
    화면(Template)에 뿌리기 좋은 형태로 가공하여 반환
    """
    DAYS_MAP = ['월', '화', '수', '목', '금', '토', '일']

    additional_periods = additional_periods or []

    def _format_period_kor(start_str, end_str):
        s_date = datetime.datetime.strptime(start_str, "%Y-%m-%d").date()
        e_date = datetime.datetime.strptime(end_str, "%Y-%m-%d").date()
        sy = str(s_date.year)[-2:]
        ey = str(e_date.year)[-2:]
        start_text = f"{sy}년 {s_date.month}월 {s_date.day}일"
        if s_date.year == e_date.year:
            return f"{start_text} ~ {e_date.month}월 {e_date.day}일"
        return f"{start_text} ~ {ey}년 {e_date.month}월 {e_date.day}일"

    # 1. 기본 고정 스케줄 가공
    fixed_grouped = []
    # 키 정렬 (문자열 '0' -> 정수 0)
    sorted_days = sorted(rec_map.keys(), key=lambda x: int(x))

    for day_idx in sorted_days:
        blocks = rec_map[day_idx]
        if not blocks: continue

        # 시간순 정렬
        blocks.sort(key=lambda x: x['start'])

        day_schedules = []
        for b in blocks:
            day_schedules.append({
                'reason': b['reason'],
                'time_str': f"{get_time_str(b['start'])} ~ {get_time_str(b['end'])}"
            })

        fixed_grouped.append({
            'day_str': DAYS_MAP[int(day_idx)],
            'items': day_schedules
        })

    # 1-2. 특수 기간 고정 스케줄 가공
    special_period_grouped = []
    for period in additional_periods:
        p_start = str(period.get('start_date') or '').strip()
        p_end = str(period.get('end_date') or '').strip()
        p_data = period.get('data') or {}
        if not p_start or not p_end or not isinstance(p_data, dict):
            continue

        grouped_days = []
        for day_key in sorted(p_data.keys(), key=lambda x: int(x)):
            blocks = p_data.get(day_key) or []
            if not blocks:
                continue
            blocks = sorted(blocks, key=lambda x: x.get('start', 0))
            items = []
            for b in blocks:
                items.append({
                    'reason': b.get('reason') or '고정 일정',
                    'time_str': f"{get_time_str(b['start'])} ~ {get_time_str(b['end'])}"
                })
            grouped_days.append({
                'day_str': DAYS_MAP[int(day_key)],
                'items': items,
            })

        if grouped_days:
            special_period_grouped.append({
                'period_text': _format_period_kor(p_start, p_end),
                'days': grouped_days,
            })

    # 2. 예외/추가 스케줄 가공
    all_exceptions = []

    # (A) 추가된 일정 (OneOff)
    for date_str, blocks in one_map.items():
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        for b in blocks:
            all_exceptions.append({
                'type': 'added',
                'date': dt,
                'day_str': DAYS_MAP[dt.weekday()],
                'start_time': get_time_str(b['start']),
                'end_time': get_time_str(b['end']),
                'reason': b['reason']
            })

    # (B) 취소된 일정 (Exception)
    for date_str, day_payload in exc_map.items():
        normalized = _normalize_exception_day_payload(day_payload)
        indices = normalized['slots']
        targeted = normalized['targeted']
        if not indices and not targeted:
            continue
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        day_idx = dt.weekday()
        day_blocks = list(rec_map.get(str(day_idx), rec_map.get(day_idx, [])) or [])

        # 취소 날짜에 해당하는 특수 기간 고정 스케줄도 포함
        for period in additional_periods:
            p_start = str(period.get('start_date') or '').strip()
            p_end = str(period.get('end_date') or '').strip()
            p_data = period.get('data') or {}
            if not p_start or not p_end or not isinstance(p_data, dict):
                continue
            if p_start <= date_str <= p_end:
                day_blocks.extend(p_data.get(str(day_idx), []) or [])

        # 취소 대상 날짜의 "원래 고정 일정" 슬롯별 사유 맵
        slot_reason_map = {}
        for block in day_blocks:
            reason = str(block.get('reason') or '').strip() or '고정 일정'
            start_idx = int(block.get('start', 0))
            end_idx = int(block.get('end', start_idx))
            for slot in range(start_idx, end_idx):
                slot_reason_map[slot] = reason

        if indices:
            ranges = _group_indices_to_ranges(indices)
            for r_start, r_end in ranges:
                reasons = []
                for slot in range(r_start, r_end):
                    rs = slot_reason_map.get(slot)
                    if rs and rs not in reasons:
                        reasons.append(rs)
                reason_text = ', '.join(reasons) if reasons else '고정 일정'

                all_exceptions.append({
                    'type': 'cancelled',
                    'date': dt,
                    'day_str': DAYS_MAP[dt.weekday()],
                    'start_time': get_time_str(r_start),
                    'end_time': get_time_str(r_end),
                    'reason': reason_text
                })

        for t in targeted:
            try:
                t_start = int(t.get('start'))
                t_end = int(t.get('end'))
            except (TypeError, ValueError):
                continue
            target = t.get('target') or {}
            target_reason = str(target.get('reason') or '').strip() or '고정 일정'
            all_exceptions.append({
                'type': 'cancelled',
                'date': dt,
                'day_str': DAYS_MAP[dt.weekday()],
                'start_time': get_time_str(t_start),
                'end_time': get_time_str(t_end),
                'reason': target_reason
            })

    # [수정 전] 날짜로만 정렬 (순서 보장 안 됨)
    # all_exceptions.sort(key=lambda x: x['date'])

    # [수정 후] 3단 정렬 (날짜 -> 타입 -> 시간)
    all_exceptions.sort(key=lambda x: (
        x['date'],  # 1순위: 날짜가 빠를수록 먼저
        0 if x['type'] == 'cancelled' else 1,  # 2순위: 'added'는 0점, 나머지는 1점 (0이 먼저 나옴!)
        x['start_time']  # 3순위: 같은 타입이면 시간 빠른 순
    ))

    return fixed_grouped, special_period_grouped, all_exceptions


def get_confirmation_summaryandshuldbeupdated(user, start_date, end_date, session_data=None):
    """
    [Display Loader] 확인 페이지용 데이터 가공 (고정, 추가, 취소 목록)
    """
    DAYS_MAP = ['월', '화', '수', '목', '금', '토', '일']

    # 1. 고정 스케줄 (Fixed)
    recurring_qs = RecurringBlock.objects.filter(user=user).order_by('day_of_week', 'start_index')
    fixed_display = []
    for block in recurring_qs:
        fixed_display.append({
            'day_str': DAYS_MAP[block.day_of_week],
            'start_time': get_time_str(block.start_index),
            'end_time': get_time_str(block.end_index),
            'reason': block.reason,
            'day_idx': block.day_of_week,  # 아래 계산용
            'start_idx': block.start_index,  # 아래 계산용
            'end_idx': block.end_index  # 아래 계산용
        })

    # 2. 추가된 일정 (Added - OneOff)
    oneoff_qs = OneOffBlock.objects.filter(user=user, date__range=[start_date, end_date])
    added_display = []
    for block in oneoff_qs:
        added_display.append({
            'type': 'added',
            'date': block.date,
            'day_str': DAYS_MAP[block.date.weekday()],
            'start_time': get_time_str(block.start_index),
            'end_time': get_time_str(block.end_index),
            'reason': block.reason
        })

    # 3. 취소된 일정 (Cancelled - Exception)
    # RecurringException 모델이 이미 start/end를 가지고 있으므로 복잡한 재조립 로직 제거 가능
    exc_qs = RecurringException.objects.filter(user=user, date__range=[start_date, end_date])
    cancelled_display = []

    for exc in exc_qs:
        day_idx = exc.date.weekday()

        # 원본 사유 찾기 (겹치는 고정 스케줄 찾기)
        reason_found = "고정 일정"
        for r_block in fixed_display:
            if r_block['day_idx'] == day_idx:
                # 겹침 판별: (A_start < B_end) and (A_end > B_start)
                if exc.start_index < r_block['end_idx'] and exc.end_index > r_block['start_idx']:
                    reason_found = r_block['reason']
                    break

        cancelled_display.append({
            'type': 'cancelled',
            'date': exc.date,
            'day_str': DAYS_MAP[day_idx],
            'start_time': get_time_str(exc.start_index),
            'end_time': get_time_str(exc.end_index),
            'reason': reason_found
        })

    # 4. 합치고 정렬 (날짜순 -> 타입순 -> 시간순)
    all_exceptions = added_display + cancelled_display
    all_exceptions.sort(key=lambda x: (x['date'], 0 if x['type'] != 'added' else 1, x.get('start_time', '')))

    return fixed_display, all_exceptions


def get_busy_events(user, start_date, end_date):
    busy_data = {}

    # 1. 데이터 로드
    recurring_map = load_recurring_data(user, start_date, end_date)
    oneoff_map = load_oneoff_data(user, start_date, end_date, include_generated=True)
    exception_map = load_exception_data(user, start_date, end_date)

    # 2. 날짜별 순회
    curr = start_date
    while curr <= end_date:
        d_str = curr.strftime('%Y-%m-%d')
        day_idx = curr.weekday()
        daily_events = []

        # (A) 고정 스케줄 처리 (날짜 유효성 체크 추가!)
        if day_idx in recurring_map:
            day_exceptions = _normalize_exception_day_payload(exception_map.get(d_str, []))

            for r_block in recurring_map[day_idx]:
                # ★ 유효 기간 체크 로직 (New!)
                # DB에 날짜가 없으면(None) 항상 유효한 것으로 간주(or 사용)
                block_start = r_block.get('start_date') or start_date
                block_end = r_block.get('end_date') or end_date

                # 현재 날짜(curr)가 유효 기간 안에 있을 때만 추가
                if block_start <= curr <= block_end:
                    block_scope_start = block_start.strftime('%Y-%m-%d') if hasattr(block_start, 'strftime') else str(block_start)
                    block_scope_end = block_end.strftime('%Y-%m-%d') if hasattr(block_end, 'strftime') else str(block_end)
                    block_exception_slots = set()
                    for slot in range(r_block['start'], r_block['end']):
                        if _is_block_slot_cancelled(
                            slot,
                            day_exceptions,
                            block_day=day_idx,
                            block_start=r_block['start'],
                            block_end=r_block['end'],
                            block_reason=r_block.get('reason'),
                            block_scope_start=block_scope_start,
                            block_scope_end=block_scope_end,
                        ):
                            block_exception_slots.add(slot)
                    split_events = _apply_exception_to_block(r_block, block_exception_slots)
                    daily_events.extend(split_events)

        # (B) 단발성 스케줄 처리 (기존 동일)
        if d_str in oneoff_map:
            daily_events.extend([
                {**item, 'type': ('rehearsal' if item.get('is_generated') else 'oneoff')}
                for item in oneoff_map[d_str]
            ])

        if daily_events:
            busy_data[d_str] = daily_events

        curr += datetime.timedelta(days=1)

    return busy_data


def sync_generated_oneoff_for_meeting(meeting):
    """
    meeting의 PracticeSchedule을 기준으로 멤버별 generated OneOffBlock을 동기화
    """
    schedules = PracticeSchedule.objects.filter(meeting=meeting).select_related('song')

    rows = []
    for sch in schedules:
        assignee_ids = set(
            sch.song.sessions.filter(assignee__isnull=False).values_list('assignee_id', flat=True)
        )
        reason = f"합주:{sch.song.title}"[:30]
        for uid in assignee_ids:
            rows.append(OneOffBlock(
                user_id=uid,
                date=sch.date,
                start_index=sch.start_index,
                end_index=sch.end_index,
                reason=reason,
                is_generated=True,
                source_meeting=meeting,
                source_song=sch.song,
            ))

    with transaction.atomic():
        OneOffBlock.objects.filter(source_meeting=meeting, is_generated=True).delete()
        if rows:
            OneOffBlock.objects.bulk_create(rows)


def _apply_exception_to_block(block, exception_slots):
    """
    [Internal Helper] 고정 블록(Start~End)에서 예외(Exception) 시간을 제외하고
    쪼개진 이벤트 리스트를 반환함.
    """
    # 예외가 없으면 그냥 원본 리턴 (성능 최적화)
    if not exception_slots:
        return [{'start': block['start'], 'end': block['end'], 'reason': block['reason'], 'type': 'recurring'}]

    # 1. 블록을 낱개 슬롯으로 분해 (18~21 -> 18, 19, 20)
    valid_slots = []
    for s in range(block['start'], block['end']):
        if s not in exception_slots:
            valid_slots.append(s)

    if not valid_slots:
        return []

    # 2. 다시 덩어리(Range)로 묶기
    valid_slots.sort()
    merged_events = []

    start = valid_slots[0]
    prev = start

    for s in valid_slots[1:]:
        if s == prev + 1:
            prev = s
        else:
            merged_events.append({
                'start': start, 'end': prev + 1,
                'reason': block['reason'], 'type': 'recurring'
            })
            start = s
            prev = s

    # 마지막 덩어리 추가
    merged_events.append({
        'start': start, 'end': prev + 1,
        'reason': block['reason'], 'type': 'recurring'
    })

    return merged_events


def analyze_song_schedule(song, valid_rooms, start_date, end_date):
    """
    [Helper] 특정 곡의 멤버들과 합주실 상황을 고려하여 '합주 가능 슬롯'을 추출
    """
    active_sessions = song.sessions.filter(assignee__isnull=False)
    users = [s.assignee for s in active_sessions]

    if not users:
        return {'status': 'error', 'message': '배정된 멤버 없음'}

    available_map = _get_multi_room_intersection(users, valid_rooms, start_date, end_date)
    total_count = sum(len(v) for v in available_map.values())

    if total_count > 0:
        return {'status': 'success', 'available': available_map}
    else:
        return {'status': 'error', 'message': '공통 가능 시간 없음'}


def _get_multi_room_intersection(users, rooms, start_date, end_date):
    """
    [Internal] Users의 공통 시간 AND Rooms 중 하나라도 빈 시간
    """
    common_schedule = {}  # { "2026-03-01": [18, 19] }

    # 1. 멤버 데이터 로드
    user_avails = {}
    for u in users:
        qs = MemberAvailability.objects.filter(user=u, date__range=[start_date, end_date])
        u_map = {}
        for a in qs:
            d_str = a.date.strftime('%Y-%m-%d')
            u_map[d_str] = set(a.available_slot)
        user_avails[u.id] = u_map

    # 2. 룸 Busy 데이터 로드
    room_busy = {}
    for r in rooms:
        blocks = RoomBlock.objects.filter(room=r, date__range=[start_date, end_date])
        r_map = defaultdict(set)
        for b in blocks:
            d_str = b.date.strftime('%Y-%m-%d')
            for i in range(b.start_index, b.end_index):
                r_map[d_str].add(i)
        room_busy[r.id] = r_map

    # 3. 날짜 순회
    curr = start_date
    while curr <= end_date:
        d_str = curr.strftime('%Y-%m-%d')

        # (A) 멤버 교집합
        daily_common = set(range(18, 48))  # 09:00 ~ 24:00
        for u in users:
            u_slots = user_avails.get(u.id, {}).get(d_str, set())
            daily_common &= u_slots
            if not daily_common: break

        # (B) 룸 가용성 (OR)
        final_slots = set()
        if daily_common:
            for t in daily_common:
                # 이 시간 t에 대해, 차단되지 않은 방이 하나라도 있는가?
                for r in rooms:
                    if t not in room_busy[r.id].get(d_str, set()):
                        final_slots.add(t)
                        break

        if final_slots:
            common_schedule[d_str] = sorted(list(final_slots))

        curr += timedelta(days=1)

    return common_schedule


def auto_schedule_match(
    meeting,
    duration_minutes,
    required_count,
    priority_order=None,
    allowed_room_ids=None,
    preferred_room_ids=None,
    exclude_weekends=False,
    room_efficiency_priority=False,
    maximize_feasibility=False,
    hour_start_only=False,
    time_limit_start=18,
    time_limit_end=48,
    song_ids=None,
):
    """
    [Main] 주차별 합주 시간 자동 매칭
    """
    if song_ids is not None:
        songs = meeting.songs.filter(id__in=song_ids)
    else:
        songs = meeting.songs.all()
    all_rooms = list(PracticeRoom.objects.filter(band=meeting.band, is_temporary=False))
    if allowed_room_ids is not None:
        allowed_set = {str(x) for x in allowed_room_ids}
        all_rooms = [r for r in all_rooms if str(r.id) in allowed_set]
    if preferred_room_ids and not maximize_feasibility:
        pref_ids = [str(x) for x in preferred_room_ids]
        rank_map = {rid: idx for idx, rid in enumerate(pref_ids)}
        all_rooms.sort(key=lambda r: (rank_map.get(str(r.id), 10 ** 6), r.name))
    elif maximize_feasibility:
        # 배치 가능성 최우선: 큰 방을 아껴 쓰기 위해 수용 인원 작은 방부터 사용
        all_rooms.sort(key=lambda r: (int(r.capacity or 0), r.name))
    else:
        all_rooms.sort(key=lambda r: r.name)
    room_preference_rank = {str(r.id): idx for idx, r in enumerate(all_rooms)}
    start_date = meeting.practice_start_date
    end_date = meeting.practice_end_date

    # 1. 기본 유효성 검사
    if not all_rooms or not start_date or not end_date:
        return {'status': 'error', 'message': '설정 오류: 합주실 또는 기간을 확인해주세요.'}
    # 같은 곡 연속 구간의 방 전환 억제 강도(soft penalty).
    # 하드 제약(중복/점유/정원)은 그대로 우선한다.
    SAME_SONG_ROOM_SWITCH_WEIGHT = 8

    # 슬롯 수 계산 (30분 단위)
    slots_needed = int(duration_minutes // 30)
    if slots_needed < 1: slots_needed = 1
    time_limit_start = max(18, min(47, int(time_limit_start)))
    time_limit_end = max(19, min(48, int(time_limit_end)))
    if time_limit_start >= time_limit_end:
        time_limit_start, time_limit_end = 18, 48

    # 2. 주차(Week) 범위 계산
    # [(week1_start, week1_end), (week2_start, week2_end), ...]
    week_ranges = []
    curr = start_date
    while curr <= end_date:
        # 일요일까지를 한 주차로 끊음
        days_until_sunday = 6 - curr.weekday()
        w_end = curr + timedelta(days=days_until_sunday)
        if w_end > end_date:
            w_end = end_date
        week_ranges.append((curr, w_end))
        curr = w_end + timedelta(days=1)

    # 3. 실시간 점유 현황판 (Runtime Busy Map)
    # 알고리즘이 곡 A를 월요일 10시에 배정했다면, 
    # 곡 B(같은 멤버 존재)는 월요일 10시에 배정하면 안 됨.
    # 구조: runtime_busy[date_str][slot_idx] = set([user_id1, user_id2, ..., 'room_1'])
    runtime_busy = defaultdict(lambda: defaultdict(set))
    room_busy_slots = defaultdict(lambda: defaultdict(set))  # {date: {room_id: {slot...}}}
    member_room_slots = defaultdict(lambda: defaultdict(dict))  # {date: {slot: {user_id: room_id}}}

    # (A-0) 합주실 자체 불가 시간(RoomBlock) 선반영
    room_blocks = RoomBlock.objects.filter(
        room_id__in=[r.id for r in all_rooms],
        date__range=[start_date, end_date]
    )
    for block in room_blocks:
        d_str = block.date.strftime('%Y-%m-%d')
        rid = block.room_id
        for t in range(block.start_index, block.end_index):
            runtime_busy[d_str][t].add(f'room_{rid}')
            room_busy_slots[d_str][rid].add(t)

    # (A) DB에 이미 저장된 스케줄(확정된 것들) 로딩
    overlapping_meeting_ids = list(
        meeting.band.meetings.filter(
            Q(practice_start_date__isnull=True)
            | Q(practice_end_date__isnull=True)
            | (
                Q(practice_start_date__lte=end_date)
                & Q(practice_end_date__gte=start_date)
            )
        ).values_list('id', flat=True)
    )
    existing_schedules = PracticeSchedule.objects.filter(
        meeting_id__in=overlapping_meeting_ids,
        date__range=[start_date, end_date]
    )
    for sch in existing_schedules:
        d_str = sch.date.strftime('%Y-%m-%d')
        # 해당 스케줄의 멤버들 가져오기
        active_members = [s.assignee.id for s in sch.song.sessions.filter(assignee__isnull=False)]

        for t in range(sch.start_index, sch.end_index):
            runtime_busy[d_str][t].add(f'room_{sch.room.id}')
            runtime_busy[d_str][t].update(active_members)
            room_busy_slots[d_str][sch.room.id].add(t)
            for uid in active_members:
                member_room_slots[d_str][t][uid] = sch.room.id

    # 4. 매칭 시작
    final_schedule = []
    failed_songs = []

    # 곡별 분석 (헬퍼 함수 사용) - 분석은 한 번만 수행
    song_analysis_map = {}
    for song in songs:
        # 멤버가 꽉 찼는지 확인하거나, 있는 멤버끼리라도 진행
        member_cnt = song.sessions.filter(assignee__isnull=False).count()
        if member_cnt == 0:
            failed_songs.append({'song': song, 'reason': '멤버 없음'})
            continue

        valid_rooms = [r for r in all_rooms if r.capacity >= member_cnt]
        if not valid_rooms:
            failed_songs.append({'song': song, 'reason': '수용 가능한 합주실 없음'})
            continue

        # 여기서 헬퍼 함수 호출! (DB 조회)
        analysis = analyze_song_schedule(song, valid_rooms, start_date, end_date)

        # 멤버 ID 집합 (중복 체크용)
        m_ids = set(s.assignee.id for s in song.sessions.filter(assignee__isnull=False))

        song_analysis_map[song.id] = {
            'obj': song,
            'analysis': analysis,
            'members': m_ids,
            'rooms': valid_rooms
        }

    def _time_score(slot_idx):
        # 18:00(36) 이후: 거리 그대로 (18:00=0, 18:30=1, ...)
        # 18:00 이전: 큰 페널티 + 거리 (17:30=101, 17:00=102, ...)
        if slot_idx >= 36:
            return slot_idx - 36
        return 100 + (36 - slot_idx)

    def _day_priority(date_str):
        # 평일 우선(0), 주말 후순위(1)
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        return 0 if d.weekday() < 5 else 1

    valid_priority_keys = ['continuity', 'member_continuity', 'weekday', 'time_pref']
    if maximize_feasibility:
        normalized_priority_order = []
    else:
        if not priority_order:
            normalized_priority_order = valid_priority_keys.copy()
        else:
            normalized_priority_order = [k for k in priority_order if k in valid_priority_keys]
            if not normalized_priority_order:
                normalized_priority_order = valid_priority_keys.copy()

    def _member_continuity_priority(candidate_date, candidate_start, members):
        """
        이 곡의 멤버가 직전/직후 슬롯에 다른 곡으로 이미 배정된 수를 최대화.
        → 한 번 왔을 때 연속으로 합주할 수 있도록 인접 배치 우선.
        0: 멤버 전원이 인접 슬롯에 있음 (최우선)
        len(members): 인접 멤버 없음
        참고: 합주실이 달라도 연속으로 배치되므로 이동 부담이 있을 수 있음.
        """
        if not members:
            return 0
        adj_before = candidate_start - 1
        adj_after = candidate_start + slots_needed
        before_count = len(members & runtime_busy[candidate_date][adj_before])
        after_count = len(members & runtime_busy[candidate_date][adj_after])
        return len(members) - max(before_count, after_count)

    def _priority_tuple(candidate_date, candidate_start, selected_ranges, members=frozenset()):
        values = []
        for key in normalized_priority_order:
            if key == 'continuity':
                values.append(_continuity_priority(candidate_date, candidate_start, selected_ranges))
            elif key == 'member_continuity':
                values.append(_member_continuity_priority(candidate_date, candidate_start, members))
            elif key == 'weekday':
                values.append(_day_priority(candidate_date))
            elif key == 'time_pref':
                values.append(_time_score(candidate_start))
        return tuple(values)

    def _candidate_count_from_source(source_map):
        count = 0
        for _, slots in source_map.items():
            if not slots:
                continue
            ordered = sorted(slots)
            for i in range(len(ordered) - slots_needed + 1):
                chunk = ordered[i:i + slots_needed]
                if chunk[-1] - chunk[0] != slots_needed - 1:
                    continue
                if hour_start_only and chunk[0] % 2 != 0:
                    continue
                if chunk[0] < time_limit_start or (chunk[0] + slots_needed) > time_limit_end:
                    continue
                count += 1
        return count

    def _continuity_priority(candidate_date, candidate_start, selected_ranges):
        """
        같은 주차에서 이미 배치된 슬롯들과의 연속성 점수
        0: 같은 날짜에서 바로 앞/뒤로 연속
        1: 같은 날짜
        2: 그 외
        """
        if not selected_ranges:
            return 2

        same_day = [r for r in selected_ranges if r['date'] == candidate_date]
        if not same_day:
            return 2

        for r in same_day:
            if candidate_start == r['end'] or (candidate_start + slots_needed) == r['start']:
                return 0
        return 1

    def _ranges_overlap(a_start, a_end, b_start, b_end):
        return a_start < b_end and a_end > b_start

    def _pick_room_for_slot(d_str, start_slot, temp_assignments, members, rooms):
        """
        runtime_busy + temp_assignments 기준으로 가능한 첫 방 선택
        """
        end_slot = start_slot + slots_needed
        slot_range = range(start_slot, end_slot)

        # 멤버 충돌 (기존 확정/다른 곡 배정과의 충돌)
        for t in slot_range:
            if not runtime_busy[d_str][t].isdisjoint(members):
                return None

        # 같은 곡 내 임시 선택끼리 겹치지 않도록 방어
        for a in temp_assignments:
            if a['date'] == d_str and _ranges_overlap(start_slot, end_slot, a['start'], a['end']):
                return None

        def _added_booking_block_count(room_id):
            # 후보 배치로 인해 "연속 예약 구간(예약 건수)"이 얼마나 늘어나는지 계산
            # 예) [24,25,26,27]은 1건, [24,25,28,29]는 2건
            current_slots = set(room_busy_slots[d_str][room_id])
            for a in temp_assignments:
                if a['room'].id == room_id and a['date'] == d_str:
                    current_slots.update(range(a['start'], a['end']))
            target_slots = set(range(start_slot, end_slot))

            def _segment_count(slot_set):
                if not slot_set:
                    return 0
                ordered = sorted(int(s) for s in slot_set)
                seg = 1
                prev = ordered[0]
                for s in ordered[1:]:
                    if s != prev + 1:
                        seg += 1
                    prev = s
                return seg

            before = _segment_count(current_slots)
            after = _segment_count(current_slots | target_slots)
            return max(0, after - before)

        def _adjacent_room_switch_penalty(room_id):
            """
            인접 슬롯(직전/직후)에 같은 멤버가 다른 방에 배정되어 있으면 페널티.
            방 이동 동선을 줄이기 위한 tie-breaker 용도.
            """
            penalty = 0
            before_slot = start_slot - 1
            after_slot = end_slot
            for uid in members:
                prev_room = member_room_slots[d_str].get(before_slot, {}).get(uid)
                if prev_room and prev_room != room_id:
                    penalty += 1
                next_room = member_room_slots[d_str].get(after_slot, {}).get(uid)
                if next_room and next_room != room_id:
                    penalty += 1

            # 같은 곡의 임시 배정(같은 주차 탐색 중)에서도 인접 구간은 같은 방을 선호
            for a in temp_assignments:
                if a.get('date') != d_str:
                    continue
                if a.get('end') == start_slot or a.get('start') == end_slot:
                    a_room = getattr(a.get('room'), 'id', None)
                    if a_room is not None and a_room != room_id:
                        penalty += max(1, len(members))
            return penalty

        def _same_song_room_switch_penalty(room_id):
            """
            현재 곡의 같은 날짜 인접 구간(직전/직후)과 방이 다르면 강한 페널티.
            - 제약(충돌/점유) 통과 후에만 비교되는 soft penalty.
            - 방 연속성을 우선하되, 불가능하면 다른 방을 선택하도록 한다.
            """
            penalty = 0
            for a in temp_assignments:
                if a.get('date') != d_str:
                    continue
                if not (a.get('end') == start_slot or a.get('start') == end_slot):
                    continue
                a_room = getattr(a.get('room'), 'id', None)
                if a_room is None:
                    continue
                if str(a_room) != str(room_id):
                    penalty += SAME_SONG_ROOM_SWITCH_WEIGHT
            return penalty

        def _room_usage_compaction_penalty(room_id):
            """
            예약 효율 우선 모드에서, 후보 시간대의 인접 구간(직전/직후)에
            이미 사용 중인 방을 재사용하도록 유도한다.
            같은 날짜 전체가 아니라 "인접 구간" 중심으로 방 종류 수를 줄인다.
            """
            if not room_efficiency_priority:
                return 0
            used_room_ids = set()
            near_start = max(time_limit_start, start_slot - 1)
            near_end = min(time_limit_end, end_slot + 1)
            near_slots = set(range(near_start, near_end))
            if not near_slots:
                return 0
            for rid, slots in room_busy_slots[d_str].items():
                if set(slots) & near_slots:
                    used_room_ids.add(str(rid))
            for a in temp_assignments:
                if a.get('date') == d_str and a.get('room') is not None:
                    a_start = int(a.get('start', 0))
                    a_end = int(a.get('end', a_start + 1))
                    # 인접 또는 겹침 구간만 포함
                    if a_end >= near_start and a_start <= near_end:
                        used_room_ids.add(str(a['room'].id))
            if not used_room_ids:
                return 0
            return 0 if str(room_id) in used_room_ids else 1

        candidates = []
        for r in rooms:
            room_ok = True
            for t in slot_range:
                if t in room_busy_slots[d_str][r.id]:
                    room_ok = False
                    break
            if not room_ok:
                continue

            for a in temp_assignments:
                if a['room'].id != r.id or a['date'] != d_str:
                    continue
                if _ranges_overlap(start_slot, end_slot, a['start'], a['end']):
                    room_ok = False
                    break

            if room_ok:
                candidates.append(r)

        if not candidates:
            return None
        if maximize_feasibility:
            candidates.sort(key=lambda r: (
                _same_song_room_switch_penalty(r.id),
                _adjacent_room_switch_penalty(r.id),
                int(r.capacity or 0),
                _added_booking_block_count(r.id),
                r.name,
            ))
        elif room_efficiency_priority:
            candidates.sort(key=lambda r: (
                _same_song_room_switch_penalty(r.id),
                _adjacent_room_switch_penalty(r.id),
                _room_usage_compaction_penalty(r.id),
                room_preference_rank.get(str(r.id), 10 ** 6),
                _added_booking_block_count(r.id),
                r.name,
            ))
        else:
            candidates.sort(key=lambda r: (
                _same_song_room_switch_penalty(r.id),
                _adjacent_room_switch_penalty(r.id),
                room_preference_rank.get(str(r.id), 10 ** 6),
                _added_booking_block_count(r.id),
                _room_usage_compaction_penalty(r.id),
                r.name,
            ))
        return candidates[0]

    def _find_contiguous_same_day_pattern(week_candidates, members, rooms, need_count):
        """
        같은 날짜에서 need_count회가 slots_needed 간격으로 연속되는 패턴 우선 탐색
        """
        by_day = defaultdict(set)
        for d_str, s in week_candidates:
            by_day[d_str].add(s)

        best = None
        for d_str in sorted(by_day.keys()):
            starts = sorted(by_day[d_str])
            start_set = set(starts)
            for s0 in starts:
                seq = [s0 + (k * slots_needed) for k in range(need_count)]
                if not all(x in start_set for x in seq):
                    continue

                tmp = []
                ok = True
                for s in seq:
                    r = _pick_room_for_slot(d_str, s, tmp, members, rooms)
                    if not r:
                        ok = False
                        break
                    tmp.append({
                        'date': d_str,
                        'start': s,
                        'end': s + slots_needed,
                        'room': r
                    })
                if not ok:
                    continue

                score = _priority_tuple(d_str, s0, [], members)
                if best is None or score < best[0]:
                    best = (score, tmp)
        return best[1] if best else None

    def _find_compact_same_day_pattern(week_candidates, members, rooms, need_count):
        """
        완전 연속이 없을 때 같은 날짜에서 gap 최소 조합 탐색
        """
        by_day = defaultdict(list)
        for d_str, s in week_candidates:
            by_day[d_str].append(s)

        best = None
        for d_str in sorted(by_day.keys()):
            starts = sorted(set(by_day[d_str]))
            if len(starts) < need_count:
                continue

            comb = []

            def dfs(idx):
                nonlocal best
                if len(comb) == need_count:
                    tmp = []
                    for s in comb:
                        r = _pick_room_for_slot(d_str, s, tmp, members, rooms)
                        if not r:
                            return
                        tmp.append({
                            'date': d_str,
                            'start': s,
                            'end': s + slots_needed,
                            'room': r
                        })

                    gap_sum = 0
                    for i in range(1, len(comb)):
                        gap_sum += max(0, comb[i] - comb[i - 1] - slots_needed)
                    score = (
                        gap_sum,
                        *_priority_tuple(d_str, comb[0], [], members),
                        d_str,
                        comb[0]
                    )
                    if best is None or score < best[0]:
                        best = (score, tmp)
                    return

                remain_need = need_count - len(comb)
                if idx > len(starts) - remain_need:
                    return

                for i in range(idx, len(starts)):
                    s = starts[i]
                    if comb and s < comb[-1] + slots_needed:
                        continue
                    comb.append(s)
                    dfs(i + 1)
                    comb.pop()

            dfs(0)
        return best[1] if best else None

    # 5. 배치 가능한 경우의 수가 가장 적은 곡부터 정렬
    ordered_song_items = []
    for _, item in song_analysis_map.items():
        analysis = item['analysis']
        source_map = {}
        if analysis['status'] == 'success':
            source_map = analysis.get('available', {})
        item['candidate_count'] = _candidate_count_from_source(source_map) if source_map else 0
        ordered_song_items.append(item)

    ordered_song_items.sort(key=lambda x: (x.get('candidate_count', 0), x['obj'].title))

    # 6. 주차별 순회 및 배정
    for item in ordered_song_items:
        song = item['obj']
        analysis = item['analysis']
        members = item['members']
        rooms = item['rooms']

        # 분석 결과 가용 시간이 없으면 실패 처리
        if analysis['status'] != 'success':
            failed_songs.append({'song': song, 'reason': analysis.get('message', '분석 실패')})
            continue

        # 주차별로 체크
        failed_weeks = []

        for w_idx, (w_start, w_end) in enumerate(week_ranges):
            w_start_str = w_start.strftime('%Y-%m-%d')
            w_end_str = w_end.strftime('%Y-%m-%d')

            # 이번 주차 배정 횟수 체크
            scheduled_count = 0

            week_candidates = []  # (date_str, start_slot)
            source_map = analysis['available']

            # 날짜 필터링 및 연속 슬롯 확인
            all_week_candidates = []  # 정시/반시 모두 포함
            for d_str, slots in source_map.items():
                if w_start_str <= d_str <= w_end_str:
                    if exclude_weekends:
                        d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
                        if d_obj.weekday() >= 5:
                            continue
                    # 연속 슬롯 찾기
                    if not slots: continue
                    slots.sort()
                    for i in range(len(slots) - slots_needed + 1):
                        # 연속성 체크 (예: 18, 19, 20 ...)
                        chunk = slots[i: i + slots_needed]
                        if chunk[-1] - chunk[0] == slots_needed - 1:
                            if chunk[0] < time_limit_start or (chunk[0] + slots_needed) > time_limit_end:
                                continue
                            all_week_candidates.append((d_str, chunk[0]))  # 시작점 저장

            # 1차 후보: 설정을 우선 반영
            if hour_start_only:
                week_candidates = [c for c in all_week_candidates if c[1] % 2 == 0]
            else:
                week_candidates = list(all_week_candidates)

            # (B) 후보군 중에서 '실시간 중복' 없는 슬롯 찾기
            assigned_in_week = 0
            selected_in_week = []

            # (B-0) 같은 날 연속/압축 패턴 우선 배정
            if (not maximize_feasibility) and required_count > 1 and week_candidates:
                pattern = _find_contiguous_same_day_pattern(week_candidates, members, rooms, required_count)
                if pattern is None:
                    pattern = _find_compact_same_day_pattern(week_candidates, members, rooms, required_count)

                if pattern:
                    for p in pattern:
                        final_schedule.append({
                            'song': song,
                            'song_title': song.title,
                            'room': p['room'],
                            'date': p['date'],
                            'start': p['start'],
                            'end': p['end'],
                            'is_fixed': False,
                        })

                        for t in range(p['start'], p['end']):
                            runtime_busy[p['date']][t].add(f"room_{p['room'].id}")
                            runtime_busy[p['date']][t].update(members)
                            room_busy_slots[p['date']][p['room'].id].add(t)
                            for uid in members:
                                member_room_slots[p['date']][t][uid] = p['room'].id

                        selected_in_week.append({
                            'date': p['date'],
                            'start': p['start'],
                            'end': p['end'],
                            'room': p['room'],
                        })
                        assigned_in_week += 1

                    # 동일 시작점 중복 방지
                    used = {(p['date'], p['start']) for p in pattern}
                    week_candidates = [c for c in week_candidates if c not in used]

            # 패턴 배정만으로 주간 횟수 충족 시 다음 주차로
            if assigned_in_week >= required_count:
                continue

            # 남은 횟수만큼 단건 그리디 배정
            for _ in range(required_count - assigned_in_week):
                best_slot = None
                best_room = None
                best_score = None

                def _same_song_adjacent_room_switch_penalty(d_str, start_slot, room_obj):
                    """
                    같은 곡의 주차 내 인접 배치(직전/직후)와 방이 달라지면 페널티.
                    외부 점유로 연속이 끊긴 경우에도 가능한 한 같은 방으로 이어붙이도록 유도.
                    """
                    if room_obj is None:
                        return 0
                    room_id = str(getattr(room_obj, 'id', '') or '')
                    end_slot = start_slot + slots_needed
                    penalty = 0
                    for r in selected_in_week:
                        if r.get('date') != d_str:
                            continue
                        if r.get('end') == start_slot or r.get('start') == end_slot:
                            prev_room = str(getattr(r.get('room'), 'id', '') or '')
                            if prev_room and prev_room != room_id:
                                penalty += SAME_SONG_ROOM_SWITCH_WEIGHT
                    return penalty

                for d_str, start_slot in week_candidates:
                    # 슬롯 범위
                    slot_range = range(start_slot, start_slot + slots_needed)

                    # 1. 멤버 중복 체크
                    member_conflict = False
                    for t in slot_range:
                        if not runtime_busy[d_str][t].isdisjoint(members):
                            member_conflict = True
                            break
                    if member_conflict: continue

                    # 2. 룸 가용 여부 및 선택
                    target_room = _pick_room_for_slot(d_str, start_slot, selected_in_week, members, rooms)

                    if target_room:
                        score = (
                            _same_song_adjacent_room_switch_penalty(d_str, start_slot, target_room),
                            *_priority_tuple(d_str, start_slot, selected_in_week, members),
                            d_str,
                            start_slot,
                            room_preference_rank.get(str(target_room.id), 10 ** 6),
                        )
                        if best_score is None or score < best_score:
                            best_score = score
                            best_slot = (d_str, start_slot)
                            best_room = target_room

                if best_slot:
                    # 배정 확정
                    d_str, s_idx = best_slot

                    final_schedule.append({
                        'song': song,
                        'song_title': song.title,
                        'room': best_room,
                        'date': d_str,
                        'start': s_idx,
                        'end': s_idx + slots_needed,
                        'is_fixed': False,
                    })

                    # Runtime Busy 업데이트
                    for k in range(slots_needed):
                        t = s_idx + k
                        runtime_busy[d_str][t].add(f'room_{best_room.id}')
                        runtime_busy[d_str][t].update(members)
                        room_busy_slots[d_str][best_room.id].add(t)
                        for uid in members:
                            member_room_slots[d_str][t][uid] = best_room.id

                    # 같은 주차 내에서 방금 쓴 시간은 후보군에서 제거 (재사용 불가)
                    week_candidates = [c for c in week_candidates if not (c[0] == d_str and c[1] == s_idx)]
                    selected_in_week.append({
                        'date': d_str,
                        'start': s_idx,
                        'end': s_idx + slots_needed,
                        'room': best_room,
                    })
                    assigned_in_week += 1
                else:
                    break  # 더 이상 배정 불가

            if assigned_in_week < required_count:
                failed_weeks.append(f"{w_idx + 1}주차")

        # 주차별 배정이 모두 끝난 후 실패 여부 기록
        if failed_weeks:
            failed_songs.append({
                'song': song,
                'reason': f"시간 부족 ({', '.join(failed_weeks)} 실패)"
            })

    # 7. 안전 후처리: 같은 곡 연속 구간 방 끊김 완화 (제약 유지)
    # - 중복/점유/정원 제약을 절대 깨지 않는 범위에서만
    #   같은 슬롯 내 단순 이동 또는 1:1 room swap을 시도한다.
    if final_schedule:
        room_blocks_by_room_date = defaultdict(set)  # {(room_id, date_str): {slot...}}
        rb_qs = RoomBlock.objects.filter(
            room_id__in=[r.id for r in all_rooms],
            date__range=[start_date, end_date]
        )
        for rb in rb_qs:
            d_key = rb.date.strftime('%Y-%m-%d')
            key = (str(rb.room_id), d_key)
            for t in range(rb.start_index, rb.end_index):
                room_blocks_by_room_date[key].add(t)

        song_member_count = {}
        song_user_ids_map = defaultdict(set)
        for s in songs:
            assignee_ids = set(
                s.sessions.filter(assignee__isnull=False).values_list('assignee_id', flat=True)
            )
            song_member_count[s.id] = len(assignee_ids)
            song_user_ids_map[s.id] = assignee_ids

        def _event_room_conflict(idx, target_room_id, exclude_indices=None):
            exclude = set(exclude_indices or set())
            ev = final_schedule[idx]
            d_str = str(ev.get('date') or '')
            s_idx = int(ev.get('start', 0))
            e_idx = int(ev.get('end', s_idx + 1))

            blocked = room_blocks_by_room_date.get((str(target_room_id), d_str), set())
            for t in range(s_idx, e_idx):
                if t in blocked:
                    return True

            for j, other in enumerate(final_schedule):
                if j == idx or j in exclude:
                    continue
                if str(other.get('date') or '') != d_str:
                    continue
                other_room_id = str(getattr(other.get('room'), 'id', '') or '')
                if other_room_id != str(target_room_id):
                    continue
                os = int(other.get('start', 0))
                oe = int(other.get('end', os + 1))
                if s_idx < oe and e_idx > os:
                    return True
            return False

        def _event_member_conflict(idx, target_room_id=None, exclude_indices=None):
            exclude = set(exclude_indices or set())
            ev = final_schedule[idx]
            d_str = str(ev.get('date') or '')
            s_idx = int(ev.get('start', 0))
            e_idx = int(ev.get('end', s_idx + 1))
            song_obj = ev.get('song')
            if not song_obj:
                return False
            my_users = set(song_user_ids_map.get(song_obj.id, set()))
            if not my_users:
                return False
            for j, other in enumerate(final_schedule):
                if j == idx or j in exclude:
                    continue
                if str(other.get('date') or '') != d_str:
                    continue
                os = int(other.get('start', 0))
                oe = int(other.get('end', os + 1))
                if not (s_idx < oe and e_idx > os):
                    continue
                other_song = other.get('song')
                if not other_song:
                    continue
                other_users = set(song_user_ids_map.get(other_song.id, set()))
                if not my_users.isdisjoint(other_users):
                    return True
            return False

        def _event_capacity_conflict(idx, target_room_obj):
            if target_room_obj is None:
                return True
            ev = final_schedule[idx]
            song_obj = ev.get('song')
            if not song_obj:
                return False
            need = int(song_member_count.get(song_obj.id, 0) or 0)
            cap = int(getattr(target_room_obj, 'capacity', 0) or 0)
            return cap > 0 and need > cap

        def _can_reassign_event(idx, target_room_obj, exclude_indices=None):
            if target_room_obj is None:
                return False
            target_room_id = str(getattr(target_room_obj, 'id', '') or '')
            if not target_room_id:
                return False
            if _event_room_conflict(idx, target_room_id, exclude_indices=exclude_indices):
                return False
            if _event_member_conflict(idx, target_room_id, exclude_indices=exclude_indices):
                return False
            if _event_capacity_conflict(idx, target_room_obj):
                return False
            return True

        def _contiguous_target_room_id(idx):
            ev = final_schedule[idx]
            song_obj = ev.get('song')
            if not song_obj:
                return ''
            d_str = str(ev.get('date') or '')
            s_idx = int(ev.get('start', 0))
            e_idx = int(ev.get('end', s_idx + 1))
            same_song = []
            for j, other in enumerate(final_schedule):
                if j == idx:
                    continue
                if str(other.get('date') or '') != d_str:
                    continue
                other_song = other.get('song')
                if not other_song or other_song.id != song_obj.id:
                    continue
                os = int(other.get('start', 0))
                oe = int(other.get('end', os + 1))
                if oe == s_idx or os == e_idx:
                    same_song.append(other)
            if not same_song:
                return ''
            same_song.sort(key=lambda x: (
                room_preference_rank.get(str(getattr(x.get('room'), 'id', '') or ''), 10 ** 6),
                int(x.get('start', 0)),
            ))
            return str(getattr(same_song[0].get('room'), 'id', '') or '')

        max_swap_pass = 3
        for _ in range(max_swap_pass):
            changed = False
            for idx, ev in enumerate(final_schedule):
                target_room_id = _contiguous_target_room_id(idx)
                if not target_room_id:
                    continue
                current_room_obj = ev.get('room')
                current_room_id = str(getattr(current_room_obj, 'id', '') or '')
                if not current_room_id or current_room_id == target_room_id:
                    continue
                target_room_obj = next((r for r in all_rooms if str(r.id) == str(target_room_id)), None)
                if target_room_obj is None:
                    continue

                # 1) 단순 이동 시도
                if _can_reassign_event(idx, target_room_obj):
                    final_schedule[idx]['room'] = target_room_obj
                    changed = True
                    continue

                # 2) 동일 시간대 1:1 swap 시도
                d_str = str(ev.get('date') or '')
                s_idx = int(ev.get('start', 0))
                e_idx = int(ev.get('end', s_idx + 1))
                blockers = []
                for j, other in enumerate(final_schedule):
                    if j == idx:
                        continue
                    if str(other.get('date') or '') != d_str:
                        continue
                    other_room_id = str(getattr(other.get('room'), 'id', '') or '')
                    if other_room_id != target_room_id:
                        continue
                    os = int(other.get('start', 0))
                    oe = int(other.get('end', os + 1))
                    if s_idx < oe and e_idx > os:
                        blockers.append(j)
                if len(blockers) != 1:
                    continue
                b_idx = blockers[0]
                blocker_room_obj = final_schedule[b_idx].get('room')
                if blocker_room_obj is None:
                    continue
                if str(getattr(blocker_room_obj, 'id', '') or '') != target_room_id:
                    continue

                # blocker를 내 현재 방으로 보낼 수 있는지 검사
                current_room_obj = next((r for r in all_rooms if str(r.id) == current_room_id), current_room_obj)
                if current_room_obj is None:
                    continue
                if not _can_reassign_event(b_idx, current_room_obj, exclude_indices={idx}):
                    continue
                if not _can_reassign_event(idx, target_room_obj, exclude_indices={b_idx}):
                    continue

                final_schedule[b_idx]['room'] = current_room_obj
                final_schedule[idx]['room'] = target_room_obj
                changed = True
            if not changed:
                break

    # 8. 후처리(편의성): 같은 곡 연속 구간 방 통일/방 변경 최소화
    # 중복/점유 안정성을 최우선할 때는 후처리 재배치를 끈다.
    conservative_dedup_priority = True
    if final_schedule and (not conservative_dedup_priority):
        room_blocks_by_room_date = defaultdict(set)  # {(room_id, date_str): {slot...}}
        rb_qs = RoomBlock.objects.filter(
            room_id__in=[r.id for r in all_rooms],
            date__range=[start_date, end_date]
        )
        for rb in rb_qs:
            d_key = rb.date.strftime('%Y-%m-%d')
            key = (str(rb.room_id), d_key)
            for t in range(rb.start_index, rb.end_index):
                room_blocks_by_room_date[key].add(t)

        song_member_count = {}
        for s in songs:
            song_member_count[s.id] = s.sessions.filter(assignee__isnull=False).count()

        def _is_room_available_for_event(room_id, d_str, s_idx, e_idx, exclude_indices):
            blocked = room_blocks_by_room_date.get((room_id, d_str), set())
            for t in range(s_idx, e_idx):
                if t in blocked:
                    return False
            for idx, other in enumerate(final_schedule):
                if idx in exclude_indices:
                    continue
                if str(other.get('date')) != d_str:
                    continue
                if str(getattr(other.get('room'), 'id', '') or '') != str(room_id):
                    continue
                os = int(other.get('start', 0))
                oe = int(other.get('end', os + 1))
                if s_idx < oe and e_idx > os:
                    return False
            return True

        grouped = defaultdict(list)  # {(song_id, date_str): [index...]}
        for idx, ev in enumerate(final_schedule):
            song_obj = ev.get('song')
            if not song_obj:
                continue
            grouped[(song_obj.id, str(ev.get('date')))].append(idx)

        for (song_id, d_str), indices in grouped.items():
            if len(indices) < 2:
                continue
            indices.sort(key=lambda i: int(final_schedule[i].get('start', 0)))

            member_cnt = int(song_member_count.get(song_id, 0) or 0)
            candidate_rooms = [r for r in all_rooms if int(r.capacity or 0) >= member_cnt]
            if not candidate_rooms:
                continue

            i = 0
            while i < len(indices) - 1:
                chain = [indices[i]]
                j = i + 1
                while j < len(indices):
                    prev = final_schedule[chain[-1]]
                    curr = final_schedule[indices[j]]
                    prev_end = int(prev.get('end', int(prev.get('start', 0)) + 1))
                    curr_start = int(curr.get('start', 0))
                    if curr_start != prev_end:
                        break
                    chain.append(indices[j])
                    j += 1

                if len(chain) > 1:
                    current_room_id = str(getattr(final_schedule[chain[0]].get('room'), 'id', '') or '')
                    ordered_rooms = sorted(
                        candidate_rooms,
                        key=lambda r: (
                            room_preference_rank.get(str(r.id), 10 ** 6),
                            0 if str(r.id) == current_room_id else 1,
                            r.name,
                        )
                    )
                    for room in ordered_rooms:
                        rid = str(room.id)
                        can_apply = True
                        for idx in chain:
                            ev = final_schedule[idx]
                            s_idx = int(ev.get('start', 0))
                            e_idx = int(ev.get('end', s_idx + 1))
                            if not _is_room_available_for_event(rid, d_str, s_idx, e_idx, set(chain)):
                                can_apply = False
                                break
                        if can_apply:
                            for idx in chain:
                                final_schedule[idx]['room'] = room
                            break

                i = j

        # 7-2. 후처리: 곡별 방 변경 횟수 최소화(로컬 탐색)
        # 같은 곡의 전체 이벤트를 시간순으로 봤을 때 방 전환 횟수를 줄이되,
        # 기존 방 충돌/차단 제약은 절대 깨지 않도록 단일 이벤트 재배치만 수행한다.
        song_event_indices = defaultdict(list)  # {song_id: [event_idx...]}
        for idx, ev in enumerate(final_schedule):
            song_obj = ev.get('song')
            if song_obj:
                song_event_indices[song_obj.id].append(idx)

        def _song_room_switch_count(song_id):
            indices = list(song_event_indices.get(song_id, []))
            if len(indices) < 2:
                return 0
            indices.sort(key=lambda i: (
                str(final_schedule[i].get('date') or ''),
                int(final_schedule[i].get('start', 0)),
                int(final_schedule[i].get('end', 0)),
            ))
            switches = 0
            prev_room_id = None
            for i in indices:
                room_obj = final_schedule[i].get('room')
                rid = int(getattr(room_obj, 'id', 0) or 0)
                if prev_room_id is not None and rid != prev_room_id:
                    switches += 1
                prev_room_id = rid
            return switches

        room_candidates_by_song_id = {}
        for s in songs:
            member_cnt = int(song_member_count.get(s.id, 0) or 0)
            room_candidates_by_song_id[s.id] = [r for r in all_rooms if int(r.capacity or 0) >= member_cnt]

        max_pass = 5
        for _ in range(max_pass):
            improved_any = False
            event_order = list(range(len(final_schedule)))
            event_order.sort(key=lambda i: (
                str(final_schedule[i].get('date') or ''),
                int(final_schedule[i].get('start', 0)),
                int(final_schedule[i].get('end', 0)),
            ))

            for idx in event_order:
                ev = final_schedule[idx]
                song_obj = ev.get('song')
                if not song_obj:
                    continue
                s_id = song_obj.id
                candidates = room_candidates_by_song_id.get(s_id, [])
                if len(candidates) <= 1:
                    continue

                d_str = str(ev.get('date') or '')
                s_idx = int(ev.get('start', 0))
                e_idx = int(ev.get('end', s_idx + 1))
                current_room = ev.get('room')
                if current_room is None:
                    continue
                current_room_id = str(getattr(current_room, 'id', '') or '')
                current_score = _song_room_switch_count(s_id)
                best_score = current_score
                best_room = current_room
                best_pref_rank = room_preference_rank.get(current_room_id, 10 ** 6)

                for room in candidates:
                    rid = str(room.id)
                    if rid == current_room_id:
                        continue
                    if not _is_room_available_for_event(rid, d_str, s_idx, e_idx, {idx}):
                        continue

                    ev['room'] = room
                    trial_score = _song_room_switch_count(s_id)
                    ev['room'] = current_room
                    trial_pref_rank = room_preference_rank.get(rid, 10 ** 6)
                    if (trial_score < best_score) or (trial_score == best_score and trial_pref_rank < best_pref_rank):
                        best_score = trial_score
                        best_room = room
                        best_pref_rank = trial_pref_rank

                if str(getattr(best_room, 'id', '') or '') != current_room_id:
                    ev['room'] = best_room
                    improved_any = True

            if not improved_any:
                break

    # 9. 결과 반환 (날짜순 정렬)
    final_schedule.sort(key=lambda x: (x['date'], x['start']))

    return {
        'status': 'success',
        'schedule': final_schedule,
        'failed': failed_songs,
        'total_count': len(songs),
        'success_count': len(set(x['song'].id for x in final_schedule)),
    }

# group_schedule_by_week 등 하단 함수는 그대로 유지


def group_schedule_by_week(start_date, end_date, schedule_list):
    """
    [View Helper] 1줄짜리 리스트를 주차별로 그룹핑 (UI용)
    """
    weeks = []
    # 시작일이 속한 주의 월요일 찾기
    curr = start_date - timedelta(days=start_date.weekday())

    while curr <= end_date:
        week_end = curr + timedelta(days=6)

        # 이번 주 데이터 구조
        days_data = []
        for i in range(7):
            day_date = curr + timedelta(days=i)
            d_str = day_date.strftime('%Y-%m-%d')

            # 해당 날짜 이벤트 필터링
            events = [s for s in schedule_list if s['date'] == d_str]
            days_data.append({
                'date': day_date,
                'events': events
            })

        weeks.append({
            'start': curr,
            'end': week_end,
            'days': days_data
        })

        curr += timedelta(weeks=1)

    return weeks


# utils.py 맨 아래에 추가
# utils.py
