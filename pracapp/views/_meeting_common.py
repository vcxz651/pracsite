from ..models import Membership, MeetingParticipant, PracticeRoom


def is_final_locked(meeting, include_released=True):
    return bool(
        meeting.is_final_schedule_confirmed
        or (include_released and meeting.is_final_schedule_released)
    )


def final_lock_prefix(meeting):
    return '최종 확정 이후에는' if meeting.is_final_schedule_confirmed else '최종 일정 공개 이후에는'


def final_lock_message(meeting, action_text):
    return f'{final_lock_prefix(meeting)} {action_text}'


def final_lock_state_message(meeting):
    return '이미 최종 확정된 일정입니다.' if meeting.is_final_schedule_confirmed else '이미 최종 일정 공개 상태입니다.'


def available_rooms_qs(meeting, include_temporary=False):
    qs = PracticeRoom.objects.filter(band=meeting.band)
    if not include_temporary:
        qs = qs.filter(is_temporary=False)
    return qs.distinct()


def get_approved_membership(user, band):
    return Membership.objects.filter(
        user=user,
        band=band,
        is_approved=True,
    ).first()


def is_manager_membership(membership):
    return bool(membership and membership.role in ['LEADER', 'MANAGER'])


def is_meeting_manager_participant(meeting, user):
    return MeetingParticipant.objects.filter(
        meeting=meeting,
        user=user,
        status=MeetingParticipant.STATUS_APPROVED,
        role=MeetingParticipant.ROLE_MANAGER,
    ).exists()


def has_meeting_manager_permission(meeting, user, membership=None):
    membership = membership if membership is not None else get_approved_membership(user, meeting.band)
    if is_manager_membership(membership):
        return True
    return is_meeting_manager_participant(meeting, user)
