import calendar
import datetime

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView
from django.db.models import Q

from ..forms import BandCreateForm, MemberEnlistForm
from ..models import Band, Membership, MeetingParticipant

DEMO_BAND_NAME_PREFIXES = (
    '[데모WORK]',
    '[데모TEMPLATE]',
    '[데모CACHE]',
    '[체험DB]',
    '[데모]',
)


def _build_semester_preset_ranges(base_year: int):
    winter_end_day = calendar.monthrange(base_year + 1, 2)[1]
    return [
        ('SEMESTER_1', '1학기', datetime.date(base_year, 3, 2), datetime.date(base_year, 6, 21)),
        ('SUMMER_BREAK', '여름방학', datetime.date(base_year, 6, 22), datetime.date(base_year, 8, 31)),
        ('SEMESTER_2', '2학기', datetime.date(base_year, 9, 1), datetime.date(base_year, 12, 20)),
        ('WINTER_BREAK', '겨울방학', datetime.date(base_year, 12, 21), datetime.date(base_year + 1, 2, winter_end_day)),
    ]


def _resolve_meeting_preset(meeting):
    start_date = getattr(meeting, 'practice_start_date', None)
    end_date = getattr(meeting, 'practice_end_date', None)
    if not start_date or not end_date:
        return None
    candidate_years = {start_date.year - 1, start_date.year, end_date.year}
    for year in sorted(candidate_years):
        for key, label, p_start, p_end in _build_semester_preset_ranges(year):
            # 프리셋과 정확히 일치할 때뿐 아니라, 프리셋 기간 안에 완전히 포함되어도 같은 분류로 본다.
            if p_start <= start_date and end_date <= p_end:
                return {'key': key, 'label': label}
    return None


class BandCreateView(LoginRequiredMixin, CreateView):
    model = Band
    form_class = BandCreateForm
    template_name = 'pracapp/band_form.html'

    def form_valid(self, form):
        response = super().form_valid(form)

        Membership.objects.create(
            user=self.request.user,
            band=self.object,
            role='LEADER',
            is_approved=True
            )

        return response

    def get_success_url(self):
        base_url = reverse_lazy('dashboard')
        current_band_id = self.object.id
        return f'{base_url}?band_id={current_band_id}'


class BandUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Band
    form_class = BandCreateForm
    template_name = 'pracapp/band_form.html'

    def test_func(self):
        band = self.get_object()
        return Membership.objects.filter(
            user=self.request.user,
            band=band,
            is_approved=True,
            role__in=['LEADER', 'MANAGER'],
        ).exists()

    def get_success_url(self):
        base_url = reverse_lazy('dashboard')
        current_band_id = self.object.id
        return f'{base_url}?band_id={current_band_id}'


class BandListView(LoginRequiredMixin, ListView):
    model = Band
    template_name = 'pracapp/band_list.html'
    context_object_name = 'searched_band_list'

    def get_queryset(self):
        q = self.request.GET.get('band_search')
        queryset = Band.objects.filter(is_public=True)
        demo_name_q = Q()
        for prefix in DEMO_BAND_NAME_PREFIXES:
            demo_name_q |= Q(name__startswith=prefix)
        if demo_name_q:
            queryset = queryset.exclude(demo_name_q)
        if q:
            return queryset.filter(name__icontains=q)
        return queryset


class MemberEnlistView(LoginRequiredMixin, CreateView):
    model = Membership
    form_class = MemberEnlistForm
    template_name = 'pracapp/member_enlist.html'
    success_url = reverse_lazy('band_list')

    @property
    def target_band(self):
        return get_object_or_404(Band, id=self.kwargs['band_id'])

    def form_valid(self, form):
        band = self.target_band
        user = self.request.user
        message_text = form.cleaned_data.get('message')
        membership, created = Membership.objects.get_or_create(
            band=band,
            user=user,
            defaults={'message': message_text},
        )
        self.object = membership
        if created:
            messages.success(self.request, '가입 신청이 접수되었습니다.')
        elif membership.is_approved:
            messages.info(self.request, '이미 가입된 밴드입니다.')
        else:
            if message_text:
                membership.message = message_text
                membership.save(update_fields=['message'])
            messages.info(self.request, '이미 가입 승인 대기 중입니다.')
        return redirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['target_band'] = self.target_band
        context['leader'] = self.target_band.leader

        return context


class DashboardView(LoginRequiredMixin, ListView):
    model = Band
    template_name = 'pracapp/dashboard.html'
    context_object_name = 'my_bands'

    def get_queryset(self):
        return Band.objects.filter(
            memberships__user=self.request.user,
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        my_bands = self.get_queryset()

        selected_band_id = self.request.GET.get('band_id')
        selected_band = None

        if selected_band_id:
            selected_band = my_bands.filter(id=selected_band_id).first()
        if not selected_band:
            selected_band = my_bands.first()

        if selected_band:
            context['selected_band'] = selected_band

            my_membership = selected_band.memberships.filter(user=self.request.user).first()
            is_approved = bool(my_membership and my_membership.is_approved)
            is_manager = bool(my_membership and my_membership.role in ['LEADER', 'MANAGER'])
            is_leader = bool(my_membership and my_membership.role == 'LEADER')
            context['is_approved'] = is_approved
            context['is_manager'] = is_manager
            context['is_leader'] = is_leader

            if is_approved:
                context['member'] = selected_band.memberships.filter(is_approved=True)
                meetings_qs = selected_band.meetings.order_by('-created_at')
                if not is_manager:
                    participant_meeting_ids = MeetingParticipant.objects.filter(
                        user=self.request.user,
                        status__in=[MeetingParticipant.STATUS_PENDING, MeetingParticipant.STATUS_APPROVED],
                    ).values_list('meeting_id', flat=True)
                    meetings_qs = meetings_qs.filter(
                        Q(visibility='LISTED') |
                        Q(id__in=participant_meeting_ids)
                    ).distinct()
                meetings = list(meetings_qs)
                for m in meetings:
                    preset = _resolve_meeting_preset(m)
                    m.schedule_preset_key = preset['key'] if preset else ''
                    m.schedule_preset_label = preset['label'] if preset else ''
                context['meeting'] = meetings
                if is_manager:
                    context['enlist'] = selected_band.memberships.filter(is_approved=False)
            else:
                context['member'] = None
                context['meeting'] = None
                context['enlist'] = None

        return context


@login_required
def approve_member(request, membership_id):
    membership = get_object_or_404(Membership, id=membership_id)
    band = membership.band

    if not Membership.objects.filter(user=request.user, band=band, role__in=['LEADER', 'MANAGER']).exists():
        return redirect('dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'approve':
            membership.is_approved = True
            membership.approval_notified = False
            membership.save(update_fields=['is_approved', 'approval_notified'])
        elif action == 'reject':
            membership.delete()

    base_url = reverse_lazy('dashboard')
    current_band_id = band.id

    return redirect(f'{base_url}?band_id={current_band_id}')


@login_required
def manage_member(request, pk):
    target_member = get_object_or_404(Membership, pk=pk)
    band = target_member.band
    my_membership = Membership.objects.filter(user=request.user, band=band).first()

    base_url = reverse_lazy('dashboard')
    current_band_id = band.id

    if not my_membership or my_membership.role != 'LEADER':
        return redirect(f'{base_url}?band_id={current_band_id}')

    if request.method == 'POST':
        action = request.POST.get('action')

        if target_member.role == 'LEADER':
            pass
        elif target_member.user == request.user:
            pass

        else:
            if action == 'kick':
                target_member.delete()
            elif action == 'promote':
                target_member.role = 'MANAGER'
                target_member.save()
            elif action == 'demote':
                target_member.role = 'MEMBER'
                target_member.save()

    return redirect(f'{base_url}?band_id={current_band_id}')
