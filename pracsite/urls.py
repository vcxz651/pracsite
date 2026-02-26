"""
URL configuration for pracsite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include
from pracapp import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('signup/', views.UserCreateView.as_view(), name='signup'),

    path('', views.HomeView.as_view(), name='home'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),

    path('band/create/', views.BandCreateView.as_view(), name='band_create'),
    path('band/update/<uuid:pk>/', views.BandUpdateView.as_view(), name='band_update'),
    path('band/list/', views.BandListView.as_view(), name='band_list'),
    path('band/enlist/<uuid:band_id>', views.MemberEnlistView.as_view(), name='member_enlist'),
    path('band/<uuid:band_id>/rooms/', views.band_rooms, name='band_rooms'),

    path('membership/<uuid:membership_id>/approve/', views.approve_member, name='member_approve'),
    path('membership/<uuid:pk>/manage/', views.manage_member, name='member_manage'),

    path('band/<uuid:band_id>/meeting/create/', views.MeetingCreateView.as_view(), name='meeting_create'),
    path('meeting/<uuid:pk>/', views.MeetingDetailView.as_view(), name='meeting_detail'),
    path('meeting/<uuid:meeting_id>/join/', views.meeting_join_request, name='meeting_join_request'),
    path('meeting/<uuid:meeting_id>/participants/manage/', views.meeting_participant_manage, name='meeting_participant_manage'),
    path('meeting/<uuid:meeting_id>/participant/<uuid:user_id>/approve/', views.meeting_participant_approve, name='meeting_participant_approve'),
    path('meeting/<uuid:meeting_id>/participant/<uuid:user_id>/reject/', views.meeting_participant_reject, name='meeting_participant_reject'),
    path('meeting/<uuid:meeting_id>/delete/', views.meeting_delete, name='meeting_delete'),
    path('meeting/<uuid:meeting_id>/room/create/', views.meeting_room_create, name='meeting_room_create'),
    path('meeting/<uuid:meeting_id>/session-stats/', views.meeting_session_stats_data, name='meeting_session_stats_data'),
    path('meeting/<uuid:meeting_id>/match-status/', views.meeting_match_status_data, name='meeting_match_status_data'),
    path('meeting/<uuid:meeting_id>/room/<uuid:room_id>/edit/', views.meeting_room_edit, name='meeting_room_edit'),
    path('meeting/update/<uuid:pk>/', views.MeetingUpdateView.as_view(), name='meeting_update'),
    path('meeting/<uuid:meeting_id>/match/settings/', views.schedule_match_settings, name='schedule_match_settings'),
    path('meeting/<uuid:meeting_id>/match/run/', views.schedule_match_run, name='schedule_match_run'),
    path('meeting/<uuid:meeting_id>/match/work-draft/save/', views.schedule_match_work_draft_save, name='schedule_match_work_draft_save'),
    path('meeting/<uuid:meeting_id>/final/', views.schedule_final, name='schedule_final'),
    path('meeting/<uuid:meeting_id>/final/booking/start/', views.schedule_booking_start, name='schedule_booking_start'),
    path('meeting/<uuid:meeting_id>/final/prepare/', views.schedule_final_prepare, name='schedule_final_prepare'),
    path('meeting/<uuid:meeting_id>/room-block/manage/', views.schedule_room_block_manage, name='schedule_room_block_manage'),
    path('meeting/<uuid:meeting_id>/match/resume/', views.schedule_match_resume, name='schedule_match_resume'),
    path('meeting/<uuid:meeting_id>/match/exit/', views.schedule_match_exit, name='schedule_match_exit'),
    path('meeting/<uuid:meeting_id>/final/ack/', views.schedule_final_acknowledge, name='schedule_final_acknowledge'),
    path('meeting/<uuid:meeting_id>/final/reset/', views.schedule_final_reset, name='schedule_final_reset'),
    path('meeting/<uuid:meeting_id>/match/save/', views.schedule_save_result, name='schedule_save_result'),
    path('meeting/<uuid:meeting_id>/match/move/', views.schedule_move_event, name='schedule_move_event'),
    path('meeting/<uuid:meeting_id>/reset_all/', views.reset_all_assignments, name='reset_all_assignments'),
    path('meeting/<uuid:meeting_id>/random_assign/', views.random_assign_all, name='random_assign_all'),
    path('meeting/<uuid:meeting_id>/random_apply/', views.random_apply_all, name='random_apply_all'),
    path('meeting/<uuid:meeting_id>/reset_all_applications/', views.reset_all_applications, name='reset_all_applications'),
    path('song/<uuid:song_id>/reset/', views.reset_song_assignments, name='reset_song_assignments'),

    path('meeting/<uuid:meeting_id>/song/<uuid:song_id>/extra-practice/', views.extra_practice, name='extra_practice'),
    path('meeting/<uuid:meeting_id>/song/<uuid:song_id>/extra-practice/save/', views.extra_practice_save, name='extra_practice_save'),
    path('meeting/<uuid:meeting_id>/song/<uuid:song_id>/extra-practice/delete/', views.extra_practice_delete, name='extra_practice_delete'),

    path('meeting/<uuid:meeting_id>/song/create/', views.SongCreateView.as_view(), name='song_create'),
    path('song/<uuid:song_id>/applicants-data/', views.song_applicants_data, name='song_applicants_data'),
    path('song/<uuid:song_id>/comments/', views.song_comments_data, name='song_comments_data'),
    path('song/<uuid:song_id>/comments/create/', views.song_comment_create, name='song_comment_create'),
    path('song/comment/<uuid:comment_id>/delete/', views.song_comment_delete, name='song_comment_delete'),
    path('song/update/<uuid:pk>/', views.SongUpdateView.as_view(), name='song_update'),
    path('song/delete/<uuid:pk>/', views.SongDeleteView.as_view(), name='song_delete'),

    path('session/<uuid:session_id>/apply', views.session_apply, name='session_apply'),
    path('session/<uuid:session_id>/assign/<uuid:user_id>/', views.session_assign, name='session_assign'),
    path('session/<uuid:session_id>/manage-applicant/<uuid:user_id>/', views.session_manage_applicant, name='session_manage_applicant'),
    path('session/<uuid:session_id>/manage-data/', views.session_manage_data, name='session_manage_data'),
    path('session/<uuid:session_id>/reject/<uuid:user_id>/', views.session_reject, name='session_reject'),
    path('meeting/<uuid:meeting_id>/session-application/toggle/', views.toggle_meeting_session_application, name='toggle_meeting_session_application'),

    path('schedule/setup/', views.schedule_setup, name='schedule_setup'),
    path('schedule/recurring/', views.schedule_recurring, name='schedule_recurring'),
    path('schedule/oneoff/', views.schedule_oneoff, name='schedule_oneoff'),
    path('schedule/confirm/', views.schedule_confirm, name='schedule_confirm'),
    path('schedule/delete/', views.schedule_delete, name='schedule_delete'),
    path('my-schedule/', views.my_schedule, name='my_schedule'), # [NEW]
    path('schedule/load/', views.schedule_edit_loader, name='schedule_edit_loader'),


    path('reset-db/', views.reset_db_data, name='reset_db_data'),

    path('demo/', views.demo_home, name='demo_home'),
    path('demo/dashboard/', views.demo_dashboard, name='demo_dashboard'),
    path('demo/start/', views.demo_start, name='demo_start'),
    path('demo/scenario/<int:scenario>/', views.demo_scenario, name='demo_scenario'),
    path('demo/switch-role/', views.demo_switch_role, name='demo_switch_role'),
    path('demo/exit/', views.demo_exit, name='demo_exit'),
]
