import csv
import datetime
import os
import random
from collections import Counter, defaultdict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from pracapp.models import (
    Band,
    Membership,
    MemberAvailability,
    Meeting,
    MeetingParticipant,
    OneOffBlock,
    RecurringBlock,
    RecurringException,
    Song,
    Session,
    PracticeSchedule,
)

User = get_user_model()


TOTAL_USERS = 60
USERNAME_PREFIX = "test"
PASSWORD = "0000"
BAND_NAME = "헤게모니"

# 60명 기준 악기 분포
REQUESTED_INSTRUMENT_COUNTS = {
    "Vocal": 11,
    "Guitar": 18,
    "Bass": 14,
    "Drum": 10,
    "Keyboard": 7,
}

# 30분 슬롯 인덱스 기준
# 09:00, 10:30, 12:00, 13:30, 15:00, 16:30
CLASS_START_INDICES = [18, 21, 24, 27, 30, 33]
CLASS_SLOTS = 3  # 1시간 15분을 30분 슬롯 체계에서 1시간 30분으로 근사

# 알바 시작 시각: 16:00이 대부분, 12:00은 종종
PART_TIME_START_CANDIDATES = [32, 24]  # 16:00, 12:00
PART_TIME_START_WEIGHTS = [0.75, 0.25]
PART_TIME_SLOTS = 8  # 4시간

# 가용시간 계산 범위(약 8주)
AVAIL_DAYS = 56

CLASS_REASON_KEYWORDS = ("수업", "강의")
ONEOFF_REASON_POOL_SHORT = [
    "팀플", "과제", "발표", "시험", "복습",
    "통학", "병원", "면접", "약속", "스터디",
    "세미나", "실험", "상담", "조모임", "모임",
]

APPLICATION_RANGE_BY_INSTRUMENT = {
    "Vocal": (3, 5),
    "Guitar": (4, 6),
    "Bass": (4, 5),
    "Drum": (4, 5),
    "Keyboard": (2, 3),
}

# 사용자 제공 이름 풀(남 40 + 여 40)
MALE_NAME_POOL_40 = [
    "김경석", "이태준", "박한섭", "최윤성", "정원탁", "조덕삼", "강희수", "윤봉식", "임철민", "한동우",
    "송재익", "오정식", "서진태", "신문수", "권태호", "유영필", "황치영", "안명보", "고기찬", "양덕수",
    "전병호", "홍성표", "백승한", "손기철", "조상현", "배용석", "남궁혁", "심재화", "노승우", "문철호",
    "하진구", "곽명석", "차두식", "지영준", "엄필수", "원용택", "채기호", "변성진", "주태환", "설인철",
]

FEMALE_NAME_POOL_40 = [
    "김옥순", "이정선", "박영숙", "최춘희", "정해숙", "조경애", "강금자", "윤혜순", "임복희", "한명옥",
    "송정자", "오말순", "서화자", "신덕예", "권보배", "유순남", "황점숙", "안인자", "고숙자", "양길순",
    "전정임", "홍귀남", "백연순", "손봉선", "조이분", "배순화", "남희수", "심정원", "노은옥", "문영자",
    "하금옥", "곽복순", "차귀례", "지옥분", "엄정애", "원갑숙", "채영희", "변춘자", "주선화", "설옥주",
]

ALL_NAME_POOL_80 = MALE_NAME_POOL_40 + FEMALE_NAME_POOL_40
# 요청: 여기서 60개 선택하여 더미 이름 교체
SELECTED_DUMMY_NAME_POOL_60 = MALE_NAME_POOL_40[:30] + FEMALE_NAME_POOL_40[:30]


def _scaled_instrument_counts(total_users: int, requested: dict[str, int]) -> dict[str, int]:
    requested_total = sum(requested.values())
    if requested_total == total_users:
        return requested.copy()

    scaled = {k: (v * total_users / requested_total) for k, v in requested.items()}
    floors = {k: int(v) for k, v in scaled.items()}
    remainder = total_users - sum(floors.values())

    # 큰 소수점부터 1명씩 배분
    ranked = sorted(scaled.items(), key=lambda x: x[1] - int(x[1]), reverse=True)
    for i in range(remainder):
        k = ranked[i][0]
        floors[k] += 1
    return floors


def _build_instrument_pool(counts: dict[str, int]) -> list[str]:
    pool: list[str] = []
    for inst, cnt in counts.items():
        pool.extend([inst] * cnt)
    random.shuffle(pool)
    return pool


def _apply_session_style_realtime_names(users: list[User]) -> None:
    """
    instrument 기준으로 realname을 Vocal1, Guitar1 ... 형식으로 통일
    (username 숫자 순으로 번호 부여)
    """
    def _u_num(u: User) -> int:
        digits = ''.join(ch for ch in u.username if ch.isdigit())
        return int(digits) if digits else 0

    counters = {
        "Vocal": 0,
        "Guitar": 0,
        "Bass": 0,
        "Drum": 0,
        "Keyboard": 0,
    }

    for user in sorted(users, key=_u_num):
        if user.instrument not in counters:
            continue
        counters[user.instrument] += 1
        user.realname = f"{user.instrument}{counters[user.instrument]}"
        user.save(update_fields=["realname"])


def _apply_human_dummy_names(users: list[User], name_pool: list[str]) -> None:
    """
    username 숫자 순으로 사용자 실명(한국어 이름) 부여.
    name_pool 길이보다 사용자가 많으면 순환한다.
    """
    if not users or not name_pool:
        return

    def _u_num(u: User) -> int:
        digits = ''.join(ch for ch in u.username if ch.isdigit())
        return int(digits) if digits else 0

    sorted_users = sorted(users, key=_u_num)
    n = len(name_pool)
    for idx, user in enumerate(sorted_users):
        user.realname = name_pool[idx % n]
        user.save(update_fields=["realname"])


def _non_overlapping_add(blocks: list[tuple[int, int]], start: int, end: int) -> bool:
    for s, e in blocks:
        if s < end and e > start:
            return False
    blocks.append((start, end))
    return True


def _add_non_overlapping_block(
    day_blocks: dict[int, list[tuple[int, int, str]]],
    day: int,
    start: int,
    end: int,
    reason: str,
) -> bool:
    ranges = [(s, e) for s, e, _ in day_blocks[day]]
    if not _non_overlapping_add(ranges, start, end):
        return False
    day_blocks[day].append((start, end, reason))
    return True


REASON_PRIORITY = {
    "수업": 1,
    "동아리활동": 2,
    "알바": 3,
}


def _resolve_day_blocks_with_priority(blocks: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """
    겹치는 블록이 있을 때 슬롯 단위로 우선순위를 적용해 정리한다.
    우선순위: 수업(1) > 동아리활동(2) > 알바(3)
    """
    if not blocks:
        return []

    slot_reason: dict[int, str] = {}
    for start, end, reason in blocks:
        for slot in range(start, end):
            if slot < 18 or slot >= 48:
                continue
            prev = slot_reason.get(slot)
            prev_pri = REASON_PRIORITY.get(prev, 99) if prev else 99
            cur_pri = REASON_PRIORITY.get(reason, 99)
            if prev is None or cur_pri < prev_pri:
                slot_reason[slot] = reason

    if not slot_reason:
        return []

    sorted_slots = sorted(slot_reason.keys())
    merged: list[tuple[int, int, str]] = []
    start = sorted_slots[0]
    prev = start
    reason = slot_reason[start]

    for slot in sorted_slots[1:]:
        current_reason = slot_reason[slot]
        if slot == prev + 1 and current_reason == reason:
            prev = slot
            continue
        merged.append((start, prev + 1, reason))
        start = slot
        prev = slot
        reason = current_reason

    merged.append((start, prev + 1, reason))
    return merged


def _create_weekly_schedule_for_user(user: User, start_date: datetime.date, end_date: datetime.date) -> None:
    # 기존 데이터 정리
    RecurringBlock.objects.filter(user=user).delete()
    OneOffBlock.objects.filter(user=user).delete()
    RecurringException.objects.filter(user=user).delete()
    MemberAvailability.objects.filter(user=user).delete()

    # weekday별 블록 임시 구조
    day_blocks: dict[int, list[tuple[int, int, str]]] = {d: [] for d in range(7)}

    # 1) 주중 수업 9개(월~금)
    classes_placed = 0
    attempts = 0
    while classes_placed < 9 and attempts < 300:
        attempts += 1
        day = random.randint(0, 4)  # 월~금
        start = random.choice(CLASS_START_INDICES)
        end = start + CLASS_SLOTS
        # 수업 시작 전 30분 버퍼 추가 (09:00 시작은 제외)
        buffered_start = start if start <= 18 else start - 1
        if _add_non_overlapping_block(day_blocks, day, buffered_start, end, "수업"):
            classes_placed += 1

    # 2) 알바 주 0~2회
    part_time_days = random.randint(0, 2)
    if part_time_days > 0:
        chosen_days = random.sample(range(7), k=part_time_days)
        for day in chosen_days:
            start = random.choices(PART_TIME_START_CANDIDATES, weights=PART_TIME_START_WEIGHTS, k=1)[0]
            end = start + PART_TIME_SLOTS
            _add_non_overlapping_block(day_blocks, day, start, end, "알바")

    # 우선순위 기반으로 겹침 정리 후 DB 저장
    for day, blocks in day_blocks.items():
        blocks = _resolve_day_blocks_with_priority(blocks)
        for s, e, reason in sorted(blocks, key=lambda x: x[0]):
            RecurringBlock.objects.create(
                user=user,
                day_of_week=day,
                start_index=s,
                end_index=e,
                reason=reason,
                start_date=start_date,
                end_date=end_date,
            )

    # MemberAvailability 동기화(Recurring + OneOff 반영)
    _sync_member_availability_from_blocks(user, start_date, end_date)


def _sync_member_availability_from_blocks(user: User, start_date: datetime.date, end_date: datetime.date) -> None:
    recurring = RecurringBlock.objects.filter(user=user, start_date__lte=end_date, end_date__gte=start_date)
    oneoff = OneOffBlock.objects.filter(user=user, date__range=[start_date, end_date], is_generated=False)
    curr = start_date
    full_slots = set(range(18, 48))  # 09:00~24:00
    oneoff_by_date: dict[datetime.date, list[tuple[int, int]]] = {}
    for ob in oneoff:
        oneoff_by_date.setdefault(ob.date, []).append((int(ob.start_index), int(ob.end_index)))
    while curr <= end_date:
        busy = set()
        day_idx = curr.weekday()
        for rb in recurring:
            if rb.day_of_week != day_idx:
                continue
            if rb.start_date <= curr <= rb.end_date:
                busy.update(range(rb.start_index, rb.end_index))
        for s, e in oneoff_by_date.get(curr, []):
            busy.update(range(s, e))
        available = sorted(list(full_slots - busy))
        MemberAvailability.objects.update_or_create(
            user=user,
            date=curr,
            defaults={"available_slot": available},
        )
        curr += datetime.timedelta(days=1)


def _apply_weekly_random_oneoff_rules(users: list[User], start_date: datetime.date, end_date: datetime.date) -> None:
    if not users or start_date > end_date:
        return

    current = start_date
    user_count = len(users)
    weekly_target_count = max(1, int(round(user_count * 0.7)))

    while current <= end_date:
        week_start = current
        week_end = min(end_date, week_start + datetime.timedelta(days=6))
        selected_users = random.sample(users, k=min(user_count, weekly_target_count))
        days_in_week = [week_start + datetime.timedelta(days=i) for i in range((week_end - week_start).days + 1)]
        recurring_by_user = defaultdict(list)
        recurring_qs = RecurringBlock.objects.filter(
            user__in=selected_users,
            start_date__lte=week_end,
            end_date__gte=week_start,
        )
        for rb in recurring_qs:
            recurring_by_user[rb.user_id].append(rb)

        existing_oneoff_by_user_date = defaultdict(lambda: defaultdict(set))
        oneoff_qs = OneOffBlock.objects.filter(
            user__in=selected_users,
            date__range=[week_start, week_end],
            is_generated=False,
        )
        for ob in oneoff_qs:
            for slot in range(int(ob.start_index), int(ob.end_index)):
                existing_oneoff_by_user_date[ob.user_id][ob.date].add(slot)

        base_busy_by_user_date = defaultdict(lambda: defaultdict(set))
        for user in selected_users:
            for d in days_in_week:
                day_busy = set(existing_oneoff_by_user_date[user.id].get(d, set()))
                w = d.weekday()
                for rb in recurring_by_user[user.id]:
                    if rb.day_of_week == w and rb.start_date <= d <= rb.end_date:
                        day_busy.update(range(int(rb.start_index), int(rb.end_index)))
                base_busy_by_user_date[user.id][d] = day_busy

        # 1) 대상자 선발 후, 일정 스펙(종일/시간, 사유) 먼저 생성
        plans = []
        for user in selected_users:
            reason = random.choice(ONEOFF_REASON_POOL_SHORT)[:5]
            if random.random() < 0.10:
                plans.append({
                    "user": user,
                    "all_day": True,
                    "duration_slots": 30,  # 09:00~24:00
                    "reason": reason,
                })
            else:
                plans.append({
                    "user": user,
                    "all_day": False,
                    "duration_slots": random.randint(1, 3) * 2,
                    "reason": reason,
                })

        # 2) 시간 배치: 겹치지 않을 때까지 주차 단위 재시도
        inserted_rows = None
        for _retry in range(180):
            busy_by_user_date = defaultdict(lambda: defaultdict(set))
            for uid, day_map in base_busy_by_user_date.items():
                for d, busy_slots in day_map.items():
                    busy_by_user_date[uid][d] = set(busy_slots)

            rows = []
            random.shuffle(plans)
            all_placed = True

            for plan in plans:
                user = plan["user"]
                reason = plan["reason"]
                duration_slots = int(plan["duration_slots"])
                assigned = None

                candidate_days = days_in_week[:]
                random.shuffle(candidate_days)

                if plan["all_day"]:
                    for d in candidate_days:
                        if not busy_by_user_date[user.id][d]:
                            assigned = (d, 18, 48)
                            break
                else:
                    for d in candidate_days:
                        busy = busy_by_user_date[user.id][d]
                        possible_starts = []
                        min_start = 18
                        max_start = 48 - duration_slots
                        for s in range(min_start, max_start + 1):
                            e = s + duration_slots
                            if any(slot in busy for slot in range(s, e)):
                                continue
                            possible_starts.append(s)
                        if possible_starts:
                            s = random.choice(possible_starts)
                            assigned = (d, s, s + duration_slots)
                            break

                if assigned is None:
                    all_placed = False
                    break

                d, s_idx, e_idx = assigned
                for slot in range(s_idx, e_idx):
                    busy_by_user_date[user.id][d].add(slot)
                rows.append((user, d, s_idx, e_idx, reason))

            if all_placed:
                inserted_rows = rows
                break

        if inserted_rows:
            OneOffBlock.objects.bulk_create([
                OneOffBlock(
                    user=row[0],
                    date=row[1],
                    start_index=row[2],
                    end_index=row[3],
                    reason=row[4],
                    is_generated=False,
                )
                for row in inserted_rows
            ])
        current = week_end + datetime.timedelta(days=1)


def _apply_class_buffer_to_existing_recurring(user: User) -> bool:
    changed = False
    rows = list(RecurringBlock.objects.filter(user=user))
    for rb in rows:
        reason = (rb.reason or '').strip()
        if not any(k in reason for k in CLASS_REASON_KEYWORDS):
            continue
        if rb.start_index <= 18:
            continue
        new_start = max(18, rb.start_index - 1)
        if new_start == rb.start_index:
            continue
        rb.start_index = new_start
        rb.save(update_fields=["start_index"])
        changed = True
    return changed


@transaction.atomic
def create_requested_dummy_users(seed: int = 42) -> None:
    random.seed(seed)
    today = datetime.date.today()
    start_date = today
    end_date = today + datetime.timedelta(days=AVAIL_DAYS)

    band, _ = Band.objects.get_or_create(name=BAND_NAME)

    scaled_counts = _scaled_instrument_counts(TOTAL_USERS, REQUESTED_INSTRUMENT_COUNTS)
    instrument_pool = _build_instrument_pool(scaled_counts)

    created_users: list[User] = []
    for i in range(1, TOTAL_USERS + 1):
        username = f"{USERNAME_PREFIX}{i}"
        instrument = instrument_pool[i - 1]

        user, _ = User.objects.get_or_create(username=username)
        user.realname = f"테스트유저{i}"
        user.instrument = instrument
        user.instrument_detail = ""
        user.is_active = True
        user.set_password(PASSWORD)
        user.save()

        membership, _ = Membership.objects.get_or_create(
            user=user,
            band=band,
            defaults={"role": "MEMBER", "is_approved": True},
        )
        if not membership.is_approved:
            membership.is_approved = True
            membership.save(update_fields=["is_approved"])

        created_users.append(user)

    # 밴드에 리더가 아무도 없으면 test1을 리더로 승격
    if not band.memberships.filter(role="LEADER", is_approved=True).exists():
        m = band.memberships.filter(user__username=f"{USERNAME_PREFIX}1").first()
        if m:
            m.role = "LEADER"
            m.is_approved = True
            m.save(update_fields=["role", "is_approved"])

    for user in created_users:
        _create_weekly_schedule_for_user(user, start_date, end_date)
    _apply_weekly_random_oneoff_rules(created_users, start_date, end_date)
    for user in created_users:
        _sync_member_availability_from_blocks(user, start_date, end_date)

    _apply_human_dummy_names(created_users, SELECTED_DUMMY_NAME_POOL_60)

    instrument_summary = Counter([u.instrument for u in created_users])
    print("✅ 더미 유저/스케줄 생성 완료")
    print(f"- 밴드: {band.name}")
    print(f"- 유저: {TOTAL_USERS}명 (id: test1~test{TOTAL_USERS}, pw: {PASSWORD})")
    print(f"- 생성 기간: {start_date} ~ {end_date}")
    print(f"- 악기 분포(보정): {dict(instrument_summary)}")
    print(f"- 요청 분포(원본): {REQUESTED_INSTRUMENT_COUNTS}")


@transaction.atomic
def apply_member_schedule_rules(
    band_name: str = BAND_NAME,
    seed: int = 20260222,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> None:
    """
    기존 멤버 스케줄에 규칙을 후처리 반영.
    1) 수업 시작 전 30분 버퍼 추가(09:00 제외)
    2) 주차별 랜덤 oneoff 생성
    3) MemberAvailability 재계산
    """
    random.seed(seed)
    band = Band.objects.get(name=band_name)
    users = list(
        User.objects.filter(
            user_memberships__band=band,
            user_memberships__is_approved=True,
        ).distinct()
    )
    if not users:
        print("ℹ️ 적용할 멤버가 없습니다.")
        return

    if start_date is None or end_date is None:
        recurring_qs = RecurringBlock.objects.filter(user__in=users)
        if recurring_qs.exists():
            start_date = start_date or recurring_qs.order_by("start_date").first().start_date
            end_date = end_date or recurring_qs.order_by("-end_date").first().end_date
        else:
            today = datetime.date.today()
            start_date = start_date or today
            end_date = end_date or (today + datetime.timedelta(days=AVAIL_DAYS))

    changed_users = 0
    for user in users:
        if _apply_class_buffer_to_existing_recurring(user):
            changed_users += 1

    OneOffBlock.objects.filter(
        user__in=users,
        date__range=[start_date, end_date],
        is_generated=False,
    ).delete()
    _apply_weekly_random_oneoff_rules(users, start_date, end_date)
    for user in users:
        _sync_member_availability_from_blocks(user, start_date, end_date)

    print("✅ 멤버 스케줄 규칙 반영 완료")
    print(f"- 밴드: {band_name}")
    print(f"- 대상 멤버: {len(users)}명")
    print(f"- 수업 버퍼 반영 멤버: {changed_users}명")
    print(f"- 기간: {start_date} ~ {end_date}")


def _session_matches_instrument(session_name: str, instrument: str) -> bool:
    name = session_name.strip().lower()
    if instrument == "Vocal":
        return name == "vocal"
    if instrument == "Guitar":
        return name.startswith("guitar")
    if instrument == "Bass":
        return name == "bass"
    if instrument == "Drum":
        return name == "drum"
    if instrument == "Keyboard":
        return name == "keyboard"
    return False


@transaction.atomic
def apply_test_users_to_meeting_applications(meeting_id: str | None = None, seed: int = 99) -> None:
    random.seed(seed)
    band = Band.objects.get(name=BAND_NAME)

    if meeting_id:
        meeting = Meeting.objects.get(id=meeting_id, band=band)
    else:
        meeting = band.meetings.order_by("-created_at").first()
        if not meeting:
            raise ValueError("헤게모니 밴드에 meeting이 없습니다.")

    songs = list(meeting.songs.prefetch_related("sessions").all())
    if not songs:
        raise ValueError("해당 meeting에 곡이 없습니다.")

    test_users = list(
        User.objects.filter(username__regex=r"^test([1-9]|1[0-5])$")
        .order_by("username")
    )
    if not test_users:
        raise ValueError("test1~test15 유저가 없습니다. 먼저 create_requested_dummy_users()를 실행하세요.")

    # 해당 meeting에서 test 유저들의 기존 지원 초기화
    for s in Session.objects.filter(song__meeting=meeting):
        s.applicant.remove(*test_users)

    applied_counter: dict[str, int] = {}

    for user in test_users:
        inst = user.instrument
        if inst not in APPLICATION_RANGE_BY_INSTRUMENT:
            continue
        min_n, max_n = APPLICATION_RANGE_BY_INSTRUMENT[inst]

        # 이 악기가 지원 가능한 곡(해당 악기 세션이 1개 이상 존재)
        eligible_songs = []
        for song in songs:
            matched = [sess for sess in song.sessions.all() if _session_matches_instrument(sess.name, inst)]
            if matched:
                eligible_songs.append((song, matched))

        if not eligible_songs:
            applied_counter[user.username] = 0
            continue

        target_cnt = random.randint(min_n, max_n)
        target_cnt = min(target_cnt, len(eligible_songs))

        selected = random.sample(eligible_songs, target_cnt)
        for _, matching_sessions in selected:
            # 같은 악기 세션이 여러 개인 경우(예: Guitar1/2/3) 랜덤 지원
            target_session = random.choice(matching_sessions)
            target_session.applicant.add(user)

        applied_counter[user.username] = target_cnt

    print("✅ test 유저 세션 지원 생성 완료")
    print(f"- meeting: {meeting.title} ({meeting.id})")
    for username in sorted(applied_counter.keys(), key=lambda x: int(x.replace(USERNAME_PREFIX, ""))):
        print(f"  {username}: {applied_counter[username]}곡 지원")


if __name__ == "__main__":
    # manage.py shell 환경에서: exec(open('create_dummy.py').read())
    create_requested_dummy_users()


@transaction.atomic
def create_large_dummy_for_test_meeting(seed: int = 20260218) -> None:
    """
    요청사항 반영:
    1) test 선곡회의에 30곡 생성
       - 70%: 키보드 제외 기본 구성(V, G1, G2, B, D)
       - 나머지 30%: 기타 1~3개 랜덤 (3개일 때 Guitar3은 extra 세션)
       - 전체 30%: Keyboard 포함
    2) 멤버 구성: V11, G18, B14, D10, K7 (총 60명, test1~test60)
    3) 시간표:
       - 주중 수업 9개(1시간15분 근사 1.5시간)
       - 알바 주0~2회(4시간, 16시 위주/12시 종종)
       - 전체 40%: 평일 1~2회 18~24 동아리 활동 불가
    4) 최소 25곡은 모든 세션이 배정되도록 지원/배정 생성
    """
    random.seed(seed)

    band = Band.objects.get(name=BAND_NAME)
    meeting = Meeting.objects.get(band=band, title="test 선곡회의")

    if not meeting.practice_start_date or not meeting.practice_end_date:
        today = datetime.date.today()
        meeting.practice_start_date = today
        meeting.practice_end_date = today + datetime.timedelta(days=55)
        meeting.save(update_fields=["practice_start_date", "practice_end_date"])

    start_date = meeting.practice_start_date
    end_date = meeting.practice_end_date

    instrument_counts = {
        "Vocal": 11,
        "Guitar": 18,
        "Bass": 14,
        "Drum": 10,
        "Keyboard": 7,
    }
    total_users = sum(instrument_counts.values())

    instrument_pool = []
    for inst, cnt in instrument_counts.items():
        instrument_pool.extend([inst] * cnt)
    random.shuffle(instrument_pool)

    users = []
    for i in range(1, total_users + 1):
        username = f"test{i}"
        user, _ = User.objects.get_or_create(username=username)
        user.realname = f"테스트유저{i}"
        user.instrument = instrument_pool[i - 1]
        user.instrument_detail = ""
        user.is_active = True
        user.set_password(PASSWORD)
        user.save()

        membership, _ = Membership.objects.get_or_create(
            user=user,
            band=band,
            defaults={"role": "MEMBER", "is_approved": True},
        )
        if not membership.is_approved:
            membership.is_approved = True
            membership.save(update_fields=["is_approved"])
        users.append(user)

    _apply_human_dummy_names(users, SELECTED_DUMMY_NAME_POOL_60)

    # test 유저 시간표 초기화
    RecurringBlock.objects.filter(user__in=users).delete()
    OneOffBlock.objects.filter(user__in=users).delete()
    RecurringException.objects.filter(user__in=users).delete()
    MemberAvailability.objects.filter(user__in=users, date__range=[start_date, end_date]).delete()

    club_member_count = int(round(total_users * 0.4))
    club_members = set(random.sample(users, club_member_count))

    for user in users:
        day_blocks = {d: [] for d in range(7)}

        # 주중 수업 9개
        classes_placed = 0
        attempts = 0
        while classes_placed < 9 and attempts < 400:
            attempts += 1
            day = random.randint(0, 4)
            start = random.choice(CLASS_START_INDICES)
            end = start + CLASS_SLOTS
            # 수업 시작 전 30분 버퍼 추가 (09:00 시작은 제외)
            buffered_start = start if start <= 18 else start - 1
            if _add_non_overlapping_block(day_blocks, day, buffered_start, end, "수업"):
                classes_placed += 1

        # 알바 주 0~2회
        part_cnt = random.randint(0, 2)
        if part_cnt:
            for day in random.sample(range(7), k=part_cnt):
                start = random.choices(PART_TIME_START_CANDIDATES, weights=PART_TIME_START_WEIGHTS, k=1)[0]
                end = start + PART_TIME_SLOTS
                day_blocks[day].append((start, end, "알바"))

        # 40%: 평일 동아리 활동 1~2회 18:00~24:00
        if user in club_members:
            target_cnt = random.randint(1, 2)
            candidates = list(range(5))
            random.shuffle(candidates)
            placed = 0
            for day in candidates:
                day_blocks[day].append((36, 48, "동아리활동"))
                placed += 1
                if placed >= target_cnt:
                    break

        for day, blocks in day_blocks.items():
            blocks = _resolve_day_blocks_with_priority(blocks)
            for s, e, reason in sorted(blocks, key=lambda x: x[0]):
                RecurringBlock.objects.create(
                    user=user,
                    day_of_week=day,
                    start_index=s,
                    end_index=e,
                    reason=reason,
                    start_date=start_date,
                    end_date=end_date,
                )

        _sync_member_availability_from_blocks(user, start_date, end_date)

    _apply_weekly_random_oneoff_rules(users, start_date, end_date)
    for user in users:
        _sync_member_availability_from_blocks(user, start_date, end_date)

    # 기존 데이터 정리: test 선곡회의 곡/세션, 모든 기존 확정 스케줄
    PracticeSchedule.objects.all().delete()
    Song.objects.filter(meeting=meeting).delete()

    # 곡 생성
    author = band.memberships.filter(role="LEADER", is_approved=True).first()
    author_user = author.user if author else users[0]

    total_songs = 30
    base_song_count = int(total_songs * 0.7)  # 21
    keyboard_song_count = int(total_songs * 0.3)  # 9

    song_indices = list(range(total_songs))
    random.shuffle(song_indices)
    keyboard_set = set(song_indices[:keyboard_song_count])
    variable_guitar_set = set(song_indices[base_song_count:])  # 나머지 9곡

    created_songs = []
    for idx in range(total_songs):
        song = Song.objects.create(
            meeting=meeting,
            author=author_user,
            title=f"Dummy Song {idx + 1}",
            artist=f"Dummy Artist {random.randint(1, 12)}",
            url=f"https://youtube.com/watch?v=dummy{idx + 1:02d}",
        )

        sessions = [("Vocal", False), ("Bass", False), ("Drum", False)]

        if idx in variable_guitar_set:
            g_cnt = random.randint(1, 3)
        else:
            g_cnt = 2

        if g_cnt >= 1:
            sessions.append(("Guitar1", False))
        if g_cnt >= 2:
            sessions.append(("Guitar2", False))
        if g_cnt >= 3:
            sessions.append(("Guitar3", True))  # 추가 세션

        if idx in keyboard_set:
            sessions.append(("Keyboard", False))

        for name, is_extra in sessions:
            Session.objects.create(song=song, name=name, is_extra=is_extra)

        created_songs.append(song)

    # 지원/배정 생성 (최소 25곡 완배정)
    inst_users = {
        "Vocal": [u for u in users if u.instrument == "Vocal"],
        "Guitar": [u for u in users if u.instrument == "Guitar"],
        "Bass": [u for u in users if u.instrument == "Bass"],
        "Drum": [u for u in users if u.instrument == "Drum"],
        "Keyboard": [u for u in users if u.instrument == "Keyboard"],
    }

    def _pool_for_session_name(name: str):
        nm = name.lower()
        if nm.startswith("guitar"):
            return inst_users["Guitar"]
        if nm == "vocal":
            return inst_users["Vocal"]
        if nm == "bass":
            return inst_users["Bass"]
        if nm == "drum":
            return inst_users["Drum"]
        if nm == "keyboard":
            return inst_users["Keyboard"]
        return users

    song_order = created_songs[:]
    random.shuffle(song_order)
    fully_target = set(song_order[:25])

    for song in created_songs:
        used_user_ids = set()
        for sess in song.sessions.all():
            pool = _pool_for_session_name(sess.name)
            if not pool:
                continue

            if song in fully_target:
                # 같은 곡 안에서 가능하면 다른 사람으로 배정
                available_pool = [u for u in pool if u.id not in used_user_ids] or pool
                assignee = random.choice(available_pool)
                sess.assignee = assignee
                sess.save(update_fields=["assignee"])
                used_user_ids.add(assignee.id)

                # 지원자 2~4명(풀 크기에 맞춰)
                k = min(len(pool), random.randint(2, 4))
                applicants = random.sample(pool, k=k)
                if assignee not in applicants:
                    applicants[0] = assignee
                sess.applicant.add(*applicants)
            else:
                # 나머지 5곡은 일부만 배정/지원
                if random.random() < 0.65:
                    assignee = random.choice(pool)
                    sess.assignee = assignee
                    sess.save(update_fields=["assignee"])
                    sess.applicant.add(assignee)
                if random.random() < 0.8:
                    k = min(len(pool), random.randint(1, 3))
                    sess.applicant.add(*random.sample(pool, k=k))

    full_count = sum(1 for s in created_songs if s.is_session_full)

    print("✅ 대규모 더미데이터 생성 완료")
    print(f"- 밴드: {band.name}")
    print(f"- 미팅: {meeting.title}")
    print(f"- PracticeSchedule 삭제: 완료")
    print(f"- 멤버: {total_users}명 (test1~test{total_users}, pw: {PASSWORD})")
    print(f"- 악기 분포: {instrument_counts}")
    print(f"- 곡: {total_songs}개 생성")
    print(f"- 키보드 포함 곡: {keyboard_song_count}개")
    print(f"- 완전 배정 곡: {full_count}개")


@transaction.atomic
def setup_meeting_with_template_songs(
    band_name: str = BAND_NAME,
    meeting_title: str = "김민기 명곡선",
    total_songs: int = 60,
    seed: int = 42,
) -> None:
    """
    1) 새 미팅 생성 (같은 제목이 이미 있으면 재사용)
    2) CSV 템플릿 기반 60곡 생성 (기존 곡 삭제 후 재생성)
    3) 밴드의 기존 승인 멤버 전원을 미팅 참가자(APPROVED)로 등록

    실행 예시 (manage.py shell):
        exec(open('create_dummy.py').read())
        setup_meeting_with_template_songs()
    """
    random.seed(seed)
    today = datetime.date.today()

    band = Band.objects.get(name=band_name)

    # 1) 미팅 생성 또는 재사용
    meeting, created = Meeting.objects.get_or_create(
        band=band,
        title=meeting_title,
        defaults={
            'practice_start_date': today,
            'practice_end_date': today + datetime.timedelta(days=56),
            'description': '김민기 밴드음악 명곡선 선곡회의',
        },
    )
    if not created:
        meeting.practice_start_date = today
        meeting.practice_end_date = today + datetime.timedelta(days=56)
        meeting.save(update_fields=['practice_start_date', 'practice_end_date'])

    # 2) 기존 곡 정리 후 CSV 기반 재생성
    Song.objects.filter(meeting=meeting).delete()

    csv_path = os.path.join(os.getcwd(), '김민기_밴드음악_명곡선_선곡템플릿.csv')
    template_songs = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            template_songs.append(row)

    leader_m = (
        band.memberships.filter(role='LEADER', is_approved=True).first()
        or band.memberships.filter(is_approved=True).first()
    )
    if not leader_m:
        raise ValueError(f"'{band_name}' 밴드에 승인된 멤버가 없습니다.")
    author = leader_m.user

    n_templates = len(template_songs)
    for idx in range(total_songs):
        tmpl = template_songs[idx % n_templates]
        title = tmpl['title']
        if idx >= n_templates:
            repeat_num = idx // n_templates + 1
            title = f"{title} ({repeat_num})"

        song = Song.objects.create(
            meeting=meeting,
            author=author,
            title=title,
            artist=tmpl['artist'],
            url=tmpl.get('url', '') or '',
            author_note=tmpl.get('author_note', '') or '',
        )

        needed = [s.strip() for s in (tmpl.get('needed_session') or '').split(',') if s.strip()]
        for name in needed:
            Session.objects.create(song=song, name=name, is_extra=False)

        extra = (tmpl.get('extra_session') or '').strip()
        if extra:
            Session.objects.create(song=song, name=extra, is_extra=True)

    # 3) 기존 승인 멤버 전원 미팅 참가자 등록
    members = User.objects.filter(
        user_memberships__band=band,
        user_memberships__is_approved=True,
    ).distinct()

    now = timezone.now()
    added = 0
    for user in members:
        _, created_p = MeetingParticipant.objects.get_or_create(
            meeting=meeting,
            user=user,
            defaults={
                'status': MeetingParticipant.STATUS_APPROVED,
                'role': MeetingParticipant.ROLE_MEMBER,
                'approved_at': now,
            },
        )
        if created_p:
            added += 1

    print("✅ 미팅 생성 + 곡 생성 + 멤버 참가자 등록 완료")
    print(f"- 밴드: {band_name}")
    print(f"- 미팅: {meeting.title} ({'신규' if created else '기존'}), id={meeting.id}")
    print(f"- 합주 기간: {meeting.practice_start_date} ~ {meeting.practice_end_date}")
    print(f"- 곡: {total_songs}개 생성 (템플릿 {n_templates}개 순환)")
    print(f"- 참가자 신규 등록: {added}명 / 전체 승인 멤버: {members.count()}명")
