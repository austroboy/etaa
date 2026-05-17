"""Authorization Module – Views."""

from django.http import JsonResponse
from django.views import View

from apps.authz.models import AuthorizationEvent, GroupMembership


class GroupMembershipListView(View):
    def get(self, request):
        memberships = GroupMembership.objects.all()[:200]
        data = [
            {
                "id": m.pk,
                "group_jid": m.group_jid,
                "member_phone": m.member_phone,
                "member_name": m.member_name,
                "status": m.status,
                "granted_by": m.granted_by,
                "granted_at": m.granted_at.isoformat(),
            }
            for m in memberships
        ]
        return JsonResponse({"memberships": data})


class AuthorizationEventListView(View):
    def get(self, request):
        events = AuthorizationEvent.objects.all()[:200]
        data = [
            {
                "id": e.pk,
                "timestamp": e.timestamp.isoformat(),
                "kind": e.kind,
                "actor_phone": e.actor_phone,
                "target_phone": e.target_phone,
                "group_jid": e.group_jid,
                "detail": e.detail,
            }
            for e in events
        ]
        return JsonResponse({"events": data})
