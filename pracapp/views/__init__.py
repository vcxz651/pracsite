# pracapp/views/__init__.py
# 모든 뷰를 재export하여 기존 import 경로 유지

from .auth_views import *
from .band_views import *
from .meeting_views import *
from .song_session_views import *
from .schedule_views import *
from .matching_views import *
from .home_views import *
from .admin_views import *
from .extra_practice_views import extra_practice, extra_practice_save, extra_practice_delete
from .demo_views import *
