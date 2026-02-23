from django.contrib import admin
from .models import (
    Song, Session, User, Band, Membership, Meeting, PracticeRoom, RoomBlock,
    RecurringBlock, OneOffBlock, RecurringException, MemberAvailability, PracticeSchedule
)

# Register your models here.
admin.site.register(Song)
admin.site.register(Membership)
admin.site.register(Band)
admin.site.register(User)
admin.site.register(Meeting)
admin.site.register(Session)
admin.site.register(RecurringBlock)
admin.site.register(OneOffBlock)
admin.site.register(MemberAvailability)
admin.site.register(RecurringException)
admin.site.register(PracticeRoom)
