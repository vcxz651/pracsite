# pracapp/views/auth_views.py
import hashlib
from urllib.parse import urlparse

from django.contrib.auth import views as auth_views
from django.core.cache import cache
from django.urls import reverse_lazy
from django.views.generic import CreateView

from ..forms import BandUserCreationForm


class RateLimitedLoginView(auth_views.LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    INTRO_MODAL_SESSION_KEY = 'show_intro_video_modal'
    MAX_ATTEMPTS = 7
    WINDOW_SECONDS = 15 * 60
    LOCK_SECONDS = 15 * 60
    THROTTLE_ERROR_MESSAGE = '로그인 시도가 너무 많습니다. 15분 후 다시 시도해주세요.'

    def dispatch(self, request, *args, **kwargs):
        self._throttle_rejected = False
        if request.method == 'POST':
            ip = self._client_ip(request)
            username = self._raw_username(request)
            if self._is_locked(ip, username):
                self._throttle_rejected = True
                form = self.get_form()
                form.add_error(None, self.THROTTLE_ERROR_MESSAGE)
                return self.form_invalid(form)
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        if not getattr(self, '_throttle_rejected', False):
            self._record_failure(self.request)
        return super().form_invalid(form)

    def form_valid(self, form):
        self._clear_failures(self.request)
        response = super().form_valid(form)

        # 로그인 직후 첫 진입이 앱 홈(/home/)일 때만 기능 소개 영상 모달을 1회 노출한다.
        try:
            location = str(response.get('Location') or '')
            target_path = urlparse(location).path if location else ''
            if target_path == reverse_lazy('app_home'):
                self.request.session[self.INTRO_MODAL_SESSION_KEY] = True
            else:
                self.request.session.pop(self.INTRO_MODAL_SESSION_KEY, None)
        except Exception:
            self.request.session.pop(self.INTRO_MODAL_SESSION_KEY, None)

        return response

    def _record_failure(self, request):
        ip = self._client_ip(request)
        username = self._raw_username(request)
        keys = self._attempt_keys(ip, username)
        block_keys = self._block_keys(ip, username)

        for key, block_key in zip(keys, block_keys):
            count = int(cache.get(key, 0)) + 1
            cache.set(key, count, self.WINDOW_SECONDS)
            if count >= self.MAX_ATTEMPTS:
                cache.set(block_key, 1, self.LOCK_SECONDS)

    def _clear_failures(self, request):
        ip = self._client_ip(request)
        username = self._raw_username(request)
        for key in self._attempt_keys(ip, username):
            cache.delete(key)
        for key in self._block_keys(ip, username):
            cache.delete(key)

    def _is_locked(self, ip, username):
        for block_key in self._block_keys(ip, username):
            if cache.get(block_key):
                return True
        return False

    def _attempt_keys(self, ip, username):
        # IP 단독 + IP/username 조합을 함께 추적해 대입 공격과 계정 타격형 공격을 동시에 제한한다.
        return (
            self._key('attempt_ip', ip),
            self._key('attempt_ip_user', f'{ip}:{username}'),
        )

    def _block_keys(self, ip, username):
        return (
            self._key('blocked_ip', ip),
            self._key('blocked_ip_user', f'{ip}:{username}'),
        )

    def _key(self, scope, raw):
        digest = hashlib.sha256(str(raw).encode('utf-8')).hexdigest()[:32]
        return f'auth:login:{scope}:{digest}'

    def _raw_username(self, request):
        return str(request.POST.get('username') or '').strip().lower()

    def _client_ip(self, request):
        xff = str(request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
        if xff:
            # "client, proxy1, proxy2" 형태에서 첫 번째를 원본으로 본다.
            return xff.split(',')[0].strip()
        return str(request.META.get('REMOTE_ADDR') or 'unknown').strip()


class UserCreateView(CreateView):
    form_class = BandUserCreationForm
    template_name = 'registration/signup.html'
    success_url = reverse_lazy('login')
