import datetime
import json
import random
from collections import defaultdict
from urllib.parse import urlparse, parse_qs
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import UserPassesTestMixin, LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, UpdateView, DetailView
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from urllib.parse import urlencode
from django.utils import timezone

from ..forms import MeetingCreateForm, PracticeRoomForm, RoomCreateForm
from ..models import (
    Song, Session, Band, Membership, Meeting, User,
    PracticeRoom, RoomBlock, MeetingParticipant, MeetingWorkDraft
)
from ._meeting_common import (
    is_final_locked as common_is_final_locked,
    final_lock_prefix as common_final_lock_prefix,
    final_lock_message as common_final_lock_message,
    final_lock_state_message as common_final_lock_state_message,
    available_rooms_qs as common_available_rooms_qs,
    is_manager_membership as common_is_manager_membership,
    get_approved_membership as common_get_approved_membership,
)


# ====================================================================
# Helper Functions
# ====================================================================

def _is_final_locked(meeting):
    return common_is_final_locked(meeting, include_released=True)


def _final_lock_prefix(meeting):
    return common_final_lock_prefix(meeting)


def _final_lock_message(meeting, action_text):
    return common_final_lock_message(meeting, action_text)


def _final_lock_state_message(meeting):
    return common_final_lock_state_message(meeting)


def _youtube_embed_url(raw_url):
    if not raw_url:
        return None
    try:
        parsed = urlparse(raw_url.strip())
    except Exception:
        return None
    host = (parsed.netloc or '').lower()
    path = parsed.path or ''
    video_id = None

    if 'youtu.be' in host:
        video_id = path.strip('/').split('/')[0] if path.strip('/') else None
    elif 'youtube.com' in host:
        if path == '/watch':
            video_id = parse_qs(parsed.query).get('v', [None])[0]
        elif path.startswith('/shorts/'):
            parts = path.split('/')
            video_id = parts[2] if len(parts) > 2 else None
        elif path.startswith('/embed/'):
            parts = path.split('/')
            video_id = parts[2] if len(parts) > 2 else None
        elif path.startswith('/live/'):
            parts = path.split('/')
            video_id = parts[2] if len(parts) > 2 else None

    if not video_id:
        return None
    # YouTube video id is typically 11 chars ([A-Za-z0-9_-])
    video_id = str(video_id).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        return None
    return f'https://www.youtube.com/embed/{video_id}'


def _meeting_detail_target_with_state(request, meeting_id):
    base = reverse('meeting_detail', kwargs={'pk': meeting_id})
    params = {}
    sort_opt = (request.POST.get('sort', '') or request.GET.get('sort', '')).strip()
    list_mode = (request.POST.get('list_mode', '') or request.GET.get('list_mode', '')).strip()
    page = (request.POST.get('page', '') or request.GET.get('page', '')).strip()
    if sort_opt:
        params['sort'] = sort_opt
    if list_mode:
        params['list_mode'] = list_mode
    if page:
        params['page'] = page
    return f"{base}?{urlencode(params)}" if params else base


def _available_rooms_qs(meeting):
    return common_available_rooms_qs(meeting, include_temporary=False)


def _is_manager_membership(membership):
    return common_is_manager_membership(membership)


def _is_meeting_manager_participant(participant):
    return bool(
        participant
        and participant.status == MeetingParticipant.STATUS_APPROVED
        and participant.role == MeetingParticipant.ROLE_MANAGER
    )


def _get_meeting_membership(meeting, user):
    return common_get_approved_membership(user, meeting.band)


def _has_meeting_manager_permission(meeting, user, membership=None, participant=None):
    membership = membership if membership is not None else _get_meeting_membership(meeting, user)
    if _is_manager_membership(membership):
        return True
    if participant is None:
        participant = MeetingParticipant.objects.filter(meeting=meeting, user=user).first()
    return _is_meeting_manager_participant(participant)


def _ensure_manager_participation(meeting, user):
    membership = _get_meeting_membership(meeting, user)
    if not _is_manager_membership(membership):
        return
    MeetingParticipant.objects.update_or_create(
        meeting=meeting,
        user=user,
        defaults={
            'status': MeetingParticipant.STATUS_APPROVED,
            'approved_at': timezone.now(),
            'approved_by': user,
        },
    )


def _meeting_participation_state(meeting, user):
    membership = _get_meeting_membership(meeting, user)
    if not membership:
        return {
            'membership': None,
            'is_manager': False,
            'participant': None,
            'is_approved_participant': False,
        }
    is_manager = _is_manager_membership(membership)
    if is_manager:
        _ensure_manager_participation(meeting, user)
    participant = MeetingParticipant.objects.filter(meeting=meeting, user=user).first()
    if _is_meeting_manager_participant(participant):
        is_manager = True
    is_approved_participant = bool(
        is_manager or (participant and participant.status == MeetingParticipant.STATUS_APPROVED)
    )
    return {
        'membership': membership,
        'is_manager': is_manager,
        'participant': participant,
        'is_approved_participant': is_approved_participant,
    }


def _build_participant_manage_context(meeting):
    participant_map = {
        str(p.user_id): p
        for p in meeting.participants.select_related('user', 'approved_by').all()
    }
    member_rows = []
    for m in Membership.objects.filter(band=meeting.band, is_approved=True).select_related('user').order_by('user__realname', 'user__username'):
        p = participant_map.get(str(m.user_id))
        status = p.status if p else None
        meeting_role = p.role if p else MeetingParticipant.ROLE_MEMBER
        if m.role in ['LEADER', 'MANAGER']:
            status = MeetingParticipant.STATUS_APPROVED
            meeting_role = MeetingParticipant.ROLE_MEMBER
        member_rows.append({
            'user': m.user,
            'role': m.role,
            'meeting_role': meeting_role,
            'participant': p,
            'status': status,
        })

    pending_rows = [r for r in member_rows if r['status'] == MeetingParticipant.STATUS_PENDING]
    participant_rows = [r for r in member_rows if r['status'] == MeetingParticipant.STATUS_APPROVED]
    non_participant_rows = [r for r in member_rows if r['status'] != MeetingParticipant.STATUS_APPROVED]
    return {
        'meeting': meeting,
        'member_rows': member_rows,
        'pending_rows': pending_rows,
        'participant_rows': participant_rows,
        'non_participant_rows': non_participant_rows,
    }


def _role_label_of(session_name):
    if not session_name:
        return None
    n = str(session_name).strip().lower()
    if n.startswith('vocal') or n.startswith('보컬'):
        return '보컬'
    if n.startswith('guitar') or n.startswith('기타'):
        return '기타'
    if n.startswith('bass') or n.startswith('베이스'):
        return '베이스'
    if n.startswith('drum') or n.startswith('드럼'):
        return '드럼'
    if n.startswith('keyboard') or n.startswith('키보드') or n.startswith('건반'):
        return '키보드'
    return None


def _role_label_of_instrument(instrument):
    if not instrument:
        return None
    n = str(instrument).strip().lower()
    if n == 'vocal':
        return '보컬'
    if n == 'guitar':
        return '기타'
    if n == 'bass':
        return '베이스'
    if n == 'drum':
        return '드럼'
    if n == 'keyboard':
        return '키보드'
    return None


def _effective_meeting_participant_user_ids(meeting):
    approved_participant_ids = set(
        MeetingParticipant.objects.filter(
            meeting=meeting,
            status=MeetingParticipant.STATUS_APPROVED,
        ).values_list('user_id', flat=True)
    )
    manager_ids = set(
        Membership.objects.filter(
            band=meeting.band,
            is_approved=True,
            role__in=['LEADER', 'MANAGER'],
        ).values_list('user_id', flat=True)
    )
    return approved_participant_ids | manager_ids


def _meeting_has_any_applicants(meeting):
    return Session.objects.filter(song__meeting=meeting, applicant__isnull=False).exists()


def _build_session_stats_payload(meeting):
    def _mix_rgb(c1, c2, t):
        t = max(0.0, min(1.0, float(t)))
        return (
            int(round(c1[0] + (c2[0] - c1[0]) * t)),
            int(round(c1[1] + (c2[1] - c1[1]) * t)),
            int(round(c1[2] + (c2[2] - c1[2]) * t)),
        )

    def _rgba(rgb, alpha):
        a = max(0.0, min(1.0, float(alpha)))
        return f'rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {a:.3f})'

    role_assigned = defaultdict(lambda: defaultdict(int))
    role_applied = defaultdict(lambda: defaultdict(int))
    role_session_total = defaultdict(int)

    sessions = (
        Session.objects.filter(song__meeting=meeting)
        .select_related('assignee')
        .prefetch_related('applicant')
    )
    for sess in sessions:
        label = _role_label_of(sess.name)
        if label is None:
            continue
        role_session_total[label] += 1
        if sess.assignee_id:
            role_assigned[label][sess.assignee_id] += 1
        for applicant in sess.applicant.all():
            role_applied[label][applicant.id] += 1

    participant_user_ids = _effective_meeting_participant_user_ids(meeting)

    member_info_map = {
        m.user.id: {
            'name': (m.user.realname or m.user.username),
            'role_label': _role_label_of_instrument(m.user.instrument),
        }
        for m in Membership.objects.filter(
            band=meeting.band,
            is_approved=True,
            user_id__in=participant_user_ids,
        ).select_related('user')
    }
    role_groups = ['보컬', '기타', '드럼', '베이스', '키보드']
    session_stats = []
    for label in role_groups:
        role_member_ids = {
            uid for uid, info in member_info_map.items()
            if info.get('role_label') == label
        }
        # 활동(지원/배정)이 없어도 해당 세션 멤버는 현황판에 표시한다.
        active_uids = role_member_ids | set(role_assigned[label]) | set(role_applied[label])
        members = sorted(
            [
                {
                    'user_id': str(uid),
                    'name': member_info_map[uid]['name'],
                    'assigned': int(role_assigned[label][uid]),
                    'applied': int(role_applied[label][uid]),
                }
                for uid in active_uids
                if uid in member_info_map and member_info_map[uid].get('role_label') == label
            ],
            key=lambda m: m['name']
        )
        player_count = max(1, len(members))
        avg_assigned = (role_session_total[label] / player_count) if player_count else 0
        for m in members:
            assigned = int(m['assigned'])
            if assigned == 0:
                m['load_bg'] = 'rgba(255, 255, 255, 1.0)'
                continue
            if avg_assigned <= 0:
                m['load_bg'] = 'rgba(25, 135, 84, 0.20)'
                continue
            ratio = assigned / max(avg_assigned, 0.01)

            green = (25, 135, 84)
            amber = (255, 193, 7)
            orange = (255, 140, 0)
            red = (220, 53, 69)

            if ratio < 0.80:
                # 충분히 여유: 초록 강조
                intensity = min(1.0, ratio / 0.80)
                rgb = green
                alpha = 0.18 + (0.12 * intensity)
            elif ratio < 1.15:
                # 평균을 약간 넘는 구간까지는 초록 기조 유지 (빡빡함 완화)
                t = (ratio - 0.80) / 0.35
                rgb = _mix_rgb(green, amber, t)
                alpha = 0.20 + (0.08 * t)
            elif ratio < 1.45:
                # 초과 폭이 어느 정도 쌓였을 때부터 주황으로 이동
                t = (ratio - 1.15) / 0.30
                rgb = _mix_rgb(amber, orange, t)
                alpha = 0.24 + (0.06 * t)
            elif ratio < 1.90:
                # 초과 폭이 커질수록: 주황 -> 빨강
                t = (ratio - 1.45) / 0.45
                rgb = _mix_rgb(orange, red, t)
                alpha = 0.28 + (0.08 * t)
            else:
                # 과부하 구간
                rgb = red
                alpha = 0.38

            m['load_bg'] = _rgba(rgb, alpha)

        if members:
            session_stats.append({
                'label': label,
                'member_count': len(members),
                'members': members,
            })

    ordered_labels = ['보컬', '기타', '드럼', '베이스', '키보드']
    stats_by_label = {item['label']: item for item in session_stats}
    ordered_groups = [stats_by_label[lbl] for lbl in ordered_labels if lbl in stats_by_label]
    ordered_groups.extend([item for item in session_stats if item['label'] not in ordered_labels])

    col1, col2 = [], []
    h1, h2 = 0, 0
    for group in ordered_groups:
        weight = 1 + len(group.get('members') or [])
        if h1 <= h2:
            col1.append(group)
            h1 += weight
        else:
            col2.append(group)
            h2 += weight
    return {'col1': col1, 'col2': col2}


# ====================================================================
# Meeting CRUD Views
# ====================================================================

@method_decorator(xframe_options_sameorigin, name='dispatch')
class MeetingCreateView(UserPassesTestMixin, CreateView):
    model = Meeting
    form_class = MeetingCreateForm
    template_name = 'pracapp/meeting_form.html'

    def test_func(self):
        return Membership.objects.filter(
            user=self.request.user,
            band_id=self.kwargs['band_id'],
            is_approved=True,
            role__in=['LEADER', 'MANAGER']
        ).exists()

    def get_success_url(self):
        base_url = reverse_lazy('dashboard')
        current_band_id = self.kwargs['band_id']
        return f'{base_url}?band_id={current_band_id}'

    def form_valid(self, form):
        band_id = self.kwargs['band_id']
        band = get_object_or_404(Band, id=band_id)
        form.instance.band = band
        response = super().form_valid(form)
        _ensure_manager_participation(self.object, self.request.user)
        if self.request.GET.get('modal') == '1':
            redirect_url = reverse('meeting_detail', kwargs={'pk': self.object.pk})
            return HttpResponse(
                f"<script>"
                f"if (window.parent) {{"
                f"window.parent.postMessage({{type:'meeting_modal_saved', redirect_url:'{redirect_url}'}}, window.location.origin);"
                f"}}"
                f"</script>"
            )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_modal'] = self.request.GET.get('modal') == '1'
        return context


@method_decorator(xframe_options_sameorigin, name='dispatch')
class MeetingUpdateView(UserPassesTestMixin, UpdateView):
    model = Meeting
    form_class = MeetingCreateForm
    template_name = 'pracapp/meeting_form.html'

    def get_success_url(self):
        base_url = reverse_lazy('dashboard')
        current_band_id = self.object.band.id
        return f'{base_url}?band_id={current_band_id}'

    def test_func(self):
        return Membership.objects.filter(
            user=self.request.user,
            band=self.get_object().band,
            is_approved=True,
            role__in=['LEADER','MANAGER']
        ).exists()

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.GET.get('modal') == '1':
            return HttpResponse(
                "<script>"
                "if (window.parent) {"
                "window.parent.postMessage({type:'meeting_modal_saved'}, window.location.origin);"
                "}"
                "</script>"
            )
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_modal'] = self.request.GET.get('modal') == '1'
        return context


class MeetingDetailView(LoginRequiredMixin, DetailView):
    model = Meeting
    template_name = 'pracapp/meeting_detail.html'
    context_object_name = 'meeting'

    def dispatch(self, request, *args, **kwargs):
        meeting = self.get_object()
        membership = _get_meeting_membership(meeting, request.user)
        if not membership:
            messages.error(request, '밴드 승인 멤버만 접근할 수 있습니다.')
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        meeting = self.object
        band = meeting.band
        total_song_count = self.object.songs.count()
        state = _meeting_participation_state(meeting, self.request.user)
        membership = state['membership']
        is_manager = state['is_manager']
        participant = state['participant']
        can_participate = state['is_approved_participant']

        requested_sort_option = (self.request.GET.get('sort') or 'default').strip()
        requested_quick_filter = (self.request.GET.get('quick_filter') or '').strip()
        quick_filter = requested_quick_filter if requested_quick_filter in ['assigned', 'applied'] else ''
        allowed_sort_options = (
            ['default', 'created_desc', 'unassigned_desc']
            if is_manager else ['default']
        )
        sort_option = requested_sort_option if requested_sort_option in allowed_sort_options else 'default'

        through = Session.applicant.through
        session_qs = Session.objects.select_related('assignee').prefetch_related('applicant').annotate(
            applicant_count=Count('applicant', distinct=True),
            my_applied=Exists(
                through.objects.filter(
                    session_id=OuterRef('pk'),
                    user_id=self.request.user.id,
                )
            ),
        )
        songs_qs = self.object.songs.prefetch_related(Prefetch('sessions', queryset=session_qs))
        # 등록 순(생성일 오름차순) 고정 번호를 계산해 렌더링 시 재사용한다.
        song_registration_order = {
            str(song_id): idx
            for idx, song_id in enumerate(
                self.object.songs.order_by('created_at', 'title').values_list('id', flat=True),
                start=1,
            )
        }

        def enrich_song(song_obj, include_ordered=False):
            song_obj.registration_order = song_registration_order.get(str(song_obj.id), 0)
            session_list = list(song_obj.sessions.all())
            applicant_counts = [int(getattr(sess, 'applicant_count', 0) or 0) for sess in session_list]
            song_obj.unassigned_session_count = sum(1 for sess in session_list if not sess.assignee_id)
            song_obj.total_applicant_count = sum(applicant_counts)
            song_obj.all_sessions_have_applicants = bool(session_list) and all(cnt > 0 for cnt in applicant_counts)
            song_obj.my_assigned_count = sum(1 for sess in session_list if sess.assignee_id == self.request.user.id)
            song_obj.my_applied_count = sum(1 for sess in session_list if bool(getattr(sess, 'my_applied', False)))
            song_obj.has_missing_applicants = bool(session_list) and any(cnt == 0 for cnt in applicant_counts)
            song_obj.all_assigned = bool(session_list) and all(sess.assignee_id for sess in session_list)
            song_obj.has_unassigned_but_applicants_full = (
                bool(session_list)
                and not song_obj.all_assigned
                and not song_obj.has_missing_applicants
            )
            if include_ordered:
                song_obj.youtube_embed_url = _youtube_embed_url(song_obj.url)
                ordered_items = song_obj.get_ordered_sessions()
                for item in ordered_items:
                    sess = item.get('obj')
                    if not sess:
                        item['applicant_count'] = 0
                        item['my_applied'] = False
                        item['applicant_ids_csv'] = ''
                        continue
                    item['applicant_count'] = int(getattr(sess, 'applicant_count', 0) or 0)
                    item['my_applied'] = bool(getattr(sess, 'my_applied', False))
                    item['applicant_ids_csv'] = ','.join(str(u.id) for u in sess.applicant.all())
                song_obj.ordered_sessions = ordered_items

        # 일반 멤버는 강제 30곡 페이징 + 기본순(초기 렌더 비용 절감)
        if is_manager:
            songs = list(songs_qs)
            for s in songs:
                enrich_song(s, include_ordered=False)

            if quick_filter == 'assigned':
                songs = [s for s in songs if s.my_assigned_count > 0]
            elif quick_filter == 'applied':
                songs = [s for s in songs if s.my_applied_count > 0]

            if sort_option == 'unassigned_desc':
                songs.sort(key=lambda s: (-s.unassigned_session_count, -s.total_applicant_count, s.title))
            elif sort_option == 'created_desc':
                songs.sort(key=lambda s: (-(s.created_at.timestamp() if getattr(s, 'created_at', None) else 0), s.title))
            else:
                sort_option = 'default'
                songs.sort(key=lambda s: ((s.created_at.timestamp() if getattr(s, 'created_at', None) else 0), s.title))

            list_mode = 'all'
            song_page = None
            visible_songs = songs

            for s in visible_songs:
                enrich_song(s, include_ordered=True)

            song_count = len(songs)
            assigned_song_count = sum(1 for s in songs if s.all_assigned)
            unassigned_song_count = sum(1 for s in songs if not s.all_assigned)
            unassigned_song_titles = [s.title for s in songs if not s.all_assigned]
        elif can_participate:
            list_mode = 'all'
            song_page = None
            if quick_filter:
                songs = list(songs_qs)
                for s in songs:
                    enrich_song(s, include_ordered=False)
                if quick_filter == 'assigned':
                    songs = [s for s in songs if s.my_assigned_count > 0]
                elif quick_filter == 'applied':
                    songs = [s for s in songs if s.my_applied_count > 0]
                visible_songs = songs
                song_count = len(songs)
            else:
                visible_songs = list(songs_qs)
                song_count = len(visible_songs)
            for s in visible_songs:
                enrich_song(s, include_ordered=True)
            assigned_song_count = 0
            unassigned_song_count = 0
            unassigned_song_titles = []
        else:
            list_mode = 'all'
            song_page = None
            visible_songs = []
            song_count = 0
            assigned_song_count = 0
            unassigned_song_count = 0
            unassigned_song_titles = []

        final_schedule_available = (
            (meeting.is_final_schedule_released or meeting.is_final_schedule_confirmed)
            and (not meeting.is_schedule_coordinating)
        )

        context['song'] = visible_songs
        context['song_page'] = song_page
        context['list_mode'] = list_mode
        context['song_count'] = song_count
        context['total_song_count'] = total_song_count
        context['assigned_song_count'] = assigned_song_count
        context['unassigned_song_count'] = unassigned_song_count
        context['has_unassigned_songs'] = context['unassigned_song_count'] > 0
        context['unassigned_song_titles'] = unassigned_song_titles
        context['sort_option'] = sort_option
        context['available_sort_options'] = allowed_sort_options
        context['quick_filter'] = quick_filter
        context['can_view_final_schedule'] = bool(membership)
        context['final_schedule_available'] = final_schedule_available
        # 템플릿의 legacy 플래그명(is_leader)을 관리자 공통 권한 플래그로 사용
        context['is_leader'] = is_manager
        context['is_manager'] = is_manager
        context['meeting_participant'] = participant
        context['can_participate_meeting'] = can_participate
        context['is_participation_pending'] = bool(participant and participant.status == MeetingParticipant.STATUS_PENDING)
        context['is_participation_rejected'] = bool(participant and participant.status == MeetingParticipant.STATUS_REJECTED)
        context['is_join_policy_approval'] = meeting.join_policy == Meeting.JOIN_POLICY_APPROVAL
        context['is_final_locked'] = _is_final_locked(meeting)
        context['final_lock_hint'] = _final_lock_message(meeting, '변경할 수 없습니다.')
        context['schedule_stage_label'] = meeting.schedule_stage_label
        context['is_booking_in_progress'] = bool(meeting.is_booking_in_progress)
        context['show_session_details'] = bool(can_participate or is_manager)
        context['rooms'] = band.rooms.filter(is_temporary=False).order_by('name')
        context['meeting_has_applicants'] = _meeting_has_any_applicants(meeting)
        context['can_delete_meeting'] = bool(is_manager and not context['meeting_has_applicants'])
        if is_manager:
            context['has_my_work_draft'] = MeetingWorkDraft.objects.filter(
                meeting=meeting,
                user=self.request.user,
            ).exists()
        else:
            context['has_my_work_draft'] = False
        if is_manager:
            context['pending_participants'] = (
                meeting.participants.filter(status=MeetingParticipant.STATUS_PENDING)
                .select_related('user')
                .order_by('requested_at')
            )
        else:
            context['pending_participants'] = []

        # 현황판은 AJAX로 로드
        context['session_stats'] = []
        context['session_stats_col1'] = []
        context['session_stats_col2'] = []
        context['session_stats_data_url'] = (
            reverse('meeting_session_stats_data', kwargs={'meeting_id': meeting.id})
            if is_manager else ''
        )

        return context


@login_required
def meeting_session_stats_data(request, meeting_id):
    meeting = get_object_or_404(Meeting.objects.select_related('band'), id=meeting_id)
    membership = Membership.objects.filter(
        user=request.user,
        band=meeting.band,
        is_approved=True,
    ).first()
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    payload = _build_session_stats_payload(meeting)
    return JsonResponse({
        'status': 'success',
        'col1': payload.get('col1', []),
        'col2': payload.get('col2', []),
    })


@login_required
def meeting_match_status_data(request, meeting_id):
    meeting = get_object_or_404(Meeting.objects.select_related('band'), id=meeting_id)
    membership = Membership.objects.filter(
        user=request.user,
        band=meeting.band,
        is_approved=True,
    ).first()
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    assigned_song_count = meeting.songs.exclude(sessions__assignee__isnull=True).filter(sessions__isnull=False).distinct().count()
    total_song_count = meeting.songs.count()
    return JsonResponse({
        'status': 'success',
        'is_session_application_closed': bool(meeting.is_session_application_closed),
        'room_count': int(_available_rooms_qs(meeting).count()),
        'assigned_song_count': int(assigned_song_count),
        'total_song_count': int(total_song_count),
        'has_unassigned_songs': bool(total_song_count > assigned_song_count),
    })


@login_required
def meeting_join_request(request, meeting_id):
    if request.method != 'POST':
        return redirect('meeting_detail', pk=meeting_id)

    meeting = get_object_or_404(Meeting.objects.select_related('band'), id=meeting_id)
    target = _meeting_detail_target_with_state(request, meeting_id)
    membership = _get_meeting_membership(meeting, request.user)
    if not membership:
        messages.error(request, '밴드 승인 멤버만 신청할 수 있습니다.')
        return redirect(target)

    if _is_manager_membership(membership):
        _ensure_manager_participation(meeting, request.user)
        messages.info(request, '리더/매니저는 자동 참여 대상입니다.')
        return redirect(target)

    participant, _ = MeetingParticipant.objects.get_or_create(
        meeting=meeting,
        user=request.user,
        defaults={
            'status': MeetingParticipant.STATUS_APPROVED
            if meeting.join_policy == Meeting.JOIN_POLICY_OPEN
            else MeetingParticipant.STATUS_PENDING,
            'approved_at': timezone.now() if meeting.join_policy == Meeting.JOIN_POLICY_OPEN else None,
        },
    )

    if meeting.join_policy == Meeting.JOIN_POLICY_OPEN:
        if participant.status != MeetingParticipant.STATUS_APPROVED:
            participant.status = MeetingParticipant.STATUS_APPROVED
            participant.approved_at = timezone.now()
            participant.approved_by = None
            participant.save(update_fields=['status', 'approved_at', 'approved_by'])
        messages.success(request, '선곡회의 참여가 완료되었습니다.')
    else:
        if participant.status == MeetingParticipant.STATUS_APPROVED:
            messages.info(request, '이미 참여 승인된 선곡회의입니다.')
        else:
            if participant.status != MeetingParticipant.STATUS_PENDING:
                participant.status = MeetingParticipant.STATUS_PENDING
                participant.approved_at = None
                participant.approved_by = None
                participant.save(update_fields=['status', 'approved_at', 'approved_by'])
            messages.success(request, '참가 신청이 접수되었습니다. 리더/매니저 승인 후 참여할 수 있습니다.')
    return redirect(target)


@login_required
def meeting_participant_approve(request, meeting_id, user_id):
    if request.method != 'POST':
        return redirect('meeting_detail', pk=meeting_id)
    meeting = get_object_or_404(Meeting.objects.select_related('band'), id=meeting_id)
    target = _meeting_detail_target_with_state(request, meeting_id)
    membership = _get_meeting_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '권한이 없습니다.')
        return redirect(target)
    participant = get_object_or_404(MeetingParticipant, meeting=meeting, user_id=user_id)
    participant.status = MeetingParticipant.STATUS_APPROVED
    participant.approved_at = timezone.now()
    participant.approved_by = request.user
    participant.save(update_fields=['status', 'approved_at', 'approved_by'])
    messages.success(request, f'{participant.user.realname}님의 참가를 승인했습니다.')
    return redirect(target)


@login_required
def meeting_participant_reject(request, meeting_id, user_id):
    if request.method != 'POST':
        return redirect('meeting_detail', pk=meeting_id)
    meeting = get_object_or_404(Meeting.objects.select_related('band'), id=meeting_id)
    target = _meeting_detail_target_with_state(request, meeting_id)
    membership = _get_meeting_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '권한이 없습니다.')
        return redirect(target)
    participant = get_object_or_404(MeetingParticipant, meeting=meeting, user_id=user_id)
    participant.status = MeetingParticipant.STATUS_REJECTED
    participant.approved_at = None
    participant.approved_by = None
    participant.save(update_fields=['status', 'approved_at', 'approved_by'])
    messages.success(request, f'{participant.user.realname}님의 참가를 반려했습니다.')
    return redirect(target)


@login_required
@xframe_options_sameorigin
def meeting_participant_manage(request, meeting_id):
    meeting = get_object_or_404(Meeting.objects.select_related('band'), id=meeting_id)
    membership = _get_meeting_membership(meeting, request.user)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
        return redirect('meeting_detail', pk=meeting.id)

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        user_id = (request.POST.get('user_id') or '').strip()
        target_user = None
        if user_id:
            target_user = User.objects.filter(id=user_id).first()

        if not target_user:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': '대상 멤버를 찾을 수 없습니다.'}, status=400)
            return redirect(f"{reverse('meeting_participant_manage', kwargs={'meeting_id': meeting.id})}?modal=1")

        target_membership = Membership.objects.filter(
            band=meeting.band,
            user=target_user,
            is_approved=True,
        ).first()
        if not target_membership:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': '밴드 승인 멤버만 관리할 수 있습니다.'}, status=400)
            return redirect(f"{reverse('meeting_participant_manage', kwargs={'meeting_id': meeting.id})}?modal=1")

        if action == 'approve':
            MeetingParticipant.objects.update_or_create(
                meeting=meeting,
                user=target_user,
                defaults={
                    'status': MeetingParticipant.STATUS_APPROVED,
                    'role': MeetingParticipant.ROLE_MEMBER,
                    'approved_at': timezone.now(),
                    'approved_by': request.user,
                },
            )
        elif action == 'reject':
            MeetingParticipant.objects.update_or_create(
                meeting=meeting,
                user=target_user,
                defaults={
                    'status': MeetingParticipant.STATUS_REJECTED,
                    'role': MeetingParticipant.ROLE_MEMBER,
                    'approved_at': None,
                    'approved_by': None,
                },
            )
        elif action == 'remove':
            if target_membership.role in ['LEADER', 'MANAGER']:
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': '리더/매니저는 참가 제외할 수 없습니다.'}, status=400)
            else:
                MeetingParticipant.objects.update_or_create(
                    meeting=meeting,
                    user=target_user,
                    defaults={
                        'status': MeetingParticipant.STATUS_LEFT,
                        'role': MeetingParticipant.ROLE_MEMBER,
                        'approved_at': None,
                        'approved_by': None,
                    },
                )
        elif action == 'set_manager':
            if target_membership.role in ['LEADER', 'MANAGER']:
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': '이미 밴드 관리자 권한이 있습니다.'}, status=400)
            else:
                participant_obj, _ = MeetingParticipant.objects.get_or_create(
                    meeting=meeting,
                    user=target_user,
                    defaults={
                        'status': MeetingParticipant.STATUS_APPROVED,
                        'approved_at': timezone.now(),
                        'approved_by': request.user,
                    },
                )
                if participant_obj.status != MeetingParticipant.STATUS_APPROVED:
                    participant_obj.status = MeetingParticipant.STATUS_APPROVED
                    participant_obj.approved_at = timezone.now()
                    participant_obj.approved_by = request.user
                participant_obj.role = MeetingParticipant.ROLE_MANAGER
                participant_obj.save(update_fields=['status', 'role', 'approved_at', 'approved_by'])
        elif action == 'unset_manager':
            participant_obj = MeetingParticipant.objects.filter(meeting=meeting, user=target_user).first()
            if participant_obj and participant_obj.role == MeetingParticipant.ROLE_MANAGER:
                participant_obj.role = MeetingParticipant.ROLE_MEMBER
                participant_obj.save(update_fields=['role'])
        else:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': '알 수 없는 요청입니다.'}, status=400)
            return redirect(f"{reverse('meeting_participant_manage', kwargs={'meeting_id': meeting.id})}?modal=1")

        if is_ajax:
            return JsonResponse({'status': 'success'})
        return redirect(f"{reverse('meeting_participant_manage', kwargs={'meeting_id': meeting.id})}?modal=1")

    context = _build_participant_manage_context(meeting)
    context['is_modal'] = request.GET.get('modal') == '1'
    if request.GET.get('fragment') == '1':
        return render(request, 'pracapp/meeting_participant_manage_tables.html', context)
    return render(request, 'pracapp/meeting_participant_manage.html', context)


# ====================================================================
# Meeting Action Views
# ====================================================================

@login_required
def toggle_meeting_session_application(request, meeting_id):
    if request.method != 'POST':
        return redirect('meeting_detail', pk=meeting_id)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    if _is_final_locked(meeting):
        messages.error(request, _final_lock_message(meeting, '세션 지원 마감 상태를 변경할 수 없습니다.'))
        return redirect('meeting_detail', pk=meeting_id)
    membership = Membership.objects.filter(user=request.user, band=meeting.band, is_approved=True).first()
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '권한이 없습니다.')
        return redirect('meeting_detail', pk=meeting_id)

    meeting.is_session_application_closed = not meeting.is_session_application_closed
    meeting.save(update_fields=['is_session_application_closed'])
    if meeting.is_session_application_closed:
        messages.success(request, '세션 지원을 마감했습니다.')
    else:
        messages.success(request, '세션 지원 마감을 해제했습니다.')

    sort_option = request.POST.get('sort', '').strip() or request.GET.get('sort', '').strip()
    target = reverse('meeting_detail', kwargs={'pk': meeting_id})
    if sort_option:
        target = f"{target}?sort={sort_option}"
    return redirect(target)


@login_required
def reset_all_assignments(request, meeting_id):
    """
    [기능] 회의 내 모든 세션의 배정(Assignee)을 초기화
    """
    meeting = get_object_or_404(Meeting, id=meeting_id)
    target = _meeting_detail_target_with_state(request, meeting_id)
    if _is_final_locked(meeting):
        messages.error(request, _final_lock_message(meeting, '배정을 초기화할 수 없습니다.'))
        return redirect(target)
    if not meeting.is_session_application_closed:
        messages.error(request, '세션 지원 마감 이후에만 배정을 초기화할 수 있습니다.')
        return redirect(target)

    # 권한 체크 (리더만 가능)
    membership = Membership.objects.filter(user=request.user, band=meeting.band).first()
    if not membership or membership.role != 'LEADER':
        messages.error(request, '권한이 없습니다.')
        return redirect(target)

    if request.method == 'POST':
        # 회의에 속한 모든 곡 -> 모든 세션 -> assignee를 None으로 변경
        Session.objects.filter(song__meeting=meeting).update(assignee=None)
        messages.success(request, '모든 배정이 초기화되었습니다.')

    return redirect(target)


@login_required
def random_assign_all(request, meeting_id):
    """
    [기능] 모든 세션을 균형 기반으로 임의 배정
    - 우선: 세션 지원자(승인 참가자/관리자만 유효)
    - 보강: 지원자가 없으면 같은 악기(역할)의 승인 참가자 풀에서 배정
    - 같은 세션명(역할) 내에서 멤버별 배정 횟수가 최대한 고르게 되도록 우선순위 선택
      (동률 시 전체 배정 수가 적은 멤버 우선, 이후 랜덤)
    """
    target = _meeting_detail_target_with_state(request, meeting_id)
    if request.method != 'POST':
        return redirect(target)

    meeting = get_object_or_404(Meeting, id=meeting_id)
    if not meeting.is_session_application_closed:
        messages.error(request, '세션 지원 마감 이후에만 배정을 진행할 수 있습니다.')
        return redirect(target)
    membership = Membership.objects.filter(user=request.user, band=meeting.band).first()
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '권한이 없습니다.')
        return redirect(target)

    approved_participant_ids = _effective_meeting_participant_user_ids(meeting)
    sessions = list(Session.objects.filter(song__meeting=meeting).prefetch_related('applicant'))
    random.shuffle(sessions)

    role_member_pool = defaultdict(list)
    memberships = Membership.objects.filter(
        band=meeting.band,
        is_approved=True,
        user_id__in=approved_participant_ids,
    ).select_related('user')
    for mem in memberships:
        role_label = _role_label_of_instrument(mem.user.instrument)
        if role_label:
            role_member_pool[role_label].append(mem.user_id)

    # 역할(세션명)별/전체 배정 횟수 집계
    role_member_assigned_count = defaultdict(lambda: defaultdict(int))
    total_assigned_count = defaultdict(int)

    assigned_changes = 0
    for session in sessions:
        applicants = [
            uid for uid in session.applicant.values_list('id', flat=True)
            if uid in approved_participant_ids
        ]
        role_label = _role_label_of(session.name)
        candidates = applicants
        if not candidates and role_label:
            candidates = list(role_member_pool.get(role_label, []))

        if not candidates:
            continue

        role = role_label or (session.name or '')
        random.shuffle(candidates)

        # (역할 내 배정 수, 전체 배정 수)가 가장 작은 지원자를 우선 배정
        picked_user_id = min(
            candidates,
            key=lambda uid: (
                role_member_assigned_count[role][uid],
                total_assigned_count[uid],
            )
        )

        if session.assignee_id != picked_user_id:
            session.assignee_id = picked_user_id
            session.save(update_fields=['assignee_id'])
            assigned_changes += 1
        # 배정된 사람은 자동으로 지원자로도 포함한다.
        session.applicant.add(picked_user_id)
        role_member_assigned_count[role][picked_user_id] += 1
        total_assigned_count[picked_user_id] += 1

    return redirect(target)


@login_required
def reset_song_assignments(request, song_id):
    """
    [기능] 특정 곡의 배정만 초기화
    """
    song = get_object_or_404(Song, id=song_id)
    meeting_id = song.meeting.id
    target = _meeting_detail_target_with_state(request, meeting_id)
    if _is_final_locked(song.meeting):
        messages.error(request, _final_lock_message(song.meeting, '배정을 초기화할 수 없습니다.'))
        return redirect(target)
    if not song.meeting.is_session_application_closed:
        messages.error(request, '세션 지원 마감 이후에만 배정을 초기화할 수 있습니다.')
        return redirect(target)

    # 권한 체크
    membership = Membership.objects.filter(user=request.user, band=song.meeting.band).first()
    if not membership or membership.role != 'LEADER':
        messages.error(request, '권한이 없습니다.')
        return redirect(target)

    if request.method == 'POST':
        # 해당 곡의 세션들만 초기화
        song.sessions.update(assignee=None)
        messages.success(request, f"'{song.title}' 곡의 배정이 초기화되었습니다.")

    return redirect(target)


@login_required
def session_reject(request, session_id, user_id):
    """
    [기능] 특정 세션의 지원자 목록에서 유저를 제거 (거절)
    """
    session = get_object_or_404(Session, id=session_id)
    target_user = get_object_or_404(User, id=user_id)
    meeting = session.song.meeting
    if _is_final_locked(meeting):
        messages.error(request, _final_lock_message(meeting, '세션 지원/배정을 변경할 수 없습니다.'))
        return redirect('meeting_detail', pk=meeting.id)

    # 권한 체크 (리더/매니저만 가능)
    membership = Membership.objects.filter(user=request.user, band=meeting.band).first()
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '권한이 없습니다.')
        return redirect('meeting_detail', pk=meeting.id)

    # 지원자 목록에 있다면 제거
    if target_user in session.applicant.all():
        session.applicant.remove(target_user)

    return redirect('meeting_detail', pk=meeting.id)


@login_required
def meeting_delete(request, meeting_id):
    if request.method != 'POST':
        return redirect('meeting_detail', pk=meeting_id)

    meeting = get_object_or_404(Meeting.objects.select_related('band'), id=meeting_id)
    target = _meeting_detail_target_with_state(request, meeting_id)
    membership = _get_meeting_membership(meeting, request.user)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '권한이 없습니다.')
        return redirect(target)

    if _meeting_has_any_applicants(meeting):
        messages.error(request, '지원한 사람이 있는 선곡회의는 삭제할 수 없습니다.')
        return redirect(target)

    band_id = meeting.band_id
    meeting_title = meeting.title
    meeting.delete()
    messages.success(request, f"'{meeting_title}' 선곡회의를 삭제했습니다.")
    return redirect(f"{reverse('dashboard')}?band_id={band_id}")


# ====================================================================
# Practice Room Views
# ====================================================================

@login_required
def band_rooms(request, band_id):
    """
    합주실 목록 조회 및 생성 페이지
    """
    band = get_object_or_404(Band, id=band_id)

    membership = band.memberships.filter(user=request.user, is_approved=True).first()
    if not membership or membership.role not in ['LEADER', 'MANAGER']:
        return redirect('dashboard')

    rooms = PracticeRoom.objects.filter(band=band, is_temporary=False)

    # 합주실 생성 처리
    if request.method == 'POST':
        if membership.role not in ['LEADER', 'MANAGER']:
            messages.error(request, '합주실 생성은 밴드 리더/매니저만 가능합니다.')
            return redirect('band_rooms', band_id=band.id)
        form = PracticeRoomForm(request.POST)
        if form.is_valid():
            room = form.save(commit=False)
            room.band = band
            room.save()
            return redirect('band_rooms', band_id=band.id)
    else:
        form = PracticeRoomForm()

    context = {
        'band': band,
        'rooms': rooms,
        'form': form,
    }
    return render(request, 'pracapp/band_rooms.html', context)


@login_required
def meeting_room_create(request, meeting_id):
    """
    meeting_detail에서 진입하는 합주실 생성 + 합주기간 전체 불가능 시간 입력 페이지
    """
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if _is_final_locked(meeting):
        messages.error(request, _final_lock_message(meeting, '합주실 정보를 변경할 수 없습니다.'))
        return redirect('meeting_detail', pk=meeting_id)
    band = meeting.band

    membership = Membership.objects.filter(
        user=request.user,
        band=band,
        is_approved=True,
    ).first()
    if not membership:
        messages.error(request, '권한이 없습니다.')
        return redirect('meeting_detail', pk=meeting_id)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '합주실 생성은 밴드 리더/매니저만 가능합니다.')
        return redirect('meeting_detail', pk=meeting_id)

    if not meeting.practice_start_date or not meeting.practice_end_date:
        messages.error(request, '먼저 회의의 합주 시작일/종료일을 설정해주세요.')
        return redirect('meeting_detail', pk=meeting_id)

    if request.method == 'POST':
        form = RoomCreateForm(request.POST)
        blocks_json = request.POST.get('blocks_json', '{}')

        if form.is_valid():
            try:
                raw_map = json.loads(blocks_json) if blocks_json else {}
            except json.JSONDecodeError:
                messages.error(request, '시간표 데이터 형식이 올바르지 않습니다.')
                return render(request, 'pracapp/meeting_room_create.html', {
                    'meeting': meeting,
                    'is_edit': False,
                    'form': form,
                    'start_date': meeting.practice_start_date.strftime('%Y-%m-%d'),
                    'end_date': meeting.practice_end_date.strftime('%Y-%m-%d'),
                    'initial_blocks': '{}',
                })

            start_date = meeting.practice_start_date
            end_date = meeting.practice_end_date

            # 데이터 정리: { "YYYY-MM-DD": [{start, end}, ...], ... }
            cleaned_rows = []
            for date_str, blocks in raw_map.items():
                try:
                    d = datetime.date.fromisoformat(date_str)
                except ValueError:
                    continue
                if d < start_date or d > end_date:
                    continue
                if not isinstance(blocks, list):
                    continue
                for b in blocks:
                    try:
                        s_idx = int(b.get('start'))
                        e_idx = int(b.get('end'))
                    except (TypeError, ValueError, AttributeError):
                        continue
                    if s_idx < 18 or e_idx > 48 or s_idx >= e_idx:
                        continue
                    cleaned_rows.append((d, s_idx, e_idx))

            with transaction.atomic():
                room = form.save(commit=False)
                room.band = band
                room.save()

                room_blocks = [
                    RoomBlock(room=room, date=d, start_index=s_idx, end_index=e_idx)
                    for d, s_idx, e_idx in cleaned_rows
                ]
                if room_blocks:
                    RoomBlock.objects.bulk_create(room_blocks)

            return redirect('meeting_detail', pk=meeting_id)
    else:
        form = RoomCreateForm()

    return render(request, 'pracapp/meeting_room_create.html', {
        'meeting': meeting,
        'is_edit': False,
        'form': form,
        'start_date': meeting.practice_start_date.strftime('%Y-%m-%d'),
        'end_date': meeting.practice_end_date.strftime('%Y-%m-%d'),
        'initial_blocks': '{}',
    })


@login_required
def meeting_room_edit(request, meeting_id, room_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if _is_final_locked(meeting):
        messages.error(request, _final_lock_message(meeting, '합주실 정보를 변경할 수 없습니다.'))
        return redirect('meeting_detail', pk=meeting_id)
    room = get_object_or_404(_available_rooms_qs(meeting), id=room_id)

    membership = Membership.objects.filter(
        user=request.user,
        band=meeting.band,
        is_approved=True,
    ).first()
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        messages.error(request, '권한이 없습니다.')
        return redirect('meeting_detail', pk=meeting_id)

    if request.method == 'POST':
        form = RoomCreateForm(request.POST, instance=room)
        blocks_json = request.POST.get('blocks_json', '{}')
        if form.is_valid():
            try:
                raw_map = json.loads(blocks_json) if blocks_json else {}
            except json.JSONDecodeError:
                messages.error(request, '시간표 데이터 형식이 올바르지 않습니다.')
                return render(request, 'pracapp/meeting_room_create.html', {
                    'meeting': meeting,
                    'room': room,
                    'is_edit': True,
                    'form': form,
                    'start_date': meeting.practice_start_date.strftime('%Y-%m-%d'),
                    'end_date': meeting.practice_end_date.strftime('%Y-%m-%d'),
                    'initial_blocks': '{}',
                })

            start_date = meeting.practice_start_date
            end_date = meeting.practice_end_date

            locked_slots_by_date = defaultdict(set)
            locked_blocks = RoomBlock.objects.filter(
                room=room,
                date__range=[start_date, end_date],
                source_meeting__isnull=False,
            )
            for lb in locked_blocks:
                for slot in range(int(lb.start_index), int(lb.end_index)):
                    locked_slots_by_date[lb.date].add(slot)

            cleaned_rows = []
            stripped_locked_overlap = False
            for date_str, blocks in raw_map.items():
                try:
                    d = datetime.date.fromisoformat(date_str)
                except ValueError:
                    continue
                if d < start_date or d > end_date:
                    continue
                if not isinstance(blocks, list):
                    continue
                for b in blocks:
                    try:
                        s_idx = int(b.get('start'))
                        e_idx = int(b.get('end'))
                    except (TypeError, ValueError, AttributeError):
                        continue
                    if s_idx < 18 or e_idx > 48 or s_idx >= e_idx:
                        continue
                    locked_slots = locked_slots_by_date.get(d, set())
                    if not locked_slots:
                        cleaned_rows.append((d, s_idx, e_idx))
                        continue
                    has_overlap = any(slot in locked_slots for slot in range(s_idx, e_idx))
                    if has_overlap:
                        stripped_locked_overlap = True
                    cur = s_idx
                    while cur < e_idx:
                        while cur < e_idx and cur in locked_slots:
                            cur += 1
                        seg_start = cur
                        while cur < e_idx and cur not in locked_slots:
                            cur += 1
                        if seg_start < cur:
                            cleaned_rows.append((d, seg_start, cur))

            with transaction.atomic():
                form.save()
                RoomBlock.objects.filter(
                    room=room,
                    date__range=[start_date, end_date],
                    source_meeting__isnull=True,
                ).delete()
                room_blocks = [
                    RoomBlock(room=room, date=d, start_index=s_idx, end_index=e_idx)
                    for d, s_idx, e_idx in cleaned_rows
                ]
                if room_blocks:
                    RoomBlock.objects.bulk_create(room_blocks)
            if stripped_locked_overlap:
                messages.warning(request, '확정된 합주 일정으로 생성된 불가 시간은 수정할 수 없습니다.')

            return redirect('meeting_detail', pk=meeting_id)
    else:
        form = RoomCreateForm(instance=room)

    # 기존 블록을 날짜별 JSON으로 구성
    initial_map = {}
    if meeting.practice_start_date and meeting.practice_end_date:
        for b in RoomBlock.objects.filter(
            room=room,
            date__range=[meeting.practice_start_date, meeting.practice_end_date],
        ):
            d_str = b.date.strftime('%Y-%m-%d')
            initial_map.setdefault(d_str, []).append({'start': b.start_index, 'end': b.end_index})

    return render(request, 'pracapp/meeting_room_create.html', {
        'meeting': meeting,
        'room': room,
        'is_edit': True,
        'form': form,
        'start_date': meeting.practice_start_date.strftime('%Y-%m-%d'),
        'end_date': meeting.practice_end_date.strftime('%Y-%m-%d'),
        'initial_blocks': json.dumps(initial_map),
    })
