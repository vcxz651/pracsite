from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import CreateView, UpdateView, DeleteView

from ..forms import SongForm
from ..models import Song, Session, User, Membership, MeetingParticipant, SongComment
from .. import utils
from ._meeting_common import (
    is_final_locked as common_is_final_locked,
    final_lock_message as common_final_lock_message,
    final_lock_prefix as common_final_lock_prefix,
    final_lock_state_message as common_final_lock_state_message,
    get_approved_membership as common_get_approved_membership,
    is_manager_membership as common_is_manager_membership,
    is_meeting_manager_participant as common_is_meeting_manager_participant,
    has_meeting_manager_permission as common_has_meeting_manager_permission,
)


def _is_final_locked(meeting):
    return common_is_final_locked(meeting, include_released=True)


def _final_lock_prefix(meeting):
    return common_final_lock_prefix(meeting)


def _final_lock_message(meeting, action_text):
    return common_final_lock_message(meeting, action_text)


def _final_lock_state_message(meeting):
    return common_final_lock_state_message(meeting)


def _is_meeting_participant_approved(meeting, user, membership=None):
    if membership and membership.role in ['LEADER', 'MANAGER']:
        return True
    if Membership.objects.filter(
        user=user,
        band=meeting.band,
        is_approved=True,
        role__in=['LEADER', 'MANAGER'],
    ).exists():
        return True
    return MeetingParticipant.objects.filter(
        meeting=meeting,
        user=user,
        status=MeetingParticipant.STATUS_APPROVED,
    ).exists()


def _meeting_visible_user_ids(meeting):
    approved_ids = set(
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
    return approved_ids | manager_ids


def _get_approved_membership(user, band):
    return common_get_approved_membership(user, band)


def _is_manager_membership(membership):
    return common_is_manager_membership(membership)


def _is_meeting_manager_participant(meeting, user):
    return common_is_meeting_manager_participant(meeting, user)


def _has_meeting_manager_permission(meeting, user, membership=None):
    return common_has_meeting_manager_permission(meeting, user, membership=membership)


def _role_label_of(session_name):
    if not session_name:
        return None
    n = str(session_name).strip().lower()
    normalized = ''.join(ch for ch in n if ch.isalnum())
    if n.startswith('vocal') or n.startswith('보컬') or normalized in {'v'}:
        return '보컬'
    if n.startswith('guitar') or n.startswith('기타') or normalized in {'g', 'g1', 'g2'}:
        return '기타'
    if n.startswith('bass') or n.startswith('베이스') or normalized in {'b'}:
        return '베이스'
    if n.startswith('drum') or n.startswith('드럼') or normalized in {'d'}:
        return '드럼'
    if n.startswith('keyboard') or n.startswith('키보드') or n.startswith('건반') or normalized in {'k'}:
        return '키보드'
    return None


def _role_label_of_instrument(instrument):
    if not instrument:
        return None
    n = str(instrument).strip().lower()
    normalized = ''.join(ch for ch in n if ch.isalnum())
    if n.startswith('vocal') or n.startswith('보컬') or normalized in {'v'}:
        return '보컬'
    if n.startswith('guitar') or n.startswith('기타') or normalized in {'g', 'g1', 'g2'}:
        return '기타'
    if n.startswith('bass') or n.startswith('베이스') or normalized in {'b'}:
        return '베이스'
    if n.startswith('drum') or n.startswith('드럼') or normalized in {'d'}:
        return '드럼'
    if n.startswith('keyboard') or n.startswith('키보드') or n.startswith('건반') or normalized in {'k'}:
        return '키보드'
    return None


#####################################################
###################### S O N G ######################
#####################################################
class SongCreateView(LoginRequiredMixin, CreateView):
    model = Song
    form_class = SongForm
    template_name = 'pracapp/song_form.html'

    def meeting_id(self):
        return self.kwargs.get('meeting_id')

    def get_success_url(self):
        return reverse('meeting_detail', kwargs={'pk': self.meeting_id()})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meeting_id'] = self.meeting_id()
        return context

    def dispatch(self, request, *args, **kwargs):
        from ..models import Meeting
        meeting = get_object_or_404(Meeting, id=self.meeting_id())
        membership = Membership.objects.filter(user=request.user, band=meeting.band, is_approved=True).first()
        if not membership:
            messages.error(request, '권한이 없습니다.')
            return redirect('meeting_detail', pk=meeting.id)
        if not _is_meeting_participant_approved(meeting, request.user, membership=membership):
            messages.error(request, '이 선곡회의 참가 승인 후 곡을 등록할 수 있습니다.')
            return redirect('meeting_detail', pk=meeting.id)
        if _is_final_locked(meeting):
            messages.error(request, _final_lock_message(meeting, '곡/세션 정보를 변경할 수 없습니다.'))
            return redirect('meeting_detail', pk=meeting.id)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        from ..models import Meeting
        meeting = get_object_or_404(Meeting, id=self.meeting_id())
        form.instance.author = self.request.user
        form.instance.meeting = meeting
        response = super().form_valid(form)

        selected_sessions = form.cleaned_data.get('needed_session')
        sheet_sessions = set(form.cleaned_data.get('sheet_sessions') or [])
        for s_name in selected_sessions:
            Session.objects.create(
                song=self.object,
                name=s_name,
                has_sheet=(s_name in sheet_sessions),
            )

        extra_data = form.cleaned_data.get('extra_session')
        if extra_data:
            names = [name.strip() for name in extra_data.split(',') if name.strip()]
            for e_name in names:
                Session.objects.create(
                    song=self.object,
                    name=e_name,
                    is_extra=True,
                    has_sheet=(e_name in sheet_sessions),
                )

        return response


class SongUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Song
    form_class = SongForm
    template_name = 'pracapp/song_form.html'

    @property
    def meeting_id(self):
        obj = self.get_object()
        return obj.meeting.id

    def get_success_url(self):
        return reverse('meeting_detail', kwargs={'pk': self.meeting_id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meeting_id'] = self.meeting_id
        return context

    def get_initial(self):
        initial = super().get_initial()
        initial['needed_session'] = list(self.object.current_needed_session)
        initial['extra_session'] = ', '.join(self.object.current_extra_session)
        initial['sheet_sessions'] = ','.join(
            self.object.sessions.filter(has_sheet=True).values_list('name', flat=True)
        )
        return initial

    def dispatch(self, request, *args, **kwargs):
        song = self.get_object()
        if _is_final_locked(song.meeting):
            messages.error(request, _final_lock_message(song.meeting, '곡/세션 정보를 변경할 수 없습니다.'))
            return redirect('meeting_detail', pk=song.meeting.id)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # 1. 일단 곡 기본 정보(제목, 아티스트 등) 저장
        response = super().form_valid(form)

        # 2. 세션 정보 동기화는 유틸에게 위임 (깔끔!)
        utils.sync_song_sessions(
            song=self.object,
            new_needed_list=form.cleaned_data.get('needed_session', []),
            new_extra_str=form.cleaned_data.get('extra_session', '')
        )

        # 3. 세션별 악보 유무 반영
        sheet_sessions = set(form.cleaned_data.get('sheet_sessions') or [])
        for sess in self.object.sessions.all():
            should_have = sess.name in sheet_sessions
            if bool(sess.has_sheet) != should_have:
                sess.has_sheet = should_have
                sess.save(update_fields=['has_sheet'])

        return response

    def test_func(self):
        return self.get_object().author == self.request.user

    def handle_no_permission(self):
        messages.error(self.request, '수정 권한이 없습니다.')
        return redirect('meeting_detail', pk=self.meeting_id)


class SongDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = Song
    template_name = 'pracapp/song_confirm_delete.html'

    def meeting_id(self):
        return self.object.meeting.id

    def get_success_url(self):
        base_url = reverse('meeting_detail', kwargs={'pk': self.meeting_id()})
        sort_option = self.request.POST.get('sort') or self.request.GET.get('sort')
        if sort_option:
            return f"{base_url}?sort={sort_option}"
        return base_url

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['meeting_id'] = self.meeting_id()
        return context

    def dispatch(self, request, *args, **kwargs):
        song = self.get_object()
        if _is_final_locked(song.meeting):
            messages.error(request, _final_lock_message(song.meeting, '곡/세션 정보를 변경할 수 없습니다.'))
            return redirect('meeting_detail', pk=song.meeting.id)
        return super().dispatch(request, *args, **kwargs)

    def test_func(self):
        song = self.get_object()
        if song.author == self.request.user:
            return True
        membership = Membership.objects.filter(user=self.request.user, band=song.meeting.band).first()
        return bool(membership and membership.role == 'LEADER')

    def handle_no_permission(self):
        messages.error(self.request, '삭제 권한이 없습니다.')
        return redirect('meeting_detail', pk=self.meeting_id())


@login_required
def session_assign(request, session_id, user_id):
    session = get_object_or_404(Session, id=session_id)
    target_user = get_object_or_404(User, id=user_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    meeting = session.song.meeting

    band = meeting.band
    if _is_final_locked(meeting):
        msg = _final_lock_message(meeting, '세션 배정을 변경할 수 없습니다.')
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=409)
        messages.error(request, msg)
        target = reverse('meeting_detail', kwargs={'pk': meeting.id})
        sort_option = request.GET.get('sort', '').strip()
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)
    if not meeting.is_session_application_closed:
        msg = '세션 지원 마감 이후에만 배정할 수 있습니다.'
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=409)
        messages.error(request, msg)
        target = reverse('meeting_detail', kwargs={'pk': meeting.id})
        sort_option = request.GET.get('sort', '').strip()
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)
    membership = _get_approved_membership(request.user, band)

    sort_option = request.GET.get('sort', '').strip()
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '세션 확정은 리더/매니저만 가능합니다.'}, status=403)
        messages.error(request, '세션 확정은 리더/매니저만 가능합니다.')
        target = reverse('meeting_detail', kwargs={'pk': meeting.id})
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)

    if not _is_meeting_participant_approved(session.song.meeting, target_user):
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '참가 승인된 멤버만 배정할 수 있습니다.'}, status=409)
        messages.error(request, '참가 승인된 멤버만 배정할 수 있습니다.')
        target = reverse('meeting_detail', kwargs={'pk': meeting.id})
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)

    applicant_added = False
    if session.assignee == target_user:
        session.assignee = None
        session.save()
    else:
        session.assignee = target_user
        session.save()
        # 배정된 사람은 자동으로 지원자로도 포함한다.
        applicant_added = not session.applicant.filter(id=target_user.id).exists()
        session.applicant.add(target_user)
    if is_ajax:
        assignee_id = str(session.assignee_id) if session.assignee_id else None
        assignee_name = (session.assignee.realname or session.assignee.username) if session.assignee else None
        return JsonResponse({
            'status': 'success',
            'session_id': str(session.id),
            'assignee_id': assignee_id,
            'assignee_name': assignee_name,
            'applicant_count': int(session.applicant.count()),
            'applicant_added': applicant_added,
        })
    target = reverse('meeting_detail', kwargs={'pk': meeting.id})
    if sort_option:
        target = f"{target}?sort={sort_option}"
    return redirect(target)


@login_required
def session_manage_applicant(request, session_id, user_id):
    session = get_object_or_404(Session, id=session_id)
    target_user = get_object_or_404(User, id=user_id)
    meeting = session.song.meeting
    band = meeting.band
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    membership = _get_approved_membership(request.user, band)

    sort_option = request.POST.get('sort', '').strip() or request.GET.get('sort', '').strip()
    target = reverse('meeting_detail', kwargs={'pk': meeting.id})
    if sort_option:
        target = f"{target}?sort={sort_option}"
    if _is_final_locked(meeting):
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': _final_lock_message(meeting, '세션 지원/배정을 변경할 수 없습니다.')}, status=409)
        messages.error(request, _final_lock_message(meeting, '세션 지원/배정을 변경할 수 없습니다.'))
        return redirect(target)

    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
        messages.error(request, '권한이 없습니다.')
        return redirect(target)

    if not Membership.objects.filter(user=target_user, band=band, is_approved=True).exists():
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '밴드 승인 멤버만 추가할 수 있습니다.'}, status=409)
        messages.error(request, '밴드 승인 멤버만 추가할 수 있습니다.')
        return redirect(target)
    if not _is_meeting_participant_approved(meeting, target_user):
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '선곡회의 참가 승인된 멤버만 지원자에 포함할 수 있습니다.'}, status=409)
        messages.error(request, '선곡회의 참가 승인된 멤버만 지원자에 포함할 수 있습니다.')
        return redirect(target)

    if target_user in session.applicant.all() and session.assignee_id == target_user.id:
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '배정된 세션은 지원을 취소할 수 없습니다.'}, status=409)
        messages.error(request, '배정된 세션은 지원을 취소할 수 없습니다.')
        return redirect(target)

    if target_user in session.applicant.all():
        session.applicant.remove(target_user)
    else:
        session.applicant.add(target_user)
    if is_ajax:
        return JsonResponse({
            'status': 'success',
            'session_id': str(session.id),
            'user_id': str(target_user.id),
            'is_applicant': bool(session.applicant.filter(id=target_user.id).exists()),
            'applicant_count': int(session.applicant.count()),
        })
    return redirect(target)


@login_required
def session_manage_data(request, session_id):
    session = get_object_or_404(Session, id=session_id)
    meeting = session.song.meeting
    band = meeting.band
    if _is_final_locked(meeting):
        return JsonResponse({'status': 'error', 'message': _final_lock_message(meeting, '세션 지원/배정을 변경할 수 없습니다.')}, status=409)
    membership = _get_approved_membership(request.user, band)
    if not _has_meeting_manager_permission(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    sort_option = request.GET.get('sort', '').strip()
    session_role_label = _role_label_of(session.name)
    visible_user_ids = _meeting_visible_user_ids(meeting)
    members_qs = User.objects.filter(
        user_memberships__band=band,
        user_memberships__is_approved=True,
    ).filter(
        id__in=visible_user_ids,
    ).distinct().order_by('realname', 'username')
    applicant_ids = set(str(uid) for uid in session.applicant.values_list('id', flat=True))
    assignee_id = str(session.assignee_id) if session.assignee_id else None

    rows = []
    for member in members_qs:
        manage_url = reverse('session_manage_applicant', kwargs={'session_id': session.id, 'user_id': member.id})
        assign_url = reverse('session_assign', kwargs={'session_id': session.id, 'user_id': member.id})
        if sort_option:
            assign_url = f"{assign_url}?sort={sort_option}"
        member_role_label = (
            _role_label_of_instrument(getattr(member, 'instrument', '') or '')
            or _role_label_of_instrument(getattr(member, 'instrument_detail', '') or '')
        )
        rows.append({
            'id': str(member.id),
            'realname': member.realname,
            'username': member.username,
            'role_label': member_role_label or '',
            'is_same_role': bool(session_role_label and member_role_label == session_role_label),
            'is_applicant': str(member.id) in applicant_ids,
            'is_assignee': assignee_id == str(member.id),
            'has_assignee': bool(assignee_id),
            'manage_url': manage_url,
            'assign_url': assign_url,
        })

    return JsonResponse({
        'status': 'success',
        'song_title': session.song.title,
        'role': session.name,
        'session_role_label': session_role_label or '',
        'session_id': str(session.id),
        'sort': sort_option,
        'members': rows,
    })


@login_required
def session_apply(request, session_id):
    session = get_object_or_404(Session, id=session_id)
    song = session.song
    meeting = song.meeting
    meeting_id = meeting.id
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    sort_option = request.POST.get('sort', '').strip() or request.GET.get('sort', '').strip()
    if _is_final_locked(meeting):
        msg = _final_lock_message(meeting, '세션 지원을 변경할 수 없습니다.')
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=409)
        messages.error(request, msg)
        target = reverse('meeting_detail', kwargs={'pk': meeting_id})
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)
    membership = _get_approved_membership(request.user, meeting.band)
    if not membership:
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
        target = reverse('meeting_detail', kwargs={'pk': meeting_id})
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)
    if not _is_meeting_participant_approved(meeting, request.user, membership=membership):
        msg = '이 선곡회의 참가 승인 후 세션 지원이 가능합니다.'
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=409)
        messages.error(request, msg)
        target = reverse('meeting_detail', kwargs={'pk': meeting_id})
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)

    if meeting.is_session_application_closed and (not _has_meeting_manager_permission(meeting, request.user, membership=membership)):
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '세션 지원이 마감되었습니다.'}, status=409)
        messages.error(request, '세션 지원이 마감되었습니다.')
        target = reverse('meeting_detail', kwargs={'pk': meeting_id})
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)

    if (song.is_closed or session.is_closed) and not request.user.is_staff:
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': '현재 이 세션은 변경할 수 없습니다.'}, status=409)
        target = reverse('meeting_detail', kwargs={'pk': meeting_id})
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)

    if session.assignee_id == request.user.id and session.applicant.filter(id=request.user.id).exists():
        msg = '배정된 세션은 지원을 취소할 수 없습니다.'
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=409)
        messages.error(request, msg)
        target = reverse('meeting_detail', kwargs={'pk': meeting_id})
        if sort_option:
            target = f"{target}?sort={sort_option}"
        return redirect(target)

    if session.applicant.filter(id=request.user.id).exists():
        session.applicant.remove(request.user)
        applied = False
    else:
        session.applicant.add(request.user)
        applied = True

    applicant_count = session.applicant.count()
    if is_ajax:
        return JsonResponse({
            'status': 'success',
            'applied': applied,
            'applicant_count': applicant_count,
            'session_id': str(session.id),
        })

    target = reverse('meeting_detail', kwargs={'pk': meeting_id})
    if sort_option:
        target = f"{target}?sort={sort_option}"
    return redirect(target)


@login_required
def song_applicants_data(request, song_id):
    song = get_object_or_404(Song.objects.select_related('meeting__band'), id=song_id)
    meeting = song.meeting
    band = meeting.band
    membership = _get_approved_membership(request.user, band)
    if not membership:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    if not _is_meeting_participant_approved(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '선곡회의 참가 승인 후 확인할 수 있습니다.'}, status=403)

    sort_option = request.GET.get('sort', '').strip()
    can_assign = (
        _has_meeting_manager_permission(meeting, request.user, membership=membership)
        and meeting.is_session_application_closed
        and (not _is_final_locked(meeting))
    )
    approved_participant_ids = _meeting_visible_user_ids(meeting)
    sessions = (
        song.sessions.select_related('assignee')
        .prefetch_related('applicant')
        .order_by('name')
    )

    rows = []
    for sess in sessions:
        applicants = [
            a for a in sess.applicant.all().order_by('realname', 'username')
            if a.id in approved_participant_ids
        ]
        if not applicants:
            continue
        assignee_id = str(sess.assignee_id) if sess.assignee_id else None
        applicant_rows = []
        for applicant in applicants:
            assign_url = ''
            if can_assign:
                assign_url = reverse('session_assign', kwargs={'session_id': sess.id, 'user_id': applicant.id})
                if sort_option:
                    assign_url = f"{assign_url}?sort={sort_option}"
            applicant_rows.append({
                'id': str(applicant.id),
                'realname': applicant.realname,
                'username': applicant.username,
                'is_assigned': assignee_id == str(applicant.id),
                'has_assignee': bool(assignee_id),
                'assign_url': assign_url,
            })

        rows.append({
            'session_id': str(sess.id),
            'has_assignee': bool(assignee_id),
            'assignee_id': assignee_id,
            'applicants': applicant_rows,
        })

    return JsonResponse({
        'status': 'success',
        'song_id': str(song.id),
        'can_assign': can_assign,
        'sessions': rows,
    })


def _comment_author_name(user):
    return str(getattr(user, 'realname', '') or getattr(user, 'username', '') or '알 수 없음')


def _serialize_song_comment(comment, *, can_delete=False):
    created_local = timezone.localtime(comment.created_at)
    return {
        'id': str(comment.id),
        'author_id': str(comment.author_id),
        'author_name': _comment_author_name(comment.author),
        'content': str(comment.content or ''),
        'created_at': created_local.isoformat(),
        'created_text': created_local.strftime('%m/%d %H:%M'),
        'can_delete': bool(can_delete),
        'delete_url': reverse('song_comment_delete', kwargs={'comment_id': comment.id}),
    }


@login_required
def song_comments_data(request, song_id):
    if request.method != 'GET':
        return JsonResponse({'status': 'error', 'message': '잘못된 요청입니다.'}, status=405)

    song = get_object_or_404(Song.objects.select_related('meeting__band'), id=song_id)
    meeting = song.meeting
    membership = _get_approved_membership(request.user, meeting.band)
    if not membership:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    if not _is_meeting_participant_approved(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '선곡회의 참가 승인 후 확인할 수 있습니다.'}, status=403)

    can_manage = _has_meeting_manager_permission(meeting, request.user, membership=membership)
    total_count = SongComment.objects.filter(song=song).count()
    recent_comments_desc = list(
        SongComment.objects.filter(song=song)
        .select_related('author')
        .order_by('-created_at')[:120]
    )
    comments = list(reversed(recent_comments_desc))
    payload = [
        _serialize_song_comment(
            c,
            can_delete=(can_manage or c.author_id == request.user.id),
        )
        for c in comments
    ]
    return JsonResponse({
        'status': 'success',
        'song_id': str(song.id),
        'comment_count': int(total_count),
        'comments': payload,
    })


@login_required
def song_comment_create(request, song_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '잘못된 요청입니다.'}, status=405)

    song = get_object_or_404(Song.objects.select_related('meeting__band'), id=song_id)
    meeting = song.meeting
    membership = _get_approved_membership(request.user, meeting.band)
    if not membership:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    if not _is_meeting_participant_approved(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '선곡회의 참가 승인 후 댓글 작성이 가능합니다.'}, status=403)

    content = str(request.POST.get('content') or '').strip()
    if not content:
        return JsonResponse({'status': 'error', 'message': '댓글 내용을 입력해주세요.'}, status=400)
    if len(content) > 500:
        return JsonResponse({'status': 'error', 'message': '댓글은 500자 이내로 입력해주세요.'}, status=400)

    comment = SongComment.objects.create(
        song=song,
        author=request.user,
        content=content,
    )
    comment_count = SongComment.objects.filter(song=song).count()
    return JsonResponse({
        'status': 'success',
        'song_id': str(song.id),
        'comment_count': int(comment_count),
        'comment': _serialize_song_comment(comment, can_delete=True),
    })


@login_required
def song_comment_delete(request, comment_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '잘못된 요청입니다.'}, status=405)

    comment = get_object_or_404(
        SongComment.objects.select_related('song__meeting__band', 'author'),
        id=comment_id,
    )
    meeting = comment.song.meeting
    membership = _get_approved_membership(request.user, meeting.band)
    if not membership:
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)
    if not _is_meeting_participant_approved(meeting, request.user, membership=membership):
        return JsonResponse({'status': 'error', 'message': '권한이 없습니다.'}, status=403)

    can_manage = _has_meeting_manager_permission(meeting, request.user, membership=membership)
    if not can_manage and comment.author_id != request.user.id:
        return JsonResponse({'status': 'error', 'message': '삭제 권한이 없습니다.'}, status=403)

    song_id = str(comment.song_id)
    comment.delete()
    comment_count = SongComment.objects.filter(song_id=song_id).count()
    return JsonResponse({
        'status': 'success',
        'song_id': song_id,
        'comment_count': int(comment_count),
    })
