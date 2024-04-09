from django.contrib import admin

from voting.models import Voting, VotingRound, Bid, Vote


class BidInline(admin.TabularInline):
    model = Bid
    fields = ["member_id", "round_number", "amount"]


class VotingRoundInline(admin.TabularInline):
    model = VotingRound
    show_change_link = True


class VoteInline(admin.TabularInline):
    model = Vote


class VotingAdmin(admin.ModelAdmin):
    list_display = ("name", "budget_goal", "voter_count", "total_count")
    inlines = [BidInline, VotingRoundInline]


class VotingRoundAdmin(admin.ModelAdmin):
    list_display = ("id", "voting", "round_number", "active")
    inlines = [VoteInline]


class BidAdmin(admin.ModelAdmin):
    list_display = ("id", "voting", "member_id", "round_number", "amount")


admin.site.register(Voting, VotingAdmin)
admin.site.register(VotingRound, VotingRoundAdmin)
admin.site.register(Bid, BidAdmin)
