from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser
import random
import uuid
import datetime

# Create your models here.
class User(AbstractUser):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    realname = models.CharField(max_length=30, blank=False, null=False)
    nickname = models.CharField(max_length=30, blank=True, unique=True)
    phone_number = models.CharField(max_length=15, blank=True)

    INSTRUMENT_CHOICES = [
        ('Vocal', '보컬'),
        ('Guitar', '기타'),
        ('Bass', '베이스'),
        ('Drum', '드럼'),
        ('Keyboard', '건반'),
        ('Etc.', '그 외'),
    ]

    instrument = models.CharField(
        max_length=20,
        choices=INSTRUMENT_CHOICES,
        blank=True
    )

    instrument_detail = models.CharField(
        max_length=50,
        blank=True
    )

    PREFIX_MAP = {
        'Vocal': [
            '가사 까먹은', '스트랩실 놓고 온', '물 마시는',
            '고음불가', '삑사리 난', '목이 쉰'
        ],
        'Guitar': [
            '줄 끊어먹은', '피크 잃어버린', '이펙터 30분', '튜닝 10분',
            '솔로 욕심쟁이', '앰프 안 킨'
        ],
        'Bass': [
            '존재감 없는', '근음 셔틀', '소리가 안 들리는',
            '손가락 아픈', '4현 기타', '메가 우쿠렐레'
        ],
        'Drum': [
            '스틱 부러진', 'BPM 제곱자', '심벌 깨먹은',
            '다리가 아픈', '메트로놈 바이패스'
        ],
        'Keyboard': [
            '체르니 30', '합주실 인간 워머', '보이스 어떻게 골라요?'
        ],
    }

    GENERIC_NICKNAMES = [
        '합주실 지박령', '하루 뮬질 3시간', '악기 없는',
        '편의점 다녀온',
    ]

    def save(self, *args, **kwargs):
        # 공백만 입력된 닉네임은 미입력으로 간주한다.
        self.nickname = str(self.nickname or '').strip()

        if not self.nickname:
            while True:
                random_num = str(random.randint(1,99999)) + '번째 '
                temp_nickname = ""
                if self.instrument and self.instrument != 'Etc.' and self.instrument in self.PREFIX_MAP:
                    prefix = random.choice(self.PREFIX_MAP[self.instrument])
                    instrument_kor_name = dict(self.INSTRUMENT_CHOICES).get(self.instrument, '뮤지션')
                    temp_nickname = f'{random_num}{prefix} {instrument_kor_name}'
                else:
                    temp_nickname = random_num + random.choice(self.GENERIC_NICKNAMES)

                if not type(self).objects.filter(nickname=temp_nickname).exists():
                    self.nickname = temp_nickname
                    break

        super().save(*args, **kwargs)

    @property
    def display_instrument(self):
        if self.instrument == 'Etc.' and self.instrument_detail:
            return self.instrument_detail

        return self.get_instrument_display()

class Band(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    name = models.CharField(max_length=100)
    member = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='Membership',
        related_name='bands'
    )
    school = models.CharField(max_length=50, verbose_name='학교/단체명', blank=True)

    DEPARTMENT_CHOICES = [
        ('CENTER', '중앙 동아리'),
        ('COLLEGE', '단과대 밴드'),
        ('MAJOR', '학과 밴드'),
        ('INDIE', '독립 밴드'),
        ('ETC', '기타'),
    ]
    department = models.CharField(
        max_length=20,
        choices=DEPARTMENT_CHOICES,
        default='ETC',
        verbose_name="소속 분류"
    )

    department_detail = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="소속 상세 (직접 입력)"
    )

    introduce = models.CharField(max_length=100, verbose_name="한 줄 소개", blank=True)
    description = models.TextField(verbose_name="상세 소개", blank=True)
    is_public = models.BooleanField(
        default=True,
        verbose_name='밴드 목록에 공개'
    )

    @property
    def leader(self):
        membership = self.memberships.filter(role='LEADER').first()
        if membership:
            return membership.user.realname
        return '알 수 없음'

    @property
    def active_member_count(self):
        return self.memberships.filter(is_approved=True).count()

    @property
    def unapproved_member_count(self):
        return self.memberships.filter(is_approved=False).count()

    def __str__(self):
        return self.name


class Meeting(models.Model):
    VISIBILITY_LISTED = 'LISTED'
    VISIBILITY_UNLISTED = 'UNLISTED'
    VISIBILITY_CHOICES = [
        (VISIBILITY_LISTED, '목록 공개'),
        (VISIBILITY_UNLISTED, '목록 비공개(링크 전용)'),
    ]

    JOIN_POLICY_OPEN = 'OPEN'
    JOIN_POLICY_APPROVAL = 'APPROVAL'
    JOIN_POLICY_CHOICES = [
        (JOIN_POLICY_OPEN, '바로 참가'),
        (JOIN_POLICY_APPROVAL, '승인 필요'),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='meetings')
    title = models.CharField(max_length=100)
    performance_datetime = models.DateTimeField(blank=True, null=True, verbose_name='공연 일시')
    schedule = models.DateTimeField(blank=True, null=True)
    location = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=300, blank=True)
    practice_start_date = models.DateField(null=True, blank=True, verbose_name="합주 시작일")
    practice_end_date = models.DateField(null=True, blank=True, verbose_name="합주 종료일")
    is_schedule_coordinating = models.BooleanField(default=False)
    is_session_application_closed = models.BooleanField(default=False)
    is_final_schedule_released = models.BooleanField(default=False)
    is_booking_in_progress = models.BooleanField(default=False)
    schedule_version = models.PositiveIntegerField(default=1)
    is_final_schedule_confirmed = models.BooleanField(default=False)
    visibility = models.CharField(
        max_length=16,
        choices=VISIBILITY_CHOICES,
        default=VISIBILITY_LISTED,
    )
    join_policy = models.CharField(
        max_length=16,
        choices=JOIN_POLICY_CHOICES,
        default=JOIN_POLICY_OPEN,
    )

    class Meta:
        indexes = [
            models.Index(fields=['band', 'created_at'], name='meeting_band_created_idx'),
            models.Index(fields=['band', 'visibility', 'created_at'], name='meeting_band_vis_created_idx'),
            models.Index(fields=['band', 'practice_start_date', 'practice_end_date'], name='meeting_band_prac_range_idx'),
        ]

    # models.py > Meeting 클래스 내부

    # [추가할 코드]
    @property
    def is_ready_for_scheduling(self):
        """
        모든 곡의 세션이 꽉 찼는지 확인하는 함수
        하나라도 빈 자리가 있으면 False를 반환합니다.
        """
        # 1. 곡이 하나도 없으면 매칭 불가
        if not self.songs.exists():
            return False

        # 2. 등록된 모든 곡을 검사
        for song in self.songs.all():
            # Song 모델에 있는 is_session_full 속성 활용
            if not song.is_session_full:
                return False

        # 3. 통과하면 True
        return True

    def __str__(self):
        return self.title

    @property
    def schedule_stage_code(self):
        if self.is_final_schedule_confirmed:
            return 'FINAL_CONFIRMED'
        if self.is_booking_in_progress:
            return 'BOOKING_IN_PROGRESS'
        if self.is_schedule_coordinating:
            return 'DRAFT_MATCHING'
        if self.is_final_schedule_released:
            return 'RELEASED_FOR_REVIEW'
        return 'DRAFT_MATCHING'

    @property
    def schedule_stage_label(self):
        labels = {
            'DRAFT_MATCHING': '매칭중',
            'RELEASED_FOR_REVIEW': '공유중',
            'BOOKING_IN_PROGRESS': '예약중',
            'FINAL_CONFIRMED': '합주 시간표 확정',
        }
        return labels.get(self.schedule_stage_code, '매칭중')


class MeetingParticipant(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_LEFT = 'LEFT'
    STATUS_CHOICES = [
        (STATUS_PENDING, '승인 대기'),
        (STATUS_APPROVED, '참여 승인'),
        (STATUS_REJECTED, '반려'),
        (STATUS_LEFT, '탈퇴'),
    ]
    ROLE_MEMBER = 'MEMBER'
    ROLE_MANAGER = 'MANAGER'
    ROLE_CHOICES = [
        (ROLE_MEMBER, '멤버'),
        (ROLE_MANAGER, '미팅 매니저'),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='meeting_participations')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_APPROVED)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_meeting_participants',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['meeting', 'user'], name='meeting_participant_unique'),
        ]
        indexes = [
            models.Index(fields=['meeting', 'status'], name='meeting_part_status_idx'),
            models.Index(fields=['user', 'status'], name='meeting_user_status_idx'),
            models.Index(fields=['user', 'status', 'meeting'], name='meeting_user_stat_meet_idx'),
        ]

    def __str__(self):
        return f'{self.meeting.title} - {self.user.username} ({self.status}, {self.role})'

class Song(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='songs')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posted_songs')
    title = models.CharField(max_length=100)
    artist = models.CharField(max_length=100)
    author_note = models.CharField(max_length=50, blank=True, default='', verbose_name='작성자 한 마디')
    url = models.URLField(blank=True)
    has_sheet = models.BooleanField(default=False, verbose_name='악보 있음')
    created_at = models.DateTimeField(auto_now_add=True)
    is_closed = models.BooleanField(default=False)

    @property
    def is_session_full(self):
        # 필수 세션(is_extra=False) 중 assignee가 없는 것이 하나라도 있으면 False
        return not self.sessions.filter(assignee__isnull=True).exists()

    def __str__(self):
        return f'{self.title} - {self.artist}'

    @property
    def current_needed_session(self):
        return self.sessions.filter(is_extra=False).values_list('name', flat=True)

    @property
    def current_extra_session(self):
        return self.sessions.filter(is_extra=True).values_list('name', flat=True)

        # models.py > Song 클래스 내부

        # [추가] 세션을 고정된 순서대로 리스트로 만들어주는 함수
        # models.py > Song 클래스 내부

    def get_ordered_sessions(self):
        fixed_order = ['Vocal', 'Guitar1', 'Guitar2', 'Bass', 'Drum', 'Keyboard']

        # [추가] 화면에 표시할 약어 맵핑
        abbr_map = {
            'Vocal': 'V',
            'Guitar1': 'G1',
            'Guitar2': 'G2',
            'Bass': 'B',
            'Drum': 'D',
            'Keyboard': 'K'
        }

        current_sessions = {s.name: s for s in self.sessions.all()}
        result = []

        # 1. 고정 세션 처리
        for role in fixed_order:
            session = current_sessions.get(role)
            # 약어 가져오기 (없으면 원래 이름)
            display_name = abbr_map.get(role, role)

            result.append({
                'role': role,
                'obj': session,
                'abbr': display_name  # <-- 약어 추가
            })

        # 2. 추가 세션 처리 (코러스 등)
        for name, session in current_sessions.items():
            if name not in fixed_order:
                # 추가 세션은 그냥 원래 이름 쓰거나 앞글자만 따거나 (일단 원래 이름)
                result.append({
                    'role': name,
                    'obj': session,
                    'abbr': name
                })

        return result


class Session(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    song = models.ForeignKey(
        Song,
        on_delete=models.CASCADE,
        related_name='sessions'
    )

    applicant = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='applied_sessions',
        blank=True
    )

    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_sessions')

    name = models.CharField(max_length=50)
    has_sheet = models.BooleanField(default=False, verbose_name='악보 있음')
    is_extra = models.BooleanField(default=False)
    is_closed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['song', 'name'], name='session_song_name_idx'),
            models.Index(fields=['song', 'assignee'], name='session_song_assign_idx'),
        ]

    def __str__(self):
        return f'{self.song.title} - {self.name}'

class Membership(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_memberships')
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='memberships')
    message = models.TextField(max_length=500, blank=True, null=True, verbose_name='가입 인사')
    is_approved = models.BooleanField(default=False)
    approval_notified = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)

    ROLE_CHOICES = [
        ('LEADER', '리더'),
        ('MANAGER', '관리자'),
        ('MEMBER', '멤버'),
        ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='MEMBER')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'band'], name='membership_user_band_unique'),
        ]
        indexes = [
            models.Index(fields=['user', 'band', 'is_approved'], name='member_user_band_ok_idx'),
            models.Index(fields=['band', 'is_approved', 'role'], name='member_band_role_ok_idx'),
        ]

    def __str__(self):
        return self.band.name + ' (membership)'


class PracticeRoom(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    band = models.ForeignKey(
        Band,
        on_delete=models.SET_NULL,
        related_name='rooms',
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=50)
    capacity = models.IntegerField(default=7)
    location = models.CharField(max_length=100, blank=True, verbose_name="위치 설명")
    is_temporary = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['band', 'is_temporary', 'name'], name='room_band_temp_name_idx'),
        ]

    def __str__(self):
        if self.band_id and self.band:
            return f'{self.band.name} - {self.name}'
        return f'공용 - {self.name}'


class RoomBlock(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    room = models.ForeignKey(PracticeRoom, on_delete=models.CASCADE, related_name='blocks')
    date = models.DateField()
    start_index = models.IntegerField()
    end_index = models.IntegerField()
    source_meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='generated_room_blocks',
    )

    class Meta:
        indexes = [
            models.Index(fields=['room', 'date', 'start_index'], name='roomblock_room_date_start_idx'),
            models.Index(fields=['source_meeting', 'date'], name='roomblock_source_date_idx'),
            models.Index(fields=['source_meeting', 'room', 'date', 'start_index'], name='roomblock_src_r_d_s_idx'),
        ]


class RecurringBlock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recurring_blocks')

    day_of_week = models.IntegerField()
    start_index = models.IntegerField()
    end_index = models.IntegerField()
    reason = models.CharField(max_length=30)
    start_date = models.DateField(null=False, blank=False, default=datetime.date.today)
    end_date = models.DateField(null=False, blank=False, default=datetime.date.today)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'start_date', 'end_date'], name='rb_user_start_end_idx'),
            models.Index(fields=['user', 'day_of_week', 'start_index'], name='rb_user_day_start_idx'),
        ]

    def __str__(self):
        return f'{self.user.realname} - {self.day_of_week} : {self.start_index} ~ {self.end_index}'


class SchedulePeriodPreset(models.Model):
    PRESET_SEMESTER_1 = 'SEMESTER_1'
    PRESET_SUMMER_BREAK = 'SUMMER_BREAK'
    PRESET_SEMESTER_2 = 'SEMESTER_2'
    PRESET_WINTER_BREAK = 'WINTER_BREAK'
    PRESET_CUSTOM = 'CUSTOM'
    PRESET_CHOICES = [
        (PRESET_SEMESTER_1, '1학기'),
        (PRESET_SUMMER_BREAK, '여름방학'),
        (PRESET_SEMESTER_2, '2학기'),
        (PRESET_WINTER_BREAK, '겨울방학'),
        (PRESET_CUSTOM, '기타(직접 설정)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='schedule_period_presets')
    start_date = models.DateField()
    end_date = models.DateField()
    preset_code = models.CharField(max_length=20, choices=PRESET_CHOICES, default=PRESET_CUSTOM)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'start_date', 'end_date'], name='sched_preset_user_range_unique'),
        ]
        indexes = [
            models.Index(fields=['user', 'start_date', 'end_date'], name='sched_preset_user_range_idx'),
        ]

    def __str__(self):
        return f'{self.user.username} - {self.start_date}~{self.end_date} ({self.preset_code})'


class OneOffBlock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='oneoff_blocks')

    date = models.DateField()
    start_index = models.IntegerField()
    end_index = models.IntegerField()
    reason = models.CharField(max_length=30)
    is_generated = models.BooleanField(default=False)
    source_meeting = models.ForeignKey(
        Meeting,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='generated_oneoff_blocks',
    )
    source_song = models.ForeignKey(
        Song,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_oneoff_blocks',
    )

    class Meta:
        indexes = [
            models.Index(fields=['user', 'date', 'is_generated'], name='ob_user_date_gen_idx'),
            models.Index(fields=['source_meeting', 'is_generated', 'date'], name='ob_src_gen_date_idx'),
        ]

    def __str__(self):
        return f'{self.user.realname} - {self.date} : {self.start_index} ~ {self.end_index}'

# models.py

class RecurringException(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    start_index = models.IntegerField()
    end_index = models.IntegerField()
    reason = models.CharField(max_length=30, default='취소')
    # 특정 recurring 블록만 취소할 때 사용 (비어있으면 기존 slot 기반 예외로 처리)
    target_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'date'], name='rex_user_date_idx'),
        ]

    def __str__(self):
        return f'{self.user.realname} - {self.date} : {self.start_index} ~ {self.end_index}'


class MemberAvailability(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='availabilities')
    date = models.DateField()

    available_slot = models.JSONField(default=list)

    class Meta:
        unique_together = ('user', 'date')

    def __str__(self):
        return f'{self.user} - {self.date}'


class PracticeSchedule(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE)
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    room = models.ForeignKey(PracticeRoom, on_delete=models.CASCADE)
    date = models.DateField()
    start_index = models.IntegerField()
    end_index = models.IntegerField()
    is_forced = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 같은 방, 같은 시간에 중복 예약 방지 (DB 레벨의 방어)
        unique_together = ('room', 'date', 'start_index')
        indexes = [
            # meeting별 시간표 조회 + ORDER BY date,start_index 최적화
            models.Index(fields=['meeting', 'date', 'start_index'], name='ps_meet_date_start_idx'),
            # meeting별 곡 집계/조회 최적화
            models.Index(fields=['meeting', 'song'], name='ps_meet_song_idx'),
            # meeting 내 room/date 충돌 체크 최적화
            models.Index(fields=['meeting', 'room', 'date', 'start_index'], name='ps_meet_room_date_start_idx'),
        ]


class MeetingFinalDraft(models.Model):
    """
    관리자가 '최종 합주 일정' 화면으로 넘긴 임시안(draft)을 저장.
    일반 멤버도 이 draft를 읽어 동일한 화면을 볼 수 있다.
    """
    meeting = models.OneToOneField(Meeting, on_delete=models.CASCADE, related_name='final_draft')
    events = models.JSONField(default=list)
    match_params = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_meeting_final_drafts',
    )
    updated_at = models.DateTimeField(auto_now=True)


class MeetingWorkDraft(models.Model):
    """
    매니저/리더 개인의 작업중 시간표(1인 1개).
    - meeting + user 조합당 단일 draft만 유지한다.
    """
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='work_drafts')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='meeting_work_drafts',
    )
    events = models.JSONField(default=list)
    match_params = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('meeting', 'user')
        indexes = [
            models.Index(fields=['meeting', 'user'], name='mwd_meeting_user_idx'),
        ]


class MeetingScheduleConfirmation(models.Model):
    """
    최종 합주 일정 확인 여부(멤버별)를 저장.
    """
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='schedule_confirmations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='schedule_confirmations')
    version = models.PositiveIntegerField(default=1)
    confirmed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('meeting', 'user', 'version')
        indexes = [
            models.Index(fields=['meeting', 'version'], name='msc_meeting_version_idx'),
            models.Index(fields=['meeting', 'version', 'user'], name='msc_meet_ver_user_idx'),
        ]


class ExtraPracticeSchedule(models.Model):
    """
    최종 확정 이후 곡 참가자(Session.assignee)가 직접 잡는 추가 합주.
    자동 매칭과 무관하며, 즉시 확정된다.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(
        Meeting, on_delete=models.CASCADE, related_name='extra_practice_schedules'
    )
    song = models.ForeignKey(
        Song, on_delete=models.CASCADE, related_name='extra_practice_schedules'
    )
    room = models.ForeignKey(
        PracticeRoom, on_delete=models.CASCADE, related_name='extra_practice_schedules'
    )
    date = models.DateField()
    start_index = models.IntegerField()   # 18~47 (30분 슬롯, 09:00~24:00)
    end_index = models.IntegerField()     # start_index < end_index
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_extra_practices',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('room', 'date', 'start_index')
        indexes = [
            models.Index(fields=['meeting', 'song'], name='eps_meeting_song_idx'),
            models.Index(fields=['meeting', 'date'], name='eps_meeting_date_idx'),
            models.Index(fields=['room', 'date', 'start_index'], name='eps_room_date_start_idx'),
        ]


class SongComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='song_comments',
    )
    content = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['song', 'created_at'], name='songcmt_song_created_idx'),
            models.Index(fields=['author', 'created_at'], name='songcmt_author_created_idx'),
        ]

    def __str__(self):
        return f'{self.song.title} - {self.author.username}'
