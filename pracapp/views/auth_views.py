# pracapp/views/auth_views.py
from django.urls import reverse_lazy
from django.views.generic import CreateView
from ..forms import BandUserCreationForm


class UserCreateView(CreateView):
    form_class = BandUserCreationForm
    template_name = 'registration/signup.html'
    success_url = reverse_lazy('login')
