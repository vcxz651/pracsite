import re

from django.contrib.auth import logout
from django.utils import timezone

from .models import Band, Session, Song, User


UUID_RE = r'[0-9a-fA-F-]{32,36}'
SESSION_PATH_RE = re.compile(rf'^/session/(?P<sid>{UUID_RE})/')
SONG_PATH_RE = re.compile(rf'^/song/(?P<sid>{UUID_RE})/')


def _cleanup_demo_assets(request):
    session = request.session
    is_cached = bool(session.get('demo_is_cached'))
    band_id = session.get('demo_band_id')
    user_ids = session.get('demo_user_ids') or []
    if not user_ids:
        for key in ('demo_user_manager_id', 'demo_user_member_id'):
            uid = session.get(key)
            if uid:
                user_ids.append(uid)

    if band_id and not is_cached:
        Band.objects.filter(id=band_id).delete()
    if user_ids and not is_cached:
        User.objects.filter(id__in=user_ids).delete()

    for key in (
        'demo_mode', 'demo_role', 'demo_scenario',
        'demo_band_id', 'demo_meeting_id',
        'demo_user_manager_id', 'demo_user_member_id',
        'demo_user_ids', 'demo_is_cached', 'demo_last_seen',
        '_auth_user_id', '_auth_user_backend', '_auth_user_hash',
    ):
        session.pop(key, None)


def _is_demo_scope_request(request):
    path = str(request.path or '')
    sess = request.session
    demo_meeting_id = str(sess.get('demo_meeting_id') or '')
    demo_band_id = str(sess.get('demo_band_id') or '')

    if path.startswith('/demo/'):
        return True
    if demo_meeting_id and demo_meeting_id in path:
        return True
    if demo_band_id and demo_band_id in path:
        return True

    m = SESSION_PATH_RE.match(path)
    if m and demo_meeting_id:
        sid = m.group('sid')
        return Session.objects.filter(id=sid, song__meeting_id=demo_meeting_id).exists()

    m = SONG_PATH_RE.match(path)
    if m and demo_meeting_id:
        sid = m.group('sid')
        return Song.objects.filter(id=sid, meeting_id=demo_meeting_id).exists()

    return False


class DemoSessionCleanupMiddleware:
    """
    데모 세션 사용자가 데모 범위를 이탈하면 즉시 데모 데이터를 정리한다.
    브라우저 강제 종료 케이스는 별도 TTL 정리 커맨드로 보완한다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.session.get('demo_mode'):
            if _is_demo_scope_request(request):
                request.session['demo_last_seen'] = timezone.now().isoformat()
            else:
                _cleanup_demo_assets(request)
                if request.user.is_authenticated:
                    logout(request)
        return self.get_response(request)
