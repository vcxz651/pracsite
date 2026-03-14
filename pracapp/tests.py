import datetime
import json
import uuid

from django.test import TestCase
from django.urls import reverse

from .views.matching_views import _build_events_signature
from .utils import auto_schedule_match
from .models import (
    Band,
    ExtraPracticeSchedule,
    Meeting,
    MeetingFinalDraft,
    MeetingWorkDraft,
    MeetingScheduleConfirmation,
    Membership,
    RoomBlock,
    PracticeRoom,
    PracticeSchedule,
    OneOffBlock,
    Session,
    Song,
    SongComment,
    User,
    MemberAvailability,
)


class TestMatchResultFlow(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username='manager',
            password='pw123456',
            realname='매니저',
        )
        self.member = User.objects.create_user(
            username='member',
            password='pw123456',
            realname='멤버',
        )
        self.user_a = User.objects.create_user(
            username='alice',
            password='pw123456',
            realname='앨리스',
        )
        self.user_b = User.objects.create_user(
            username='bob',
            password='pw123456',
            realname='밥',
        )

        self.band = Band.objects.create(name='밴드A')
        Membership.objects.create(user=self.manager, band=self.band, role='MANAGER', is_approved=True)
        Membership.objects.create(user=self.member, band=self.band, role='MEMBER', is_approved=True)

        self.meeting = Meeting.objects.create(
            band=self.band,
            title='테스트 미팅',
            practice_start_date=datetime.date(2026, 3, 2),
            practice_end_date=datetime.date(2026, 3, 8),
        )
        self.room = PracticeRoom.objects.create(band=self.band, name='A룸', capacity=10)
        self.room_b = PracticeRoom.objects.create(band=self.band, name='B룸', capacity=10)

        self.song_1 = Song.objects.create(
            meeting=self.meeting,
            author=self.manager,
            title='Song 1',
            artist='A',
        )
        self.song_2 = Song.objects.create(
            meeting=self.meeting,
            author=self.manager,
            title='Song 2',
            artist='B',
        )

    def _create_external_meeting_with_schedule(self, *, room, date_obj, start_index, end_index, assignee=None):
        external_meeting = Meeting.objects.create(
            band=self.band,
            title='외부 미팅',
            practice_start_date=self.meeting.practice_start_date,
            practice_end_date=self.meeting.practice_end_date,
        )
        external_song = Song.objects.create(
            meeting=external_meeting,
            author=self.manager,
            title='External Song',
            artist='X',
        )
        if assignee is not None:
            Session.objects.create(song=external_song, name='Vocal', assignee=assignee)
        PracticeSchedule.objects.create(
            meeting=external_meeting,
            song=external_song,
            room=room,
            date=date_obj,
            start_index=start_index,
            end_index=end_index,
            is_forced=False,
        )
        return external_meeting

    def test_schedule_save_result_requires_manager_role(self):
        self.client.login(username='member', password='pw123456')
        url = reverse('schedule_save_result', args=[self.meeting.id])
        resp = self.client.post(
            url,
            data=json.dumps({'events': []}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_schedule_save_result_requires_approved_manager_membership(self):
        Membership.objects.filter(user=self.manager, band=self.band).update(is_approved=False)
        self.client.login(username='manager', password='pw123456')
        url = reverse('schedule_save_result', args=[self.meeting.id])
        resp = self.client.post(
            url,
            data=json.dumps({'events': []}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_schedule_save_result_saves_events_and_creates_temp_room(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.user_a)
        Session.objects.create(song=self.song_2, name='Drum', assignee=self.user_b)
        MeetingScheduleConfirmation.objects.create(
            meeting=self.meeting,
            user=self.user_a,
            version=self.meeting.schedule_version,
        )
        MeetingScheduleConfirmation.objects.create(
            meeting=self.meeting,
            user=self.user_b,
            version=self.meeting.schedule_version,
        )
        self.client.login(username='manager', password='pw123456')

        url = reverse('schedule_save_result', args=[self.meeting.id])
        payload = {
            'events': [
                {
                    'song_id': str(self.song_1.id),
                    'date': '2026-03-03',
                    'start': 20,
                    'duration': 2,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                },
                {
                    'song_id': str(self.song_2.id),
                    'date': '2026-03-04',
                    'start': 22,
                    'duration': 1,
                    'room_id': f'temp-{uuid.uuid4()}',
                    'room_name': '임시 합주실X',
                    'is_forced': True,
                },
            ]
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')

        self.assertEqual(PracticeSchedule.objects.filter(meeting=self.meeting).count(), 2)
        temp_room_exists = PracticeRoom.objects.filter(
            band=self.band,
            name='임시 합주실X',
            is_temporary=True,
        ).exists()
        self.assertTrue(temp_room_exists)

        generated_blocks = OneOffBlock.objects.filter(
            is_generated=True,
            source_meeting=self.meeting,
        )
        self.assertEqual(generated_blocks.count(), 2)
        self.assertTrue(generated_blocks.filter(user=self.user_a).exists())
        self.assertTrue(generated_blocks.filter(user=self.user_b).exists())

    def test_schedule_save_result_keeps_distinct_temporary_rooms_by_room_id(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.user_a)
        Session.objects.create(song=self.song_2, name='Drum', assignee=self.user_b)
        self.client.login(username='manager', password='pw123456')

        url = reverse('schedule_save_result', args=[self.meeting.id])
        payload = {
            'events': [
                {
                    'song_id': str(self.song_1.id),
                    'date': '2026-03-03',
                    'start': 20,
                    'duration': 1,
                    'room_id': 'temp-a',
                    'room_name': '임시 A',
                    'room_location': '위치 A',
                    'is_forced': False,
                },
                {
                    'song_id': str(self.song_2.id),
                    'date': '2026-03-03',
                    'start': 22,
                    'duration': 1,
                    'room_id': 'temp-b',
                    'room_name': '임시 B',
                    'room_location': '위치 B',
                    'is_forced': False,
                },
            ]
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')

        schedules = list(
            PracticeSchedule.objects.filter(meeting=self.meeting)
            .select_related('room')
            .order_by('start_index')
        )
        self.assertEqual(len(schedules), 2)
        self.assertNotEqual(schedules[0].room_id, schedules[1].room_id)
        self.assertEqual(schedules[0].room.name, '임시 A')
        self.assertEqual(schedules[0].room.location, '위치 A')
        self.assertEqual(schedules[1].room.name, '임시 B')
        self.assertEqual(schedules[1].room.location, '위치 B')

    def test_auto_schedule_match_separate_days_option_uses_distinct_dates(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.user_a)
        MemberAvailability.objects.create(
            user=self.user_a,
            date=datetime.date(2026, 3, 2),
            available_slot=[18, 19, 20, 21],
        )
        MemberAvailability.objects.create(
            user=self.user_a,
            date=datetime.date(2026, 3, 3),
            available_slot=[18, 19],
        )

        result = auto_schedule_match(
            self.meeting,
            60,
            2,
            allowed_room_ids=[str(self.room.id)],
            separate_days_for_multi_sessions=True,
            song_ids=[self.song_1.id],
        )

        self.assertEqual(result.get('status'), 'success')
        schedule = result.get('schedule') or []
        self.assertEqual(len(schedule), 2)
        scheduled_dates = {row['date'] for row in schedule}
        self.assertEqual(scheduled_dates, {'2026-03-02', '2026-03-03'})

    def test_schedule_move_event_member_overlap_conflict_then_force(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.user_a)
        Session.objects.create(song=self.song_2, name='Guitar1', assignee=self.user_a)

        MemberAvailability.objects.create(
            user=self.user_a,
            date=datetime.date(2026, 3, 3),
            available_slot=list(range(18, 48)),
        )

        PracticeSchedule.objects.create(
            meeting=self.meeting,
            song=self.song_2,
            room=self.room,
            date=datetime.date(2026, 3, 3),
            start_index=20,
            end_index=21,
            is_forced=False,
        )

        self.client.login(username='manager', password='pw123456')
        url = reverse('schedule_move_event', args=[self.meeting.id])
        base_payload = {
            'song_id': str(self.song_1.id),
            'target_date': '2026-03-03',
            'target_start': 20,
            'duration': 1,
        }

        resp_conflict = self.client.post(
            url,
            data=json.dumps({**base_payload, 'force': False}),
            content_type='application/json',
        )
        self.assertEqual(resp_conflict.status_code, 409)
        self.assertEqual(resp_conflict.json().get('kind'), 'member_overlap')

        resp_force = self.client.post(
            url,
            data=json.dumps({**base_payload, 'force': True}),
            content_type='application/json',
        )
        self.assertEqual(resp_force.status_code, 200)
        self.assertEqual(resp_force.json().get('status'), 'success')

    def test_schedule_save_result_does_not_require_all_confirmations_of_current_version(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.user_a)
        Session.objects.create(song=self.song_2, name='Drum', assignee=self.user_b)
        MeetingScheduleConfirmation.objects.create(
            meeting=self.meeting,
            user=self.user_a,
            version=self.meeting.schedule_version,
        )
        self.client.login(username='manager', password='pw123456')

        url = reverse('schedule_save_result', args=[self.meeting.id])
        payload = {
            'events': [
                {
                    'song_id': str(self.song_1.id),
                    'date': '2026-03-03',
                    'start': 20,
                    'duration': 1,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                },
                {
                    'song_id': str(self.song_2.id),
                    'date': '2026-03-04',
                    'start': 22,
                    'duration': 1,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                },
            ]
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')

    def test_schedule_final_prepare_blocks_external_room_conflict(self):
        self.client.login(username='manager', password='pw123456')
        conflict_date = datetime.date(2026, 3, 3)
        self._create_external_meeting_with_schedule(
            room=self.room,
            date_obj=conflict_date,
            start_index=20,
            end_index=21,
        )
        payload = {
            'events': [
                {
                    'song_id': str(self.song_1.id),
                    'date': conflict_date.isoformat(),
                    'start': 20,
                    'duration': 1,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                }
            ]
        }
        url = reverse('schedule_final_prepare', args=[self.meeting.id])
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get('status'), 'error')

    def test_schedule_final_prepare_allows_forced_member_overlap(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.user_a)
        Session.objects.create(song=self.song_2, name='Vocal', assignee=self.user_a)
        self.client.login(username='manager', password='pw123456')
        target_date = datetime.date(2026, 3, 3)
        payload = {
            'events': [
                {
                    'song_id': str(self.song_1.id),
                    'date': target_date.isoformat(),
                    'start': 20,
                    'duration': 1,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                },
                {
                    'song_id': str(self.song_2.id),
                    'date': target_date.isoformat(),
                    'start': 20,
                    'duration': 1,
                    'room_id': str(self.room_b.id),
                    'room_name': self.room_b.name,
                    'is_forced': True,
                },
            ]
        }
        url = reverse('schedule_final_prepare', args=[self.meeting.id])
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')

    def test_schedule_booking_start_blocks_external_room_conflict(self):
        self.client.login(username='manager', password='pw123456')
        conflict_date = datetime.date(2026, 3, 3)
        self._create_external_meeting_with_schedule(
            room=self.room,
            date_obj=conflict_date,
            start_index=20,
            end_index=21,
        )
        payload_events = [
            {
                'song_id': str(self.song_1.id),
                'date': conflict_date.isoformat(),
                'start': 20,
                'duration': 1,
                'room_id': str(self.room.id),
                'room_name': self.room.name,
                'is_forced': False,
            }
        ]
        MeetingFinalDraft.objects.update_or_create(
            meeting=self.meeting,
            defaults={
                'events': payload_events,
                'updated_by': self.manager,
            }
        )
        self.meeting.is_final_schedule_released = True
        self.meeting.save(update_fields=['is_final_schedule_released'])

        url = reverse('schedule_booking_start', args=[self.meeting.id])
        resp = self.client.post(
            url,
            data=json.dumps({'events': payload_events}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get('status'), 'error')

    def test_schedule_booking_start_allows_forced_member_overlap(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.user_a)
        Session.objects.create(song=self.song_2, name='Vocal', assignee=self.user_a)
        self.client.login(username='manager', password='pw123456')
        target_date = datetime.date(2026, 3, 3)
        payload_events = [
            {
                'song_id': str(self.song_1.id),
                'date': target_date.isoformat(),
                'start': 20,
                'duration': 1,
                'room_id': str(self.room.id),
                'room_name': self.room.name,
                'is_forced': False,
            },
            {
                'song_id': str(self.song_2.id),
                'date': target_date.isoformat(),
                'start': 20,
                'duration': 1,
                'room_id': str(self.room_b.id),
                'room_name': self.room_b.name,
                'is_forced': True,
            },
        ]
        MeetingFinalDraft.objects.update_or_create(
            meeting=self.meeting,
            defaults={
                'events': payload_events,
                'updated_by': self.manager,
            }
        )
        self.meeting.is_final_schedule_released = True
        self.meeting.save(update_fields=['is_final_schedule_released'])

        url = reverse('schedule_booking_start', args=[self.meeting.id])
        resp = self.client.post(
            url,
            data=json.dumps({'events': payload_events}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')

    def test_schedule_save_result_blocks_external_member_conflict(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.user_a)
        # 외부 미팅에 같은 유저를 같은 시간대에 배치 (방은 달라도 멤버 중복이면 차단)
        self._create_external_meeting_with_schedule(
            room=self.room_b,
            date_obj=datetime.date(2026, 3, 3),
            start_index=20,
            end_index=21,
            assignee=self.user_a,
        )
        self.client.login(username='manager', password='pw123456')
        url = reverse('schedule_save_result', args=[self.meeting.id])
        payload = {
            'events': [
                {
                    'song_id': str(self.song_1.id),
                    'date': '2026-03-03',
                    'start': 20,
                    'duration': 1,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                }
            ]
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get('status'), 'error')

    def test_schedule_match_resume_clears_booking_in_progress(self):
        self.meeting.is_schedule_coordinating = False
        self.meeting.is_final_schedule_released = True
        self.meeting.is_booking_in_progress = True
        self.meeting.is_final_schedule_confirmed = False
        self.meeting.save(update_fields=[
            'is_schedule_coordinating',
            'is_final_schedule_released',
            'is_booking_in_progress',
            'is_final_schedule_confirmed',
        ])

        self.client.login(username='manager', password='pw123456')
        url = reverse('schedule_match_resume', args=[self.meeting.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

        self.meeting.refresh_from_db()
        self.assertTrue(self.meeting.is_schedule_coordinating)
        self.assertTrue(self.meeting.is_final_schedule_released)
        self.assertFalse(self.meeting.is_booking_in_progress)
        self.assertFalse(self.meeting.is_final_schedule_confirmed)

    def test_schedule_final_acknowledge_blocked_during_booking_in_progress(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.member)
        self.meeting.is_final_schedule_released = True
        self.meeting.is_booking_in_progress = True
        self.meeting.save(update_fields=['is_final_schedule_released', 'is_booking_in_progress'])

        self.client.login(username='member', password='pw123456')
        url = reverse('schedule_final_acknowledge', args=[self.meeting.id])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 409)

    def test_schedule_final_prepare_increments_schedule_version(self):
        self.meeting.is_schedule_coordinating = True
        self.meeting.is_final_schedule_released = False
        self.meeting.is_booking_in_progress = False
        self.meeting.schedule_version = 1
        self.meeting.save(update_fields=[
            'is_schedule_coordinating',
            'is_final_schedule_released',
            'is_booking_in_progress',
            'schedule_version',
        ])

        self.client.login(username='manager', password='pw123456')
        url = reverse('schedule_final_prepare', args=[self.meeting.id])
        resp = self.client.post(
            url,
            data=json.dumps({'events': []}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')

        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.schedule_version, 2)

    def test_schedule_final_acknowledge_allows_resubmit_after_version_change(self):
        Session.objects.create(song=self.song_1, name='Vocal', assignee=self.member)
        self.meeting.is_final_schedule_released = True
        self.meeting.is_booking_in_progress = False
        self.meeting.schedule_version = 1
        self.meeting.save(update_fields=['is_final_schedule_released', 'is_booking_in_progress', 'schedule_version'])

        self.client.login(username='member', password='pw123456')
        url = reverse('schedule_final_acknowledge', args=[self.meeting.id])
        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json().get('status'), 'success')
        self.assertTrue(MeetingScheduleConfirmation.objects.filter(
            meeting=self.meeting, user=self.member, version=1
        ).exists())

        self.meeting.schedule_version = 2
        self.meeting.save(update_fields=['schedule_version'])

        second = self.client.post(url)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json().get('status'), 'success')
        self.assertTrue(MeetingScheduleConfirmation.objects.filter(
            meeting=self.meeting, user=self.member, version=2
        ).exists())

    def test_schedule_booking_start_rejects_changed_board_after_share(self):
        self.meeting.is_final_schedule_released = True
        self.meeting.save(update_fields=['is_final_schedule_released'])
        MeetingFinalDraft.objects.create(
            meeting=self.meeting,
            updated_by=self.manager,
            events=[
                {
                    'song_id': str(self.song_1.id),
                    'date': '2026-03-03',
                    'start': 20,
                    'duration': 1,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                },
            ],
        )
        self.client.login(username='manager', password='pw123456')
        url = reverse('schedule_booking_start', args=[self.meeting.id])
        changed_payload = {
            'events': [
                {
                    'song_id': str(self.song_1.id),
                    'date': '2026-03-03',
                    'start': 21,
                    'duration': 1,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                },
            ]
        }
        resp = self.client.post(url, data=json.dumps(changed_payload), content_type='application/json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get('status'), 'error')

    def test_schedule_save_result_blocks_booking_confirm_when_required_tiles_remain(self):
        self.meeting.is_booking_in_progress = True
        self.meeting.is_final_schedule_released = True
        self.meeting.save(update_fields=['is_booking_in_progress', 'is_final_schedule_released'])
        self.client.login(username='manager', password='pw123456')
        url = reverse('schedule_save_result', args=[self.meeting.id])
        payload = {
            'events': [
                {
                    'song_id': str(self.song_1.id),
                    'date': '2026-03-03',
                    'start': 20,
                    'duration': 1,
                    'room_id': str(self.room.id),
                    'room_name': self.room.name,
                    'is_forced': False,
                },
            ],
            'booking_completed_keys': [],
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json().get('status'), 'error')
        self.assertEqual(resp.json().get('remaining_count'), 1)

    def test_schedule_final_booking_view_restores_saved_booking_completion_keys(self):
        self.meeting.is_final_schedule_released = True
        self.meeting.is_booking_in_progress = True
        self.meeting.save(update_fields=['is_final_schedule_released', 'is_booking_in_progress'])
        events = [
            {
                'song_id': str(self.song_1.id),
                'date': '2026-03-03',
                'start': 20,
                'duration': 1,
                'room_id': str(self.room.id),
                'room_name': self.room.name,
                'room_location': '',
                'is_forced': False,
            }
        ]
        MeetingFinalDraft.objects.create(
            meeting=self.meeting,
            updated_by=self.manager,
            events=events,
        )
        key = f"{self.song_1.id}|2026-03-03|20|1|{self.room.id}"
        MeetingWorkDraft.objects.update_or_create(
            meeting=self.meeting,
            user=self.manager,
            defaults={
                'events': events,
                'match_params': {
                    'booking_completed_keys': [key],
                    'booking_completed_signature': _build_events_signature(events),
                },
            },
        )

        self.client.login(username='manager', password='pw123456')
        resp = self.client.get(f"{reverse('schedule_final', args=[self.meeting.id])}?mode=booking")
        self.assertEqual(resp.status_code, 200)
        saved_keys = json.loads(resp.context['booking_saved_completed_keys_json'])
        self.assertIn(key, saved_keys)

    def test_session_apply_cannot_remove_application_when_user_is_assignee(self):
        session = Session.objects.create(song=self.song_1, name='Vocal', assignee=self.manager)
        session.applicant.add(self.manager)

        self.client.login(username='manager', password='pw123456')
        url = reverse('session_apply', args=[session.id])
        resp = self.client.post(
            url,
            data={},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(session.applicant.filter(id=self.manager.id).exists())

    def test_session_manage_applicant_cannot_remove_application_when_target_is_assignee(self):
        session = Session.objects.create(song=self.song_1, name='Drum', assignee=self.member)
        session.applicant.add(self.member)

        self.client.login(username='manager', password='pw123456')
        url = reverse('session_manage_applicant', args=[session.id, self.member.id])
        resp = self.client.post(url, data={})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(session.applicant.filter(id=self.member.id).exists())

    def test_meeting_room_edit_cannot_modify_confirmed_generated_room_blocks(self):
        other_meeting = Meeting.objects.create(
            band=self.band,
            title='다른 미팅',
            practice_start_date=self.meeting.practice_start_date,
            practice_end_date=self.meeting.practice_end_date,
        )
        RoomBlock.objects.create(
            room=self.room,
            date=datetime.date(2026, 3, 3),
            start_index=20,
            end_index=22,
            source_meeting=self.meeting,
        )

        self.client.login(username='manager', password='pw123456')
        url = reverse('meeting_room_edit', args=[other_meeting.id, self.room.id])
        blocks_json = json.dumps({
            '2026-03-03': [{'start': 20, 'end': 23}],
        })
        resp = self.client.post(url, data={
            'name': self.room.name,
            'capacity': self.room.capacity,
            'location': self.room.location,
            'blocks_json': blocks_json,
        })
        self.assertEqual(resp.status_code, 302)

        self.assertTrue(RoomBlock.objects.filter(
            room=self.room,
            date=datetime.date(2026, 3, 3),
            start_index=20,
            end_index=22,
            source_meeting=self.meeting,
        ).exists())
        # 잠금 구간(20~22)은 사용자 편집(source_meeting null)으로 생성되면 안 된다.
        self.assertFalse(RoomBlock.objects.filter(
            room=self.room,
            date=datetime.date(2026, 3, 3),
            source_meeting__isnull=True,
            start_index__lt=22,
            end_index__gt=20,
        ).exists())
        # 잠금 바깥 구간(22~23)은 저장 가능.
        self.assertTrue(RoomBlock.objects.filter(
            room=self.room,
            date=datetime.date(2026, 3, 3),
            source_meeting__isnull=True,
            start_index=22,
            end_index=23,
        ).exists())


class TestDemoFlowExtreme(TestCase):
    def _post(self, path, data=None):
        return self.client.post(path, data=data or {}, HTTP_HOST='localhost')

    def _get(self, path):
        return self.client.get(path, HTTP_HOST='localhost')

    def test_demo_start_switch_scenarios_and_exit_cleanup(self):
        start_resp = self._post(reverse('demo_start'), {'scenario': '1'})
        self.assertEqual(start_resp.status_code, 302)
        self.assertEqual(start_resp['Location'], reverse('demo_scenario', args=[1]))

        session = self.client.session
        self.assertTrue(session.get('demo_mode'))
        self.assertEqual(session.get('demo_role'), 'manager')
        meeting_id = session.get('demo_meeting_id')
        self.assertTrue(meeting_id)

        meeting = Meeting.objects.get(id=meeting_id)
        self.assertTrue(meeting.is_schedule_coordinating)
        self.assertFalse(meeting.is_booking_in_progress)
        self.assertFalse(meeting.is_final_schedule_confirmed)
        self.assertEqual(meeting.participants.count(), 40)
        self.assertEqual(meeting.songs.count(), 50)
        self.assertTrue(meeting.title.startswith('[데모TEMPLATE]'))

        s2_resp = self._get(reverse('demo_scenario', args=[2]))
        self.assertEqual(s2_resp.status_code, 302)
        self.assertEqual(s2_resp['Location'], reverse('demo_dashboard'))

        second_meeting_id = self.client.session.get('demo_meeting_id')
        self.assertNotEqual(meeting_id, second_meeting_id)
        self.assertTrue(Meeting.objects.filter(id=meeting_id).exists())
        meeting = Meeting.objects.get(id=second_meeting_id)
        meeting.refresh_from_db()
        self.assertTrue(meeting.is_schedule_coordinating)
        self.assertFalse(meeting.is_final_schedule_released)
        self.assertFalse(meeting.is_booking_in_progress)
        self.assertFalse(meeting.is_final_schedule_confirmed)
        self.assertEqual(meeting.participants.count(), 6)
        self.assertEqual(meeting.songs.count(), 20)
        self.assertTrue(MeetingWorkDraft.objects.filter(meeting=meeting).exists())

        s3_resp = self._get(reverse('demo_scenario', args=[3]))
        self.assertEqual(s3_resp.status_code, 302)

        third_meeting_id = self.client.session.get('demo_meeting_id')
        self.assertEqual(s3_resp['Location'], reverse('schedule_final', args=[third_meeting_id]))
        self.assertNotEqual(second_meeting_id, third_meeting_id)
        self.assertFalse(Meeting.objects.filter(id=second_meeting_id).exists())
        meeting = Meeting.objects.get(id=third_meeting_id)
        meeting.refresh_from_db()
        self.assertTrue(meeting.is_final_schedule_confirmed)
        self.assertGreaterEqual(
            MeetingScheduleConfirmation.objects.filter(meeting=meeting, version=meeting.schedule_version).count(),
            1,
        )

        exit_resp = self._post(reverse('demo_exit'))
        self.assertEqual(exit_resp.status_code, 302)
        self.assertEqual(exit_resp['Location'], reverse('home'))

        self.assertFalse(Meeting.objects.filter(id=third_meeting_id).exists())
        self.assertIsNone(self.client.session.get('demo_mode'))

    def test_demo_switch_role_repeated_keeps_session_and_swaps_user(self):
        self._post(reverse('demo_start'), {'scenario': '2'})
        meeting_id = self.client.session.get('demo_meeting_id')
        manager_id = self.client.session.get('demo_user_manager_id')
        member_id = self.client.session.get('demo_user_member_id')
        meeting = Meeting.objects.get(id=meeting_id)

        self.assertEqual(meeting.participants.count(), 6)
        self.assertEqual(meeting.songs.count(), 20)

        self.assertEqual(self.client.session.get('demo_role'), 'manager')
        self.assertEqual(self.client.session.get('_auth_user_id'), manager_id)

        for i in range(8):
            resp = self._post(reverse('demo_switch_role'), {'next': reverse('demo_scenario', args=[2])})
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp['Location'], reverse('demo_scenario', args=[2]))
            self.assertTrue(self.client.session.get('demo_mode'))
            self.assertEqual(self.client.session.get('demo_meeting_id'), meeting_id)
            if i % 2 == 0:
                self.assertEqual(self.client.session.get('demo_role'), 'member')
                self.assertEqual(self.client.session.get('_auth_user_id'), member_id)
            else:
                self.assertEqual(self.client.session.get('demo_role'), 'manager')
                self.assertEqual(self.client.session.get('_auth_user_id'), manager_id)

    def test_demo_restart_replaces_previous_demo_dataset(self):
        self._post(reverse('demo_start'), {'scenario': '1'})
        first_band_id = self.client.session.get('demo_band_id')
        first_meeting_id = self.client.session.get('demo_meeting_id')
        self.assertTrue(Band.objects.filter(id=first_band_id).exists())
        self.assertTrue(Meeting.objects.filter(id=first_meeting_id).exists())

        self._post(reverse('demo_start'), {'scenario': '3'})
        second_band_id = self.client.session.get('demo_band_id')
        second_meeting_id = self.client.session.get('demo_meeting_id')

        self.assertNotEqual(first_meeting_id, second_meeting_id)
        # 시나리오 A는 공유 템플릿을 직접 사용하므로, 재시작해도 원본 템플릿은 유지된다.
        self.assertTrue(Meeting.objects.filter(id=first_meeting_id).exists())
        self.assertTrue(Band.objects.filter(id=first_band_id).exists())
        self.assertTrue(Band.objects.filter(id=second_band_id).exists())
        self.assertTrue(Meeting.objects.filter(id=second_meeting_id).exists())

    def test_demo_member_scenario_one_redirects_to_meeting_detail(self):
        self._post(reverse('demo_start'), {'scenario': '1'})
        meeting_id = self.client.session.get('demo_meeting_id')

        self._post(reverse('demo_switch_role'), {'next': reverse('demo_scenario', args=[1])})
        self.assertEqual(self.client.session.get('demo_role'), 'member')

        resp = self._get(reverse('demo_scenario', args=[1]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('schedule_match_run', args=[meeting_id]), resp['Location'])
        self.assertIn('force_rematch=1', resp['Location'])

    def test_demo_data_cleans_up_immediately_when_leaving_demo_scope(self):
        self._post(reverse('demo_start'), {'scenario': '2'})
        band_id = self.client.session.get('demo_band_id')
        meeting_id = self.client.session.get('demo_meeting_id')
        self.assertTrue(Band.objects.filter(id=band_id).exists())
        self.assertTrue(Meeting.objects.filter(id=meeting_id).exists())
        self.assertTrue(self.client.session.get('demo_mode'))

        # 비데모 경로로 이동하면 미들웨어가 즉시 정리해야 한다.
        resp = self._get(reverse('home'))
        self.assertEqual(resp.status_code, 200)

        self.assertFalse(Band.objects.filter(id=band_id).exists())
        self.assertFalse(Meeting.objects.filter(id=meeting_id).exists())
        self.assertIsNone(self.client.session.get('demo_mode'))
        self.assertFalse('_auth_user_id' in self.client.session)


class TestExtraPracticeRoomBlockConsistency(TestCase):
    """
    회귀 체크리스트 §J: 추가합주 RoomBlock 일관성 검증
    ExtraPracticeSchedule + RoomBlock 동시 생성/삭제 정책을 커버한다.
    """

    def setUp(self):
        self.manager = User.objects.create_user(username='ep_manager', password='pw123456', realname='매니저')
        self.assignee = User.objects.create_user(username='ep_assignee', password='pw123456', realname='배정자')
        self.other = User.objects.create_user(username='ep_other', password='pw123456', realname='타인')

        self.band = Band.objects.create(name='EP밴드')
        Membership.objects.create(user=self.manager, band=self.band, role='MANAGER', is_approved=True)
        Membership.objects.create(user=self.assignee, band=self.band, role='MEMBER', is_approved=True)

        self.meeting = Meeting.objects.create(
            band=self.band,
            title='EP테스트 미팅',
            is_final_schedule_confirmed=True,
            practice_start_date=datetime.date(2026, 3, 2),
            practice_end_date=datetime.date(2026, 3, 8),
        )
        self.room = PracticeRoom.objects.create(band=self.band, name='EP룸', capacity=10)
        self.song = Song.objects.create(meeting=self.meeting, author=self.manager, title='EP곡', artist='X')
        Session.objects.create(song=self.song, name='Vocal', assignee=self.assignee)

    def _save_url(self):
        return reverse('extra_practice_save', args=[self.meeting.id, self.song.id])

    def _delete_url(self):
        return reverse('extra_practice_delete', args=[self.meeting.id, self.song.id])

    def _save_payload(self, **kwargs):
        base = {
            'date': '2026-03-03',
            'start_index': 20,
            'end_index': 24,
            'room_id': str(self.room.id),
        }
        base.update(kwargs)
        return base

    def test_save_creates_schedule_and_roomblock_together(self):
        """저장 성공 시 ExtraPracticeSchedule + RoomBlock 동시 생성, 응답에 두 ID 모두 포함"""
        self.client.login(username='ep_manager', password='pw123456')
        resp = self.client.post(
            self._save_url(),
            data=json.dumps(self._save_payload()),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], 'ok')
        self.assertIn('schedule_id', body)
        self.assertIn('block_id', body)

        schedule_id = body['schedule_id']
        block_id = body['block_id']
        self.assertTrue(ExtraPracticeSchedule.objects.filter(id=schedule_id).exists())
        self.assertTrue(RoomBlock.objects.filter(id=block_id, source_meeting=self.meeting).exists())

    def test_delete_removes_schedule_and_roomblock_together(self):
        """삭제 시 ExtraPracticeSchedule + 연관 RoomBlock 함께 제거"""
        self.client.login(username='ep_manager', password='pw123456')
        save_resp = self.client.post(
            self._save_url(),
            data=json.dumps(self._save_payload()),
            content_type='application/json',
        )
        schedule_id = save_resp.json()['schedule_id']
        block_id = save_resp.json()['block_id']

        del_resp = self.client.post(
            self._delete_url(),
            data=json.dumps({'schedule_id': schedule_id}),
            content_type='application/json',
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()['status'], 'ok')
        self.assertFalse(ExtraPracticeSchedule.objects.filter(id=schedule_id).exists())
        self.assertFalse(RoomBlock.objects.filter(id=block_id).exists())

    def test_duplicate_save_returns_409(self):
        """같은 합주실·날짜·시간 중복 저장 시 409 반환"""
        self.client.login(username='ep_manager', password='pw123456')
        self.client.post(
            self._save_url(),
            data=json.dumps(self._save_payload()),
            content_type='application/json',
        )
        resp2 = self.client.post(
            self._save_url(),
            data=json.dumps(self._save_payload()),
            content_type='application/json',
        )
        self.assertEqual(resp2.status_code, 409)

    def test_assignee_can_save_and_delete_own_schedule(self):
        """배정자(assignee)도 저장/삭제 가능"""
        self.client.login(username='ep_assignee', password='pw123456')
        save_resp = self.client.post(
            self._save_url(),
            data=json.dumps(self._save_payload()),
            content_type='application/json',
        )
        self.assertEqual(save_resp.status_code, 200)
        schedule_id = save_resp.json()['schedule_id']

        del_resp = self.client.post(
            self._delete_url(),
            data=json.dumps({'schedule_id': schedule_id}),
            content_type='application/json',
        )
        self.assertEqual(del_resp.status_code, 200)

    def test_non_participant_cannot_save(self):
        """미배정·비매니저 유저는 저장 불가 (403)"""
        self.client.login(username='ep_other', password='pw123456')
        resp = self.client.post(
            self._save_url(),
            data=json.dumps(self._save_payload()),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)


class TestBandUpdatePermission(TestCase):
    def setUp(self):
        self.leader = User.objects.create_user(username='leader_user', password='pw123456', realname='리더')
        self.manager = User.objects.create_user(username='manager_user', password='pw123456', realname='매니저')
        self.member = User.objects.create_user(username='member_user', password='pw123456', realname='멤버')
        self.band = Band.objects.create(name='권한테스트 밴드')
        Membership.objects.create(user=self.leader, band=self.band, role='LEADER', is_approved=True)
        Membership.objects.create(user=self.manager, band=self.band, role='MANAGER', is_approved=True)
        Membership.objects.create(user=self.member, band=self.band, role='MEMBER', is_approved=True)

    def test_leader_can_update_band_info(self):
        self.client.login(username='leader_user', password='pw123456')
        url = reverse('band_update', args=[self.band.id])
        resp = self.client.post(
            url,
            data={
                'name': '권한테스트 밴드(수정)',
                'school': '테스트학교',
                'department': 'ETC',
                'department_detail': '',
                'introduce': '소개',
                'description': '설명',
                'is_public': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.band.refresh_from_db()
        self.assertEqual(self.band.name, '권한테스트 밴드(수정)')

    def test_manager_cannot_update_band_info(self):
        self.client.login(username='manager_user', password='pw123456')
        url = reverse('band_update', args=[self.band.id])
        resp = self.client.post(
            url,
            data={
                'name': '매니저수정시도',
                'school': '',
                'department': 'ETC',
                'department_detail': '',
                'introduce': '',
                'description': '',
                'is_public': 'on',
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.band.refresh_from_db()
        self.assertEqual(self.band.name, '권한테스트 밴드')

    def test_member_cannot_update_band_info(self):
        self.client.login(username='member_user', password='pw123456')
        url = reverse('band_update', args=[self.band.id])
        resp = self.client.post(
            url,
            data={
                'name': '멤버수정시도',
                'school': '',
                'department': 'ETC',
                'department_detail': '',
                'introduce': '',
                'description': '',
                'is_public': 'on',
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.band.refresh_from_db()
        self.assertEqual(self.band.name, '권한테스트 밴드')


class TestSongCommentDisplayName(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username='comment_manager',
            password='pw123456',
            realname='댓글매니저',
            nickname='닉네임매니저',
        )
        self.member = User.objects.create_user(
            username='comment_member',
            password='pw123456',
            realname='댓글멤버',
            nickname='닉네임멤버',
        )
        self.band = Band.objects.create(name='댓글테스트밴드')
        Membership.objects.create(user=self.manager, band=self.band, role='MANAGER', is_approved=True)
        Membership.objects.create(user=self.member, band=self.band, role='MEMBER', is_approved=True)
        self.meeting = Meeting.objects.create(
            band=self.band,
            title='댓글테스트미팅',
            practice_start_date=datetime.date(2026, 3, 2),
            practice_end_date=datetime.date(2026, 3, 8),
        )
        self.song = Song.objects.create(
            meeting=self.meeting,
            author=self.manager,
            title='댓글테스트곡',
            artist='아티스트',
        )
        self.url = reverse('song_comments_data', args=[self.song.id])

    def test_song_comments_data_uses_author_nickname(self):
        SongComment.objects.create(song=self.song, author=self.member, content='테스트 댓글')
        self.client.login(username='comment_manager', password='pw123456')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(len(body['comments']), 1)
        self.assertEqual(body['comments'][0]['author_name'], '닉네임멤버')

    def test_song_comments_data_falls_back_to_username_when_nickname_missing(self):
        User.objects.filter(id=self.member.id).update(nickname='')
        SongComment.objects.create(song=self.song, author=self.member, content='닉네임 없는 댓글')
        self.client.login(username='comment_manager', password='pw123456')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], 'success')
        self.assertEqual(len(body['comments']), 1)
        self.assertEqual(body['comments'][0]['author_name'], 'comment_member')
