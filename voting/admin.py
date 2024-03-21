from django.contrib import admin

from voting.models import Voting, VotingRound


class VotingAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "budget_goal", "voter_count", "total_count")


class VotingRoundAdmin(admin.ModelAdmin):
    list_display = ("id", "voting", "round_number", "active")


admin.site.register(Voting, VotingAdmin)
admin.site.register(VotingRound, VotingRoundAdmin)
