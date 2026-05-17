"""Authorization admin registrations."""

from django.contrib import admin

from apps.authz.models import AuthorizationEvent, GroupMembership


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ("member_name", "member_phone", "group_jid",
                    "status", "granted_by", "granted_at")
    list_filter = ("status",)
    search_fields = ("member_name", "member_phone", "group_jid", "granted_by")
    readonly_fields = ("granted_at", "revoked_at")


@admin.register(AuthorizationEvent)
class AuthorizationEventAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "kind", "actor_phone", "target_phone",
                    "group_jid")
    list_filter = ("kind",)
    search_fields = ("actor_phone", "target_phone", "group_jid", "detail")
    readonly_fields = ("timestamp",)
