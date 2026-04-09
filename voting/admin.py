from django.contrib import admin

from voting.models import Voting, VotingRound, Bid, Vote, Voter, VotingVoter


class BidInline(admin.TabularInline):
    model = Bid
    fields = ["member_id", "round_number", "amount"]


class VotingRoundInline(admin.TabularInline):
    model = VotingRound
    show_change_link = True


class VoteInline(admin.TabularInline):
    model = Vote


class VotingVoterInline(admin.TabularInline):
    model = VotingVoter
    autocomplete_fields = ["voter"]
    extra = 0


class VotingAdmin(admin.ModelAdmin):
    list_display = ("name", "budget_goal", "voter_count", "total_count")
    search_fields = ("name",)
    inlines = [VotingVoterInline, BidInline, VotingRoundInline]


class VotingRoundAdmin(admin.ModelAdmin):
    list_display = ("id", "voting", "round_number", "active")
    inlines = [VoteInline]


class VoteAdmin(admin.ModelAdmin):
    pass


class BidAdmin(admin.ModelAdmin):
    list_display = ("id", "voting", "member_id", "round_number", "amount")


class VoterAdmin(admin.ModelAdmin):
    list_display = ("member_id", "name")
    search_fields = ("member_id", "name")


class VotingVoterAdmin(admin.ModelAdmin):
    list_display = ("voter", "voting", "absent_from_round")
    list_filter = ("voting",)
    autocomplete_fields = ["voter", "voting"]


admin.site.register(Voter, VoterAdmin)
admin.site.register(VotingVoter, VotingVoterAdmin)
admin.site.register(Voting, VotingAdmin)
admin.site.register(VotingRound, VotingRoundAdmin)
admin.site.register(Vote, VoteAdmin)
admin.site.register(Bid, BidAdmin)
