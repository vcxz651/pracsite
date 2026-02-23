# pracapp/views/admin_views.py

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from pracapp.models import Band, User


@login_required
def reset_db_data(request):
    """
    관리자 전용: 데이터베이스 초기화
    슈퍼유저를 제외한 모든 데이터를 삭제합니다.
    """
    if not request.user.is_superuser:
        messages.error(request, "권한이 없습니다.")
        return redirect('admin:index')

    if request.method == "POST":
        try:
            # 1. 밴드 데이터 삭제 (Cascading으로 Meeting, Song, Session 등 연쇄 삭제됨)
            Band.objects.all().delete()

            # 2. 슈퍼유저가 아닌 일반 유저 삭제 (Membership, Avail 등 연쇄 삭제)
            User.objects.filter(is_superuser=False).delete()

            messages.success(request, "✅ 슈퍼유저를 제외한 모든 데이터가 초기화되었습니다.")
        except Exception as e:
            messages.error(request, f"초기화 중 오류 발생: {e}")

    return redirect('admin:index')  # 다시 어드민 페이지로 이동
