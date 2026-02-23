# pracapp/views/home_views.py

from django.views.generic import TemplateView

from pracapp.models import Band, MemberAvailability, Membership


class HomeView(TemplateView):
    template_name = 'pracapp/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        if user.is_authenticated:
            my_band_qs = Band.objects.filter(
                memberships__user=user,
                memberships__is_approved=True
            ).distinct().order_by('name')
            context['my_band'] = my_band_qs
            context['has_schedule'] = MemberAvailability.objects.filter(user=user).exists()
            context['editable_band_ids'] = set(
                Membership.objects.filter(
                    user=user,
                    is_approved=True,
                    role__in=['LEADER', 'MANAGER'],
                ).values_list('band_id', flat=True)
            )

        else:
            context['my_band'] = None
            context['has_schedule'] = False
            context['editable_band_ids'] = set()

        return context
