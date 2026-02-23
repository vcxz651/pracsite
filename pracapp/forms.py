# pracapp/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Song, User, Membership, Meeting, Band
import datetime


class BandUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'realname', 'nickname', 'phone_number',
                  'instrument', 'instrument_detail']
        labels = {
            'username': '아이디',
            'realname': '이름 (필수)',
            'nickname': '닉네임 (선택)',
            'phone_number': '연락처 (선택)',
            'instrument': '주 세션',
            'instrument_detail': '(Etc. 선택 시 상세 입력)',
        }
        widgets = {
            'nickname': forms.TextInput(attrs={'placeholder': '미입력시 랜덤 생성'}),
            'instrument_detail': forms.TextInput(attrs={'placeholder': 'ex. 해금, 키타',}),
            'phone_number': forms.TextInput(attrs={'placeholder': '- 없이 숫자만 입력'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs['class'] = 'form_control'

class SongForm(forms.ModelForm):

    SESSION_CHOICES = [
        ('Vocal', 'Vocal'), ('Guitar1', 'Guitar1'), ('Guitar2', 'Guitar2'),
        ('Drum', 'Drum'), ('Bass', 'Bass'), ('Keyboard', 'Keyboard'),
    ]
    needed_session = forms.MultipleChoiceField(
        choices=SESSION_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        initial=['Vocal', 'Guitar1', 'Guitar2', 'Bass', 'Drum'],
        label='필요한 세션'
    )

    extra_session = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '쉼표로 구분(ex. Vocal2, 탬버린1)'}),
        label='추가 세션 (선택)',
    )

    sheet_sessions = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_sheet_sessions'}),
        label='세션별 악보 유무',
    )

    class Meta:
        model = Song
        fields = [
            'title',
            'artist',
            'author_note',
            'url',
            'needed_session',
            'extra_session',
            'sheet_sessions',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '곡 제목'}),
            'artist': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '원곡 아티스트'}),
            'author_note': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '작성자 한 마디 (최대 50자)', 'maxlength': 50}),
            'url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://youtube.com/...'}),
        }

    def clean_sheet_sessions(self):
        raw = (self.cleaned_data.get('sheet_sessions') or '').strip()
        if not raw:
            return []
        names = [x.strip() for x in raw.split(',') if x.strip()]
        # 중복 제거 + 입력 순서 유지
        seen = set()
        result = []
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            result.append(n)
        return result


class BandCreateForm(forms.ModelForm):
    class Meta:
        model = Band
        fields = [
            'name', 'school', 'department', 'department_detail',
            'introduce', 'description', 'is_public'
        ]

        widgets = {
            'introduce': forms.TextInput(attrs={'placeholder': '우리 밴드를 한 문장으로 소개'}),
            'school': forms.TextInput(attrs={'placeholder': 'ex. 한국대학교'}),
            'department_detail': forms.TextInput(attrs={
                'placeholder': 'ex. 사회과학대학, 사회학과 (분류 선택 후 입력)',
                'id': 'detail-input'  # JS 제어용 ID
            }),
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': '자세한 소개글을 적어주세요.'}),
        }

        labels = {
            'is_public': '밴드 목록에 이 밴드를 공개합니다. (체크 해제 시 초대 링크로만 가입 가능)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'is_public':
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'


class MemberEnlistForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = ['message']

        widgets = {
            'message': forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': '간단한 자기소개(100자 이내)',
            'rows': 3
            }),
        }


# forms.py

# forms.py

class MeetingCreateForm(forms.ModelForm):
    class Meta:
        model = Meeting
        # [수정] 합주 시작일/종료일 필드 추가
        fields = [
            'title', 'performance_datetime', 'schedule', 'location', 'description',
            'visibility', 'join_policy',
            'practice_start_date', 'practice_end_date'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        today = datetime.date.today()
        semester = 1 if today.month < 6 else 2

        # 1. 제목
        self.fields['title'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': f'ex. {today.year}년도 {semester}학기 정기공연'
        })

        # 2. 공연 일시 (datetime-local)
        self.fields['performance_datetime'].required = False
        self.fields['performance_datetime'].widget = forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }
        )

        # 3. 선곡회의 일시 (datetime-local)
        self.fields['schedule'].widget = forms.DateTimeInput(
            format='%Y-%m-%dT%H:%M',
            attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }
        )

        # 4. 장소
        self.fields['location'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'ex. 헤게관 50413, 줌(Zoom)'
        })

        # 5. 메모
        self.fields['description'].widget.attrs.update({
            'class': 'form-control',
            'rows': 5,
            'placeholder': '기타 특이사항'
        })

        self.fields['visibility'].label = "목록 노출 여부"
        self.fields['visibility'].widget = forms.RadioSelect(
            choices=self.fields['visibility'].choices,
            attrs={'class': 'btn-check'}
        )

        self.fields['join_policy'].label = "참가 신청 방식"
        self.fields['join_policy'].widget = forms.RadioSelect(
            choices=self.fields['join_policy'].choices,
            attrs={'class': 'btn-check'}
        )

        # [NEW] 6. 합주 시작일 (date)
        self.fields['practice_start_date'].label = "합주 시작일"
        self.fields['practice_start_date'].required = True
        self.fields['practice_start_date'].widget = forms.DateInput(
            format='%Y-%m-%d',
            attrs={
                'class': 'form-control',
                'type': 'date'
            }
        )

        # [NEW] 7. 합주 종료일 (date)
        self.fields['practice_end_date'].label = "합주 종료일 (공연날)"
        self.fields['practice_end_date'].required = True
        self.fields['practice_end_date'].widget = forms.DateInput(
            format='%Y-%m-%d',
            attrs={
                'class': 'form-control',
                'type': 'date'
            }
        )

    def clean(self):
        cleaned_data = super().clean()
        performance_datetime = cleaned_data.get('performance_datetime')
        practice_start_date = cleaned_data.get('practice_start_date')
        practice_end_date = cleaned_data.get('practice_end_date')
        if performance_datetime and not practice_end_date:
            cleaned_data['practice_end_date'] = performance_datetime.date()
            practice_end_date = cleaned_data['practice_end_date']
        if practice_start_date and practice_end_date and practice_start_date > practice_end_date:
            self.add_error('practice_end_date', '합주 종료일은 시작일보다 빠를 수 없습니다.')
        return cleaned_data


# forms.py
from .models import PracticeRoom

class PracticeRoomForm(forms.ModelForm):
    class Meta:
        model = PracticeRoom
        fields = ['name', 'capacity', 'location', 'is_temporary']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: A룸, 큰방'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 지하 1층, 정문 앞'}),
            'is_temporary': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': '합주실 이름',
            'capacity': '수용 인원',
            'location': '위치 (선택)',
            'is_temporary': '임시 합주실 여부',
        }


class RoomCreateForm(forms.ModelForm):
    class Meta:
        model = PracticeRoom
        fields = ['name', 'capacity', 'location']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: A룸, 큰방'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 지하 1층 (선택)'}),
        }
        labels = {
            'name': '합주실 이름',
            'capacity': '정원 (기본 10명)',
            'location': '위치 (선택)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['capacity'].initial = 10


class MatchSettingsForm(forms.Form):
    PRIORITY_CHOICES = (
        ('continuity', '같은 곡 연속 배치 우선'),
        ('member_continuity', '멤버 연속 합주 우선'),
        ('weekday', '평일 우선'),
        ('time_pref', '18시 기준 시간 우선'),
    )

    DEFAULT_PRIORITY_ORDER = [key for key, _ in PRIORITY_CHOICES]

    DURATION_CHOICES = (
        (30, "30분"),
        (60, "60분"),
        (90, "90분"),
        (120, "120분"),
    )
    TIME_START_CHOICES = tuple((i, f"{i // 2:02d}:{'00' if i % 2 == 0 else '30'}") for i in range(18, 48))
    TIME_END_CHOICES = tuple((i, f"{i // 2:02d}:{'00' if i % 2 == 0 else '30'}") for i in range(19, 49))

    duration_minutes = forms.TypedChoiceField(
        label="1회 합주 시간",
        choices=DURATION_CHOICES,
        initial=30,
        coerce=int,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    required_count = forms.IntegerField(
        label="주간 합주 횟수",
        initial=1,
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text="주차당 이 곡을 몇 번 합주할지 설정합니다."
    )
    priority_order = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        initial=",".join(DEFAULT_PRIORITY_ORDER)
    )
    room_priority_order = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        initial=""
    )
    room_ids = forms.MultipleChoiceField(
        required=False,
        label="합주실 설정",
        widget=forms.CheckboxSelectMultiple,
        help_text="체크된 합주실만 자동 매칭에 사용합니다."
    )
    exclude_weekends = forms.BooleanField(
        required=False,
        label="주말 제외",
        help_text="체크하면 토/일 슬롯은 자동 매칭 대상에서 제외됩니다."
    )
    room_efficiency_priority = forms.BooleanField(
        required=False,
        label="예약 효율 우선",
        initial=False,
        help_text="체크하면 인접한 합주 배치에서 사용하는 방 종류 수를 최소화하는 쪽을 우선합니다."
    )
    maximize_feasibility = forms.BooleanField(
        required=False,
        label="배치 가능성 최우선",
        initial=False,
        help_text="모든 우선순위를 무시하고, 오직 배치 가능성만 극대화합니다(비추)"
    )
    hour_start_only = forms.BooleanField(
        required=False,
        label="정시 시작만 허용",
        initial=False,
        help_text="체크하면 :00 시작만 배치하고 :30 시작은 배치하지 않습니다."
    )
    time_limit_start = forms.TypedChoiceField(
        label="합주 가능 시작",
        choices=TIME_START_CHOICES,
        initial=18,
        coerce=int,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    time_limit_end = forms.TypedChoiceField(
        label="합주 가능 종료",
        choices=TIME_END_CHOICES,
        initial=48,
        coerce=int,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, room_choices=None, room_initial=None, **kwargs):
        super().__init__(*args, **kwargs)
        room_choices = room_choices or []
        self.fields['room_ids'].choices = room_choices
        if room_initial is not None:
            self.fields['room_ids'].initial = room_initial
        self.fields['exclude_weekends'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['room_efficiency_priority'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['maximize_feasibility'].widget.attrs.update({'class': 'form-check-input'})
        self.fields['hour_start_only'].widget.attrs.update({'class': 'form-check-input'})

    def clean_priority_order(self):
        raw = (self.cleaned_data.get('priority_order') or '').strip()
        if not raw:
            return self.DEFAULT_PRIORITY_ORDER.copy()

        items = [x.strip() for x in raw.split(',') if x.strip()]
        valid_keys = {k for k, _ in self.PRIORITY_CHOICES}

        # 유효하지 않은 키 제거
        items = [x for x in items if x in valid_keys]

        # 중복 제거 + 길이 제한
        dedup = []
        for x in items:
            if x not in dedup:
                dedup.append(x)

        return dedup[:len(self.DEFAULT_PRIORITY_ORDER)] or self.DEFAULT_PRIORITY_ORDER.copy()

    def clean_room_ids(self):
        room_ids = self.cleaned_data.get('room_ids') or []
        if not room_ids:
            raise forms.ValidationError("최소 1개의 합주실을 선택해주세요.")
        return room_ids

    def clean_room_priority_order(self):
        raw = (self.cleaned_data.get('room_priority_order') or '').strip()
        if not raw:
            return []
        allowed = {str(v) for v, _ in self.fields['room_ids'].choices}
        out = []
        seen = set()
        for part in raw.split(','):
            rid = part.strip()
            if not rid or rid in seen or rid not in allowed:
                continue
            seen.add(rid)
            out.append(rid)
        return out

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('time_limit_start')
        end = cleaned.get('time_limit_end')
        if start is not None and end is not None and start >= end:
            self.add_error('time_limit_end', '종료 시간은 시작 시간보다 뒤여야 합니다.')
        return cleaned
