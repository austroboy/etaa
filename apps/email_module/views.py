"""Email Module – Views."""

from django.http import JsonResponse
from django.views import View
from apps.email_module.models import EmailRecord


class EmailRecordListView(View):
    def get(self, request):
        records = EmailRecord.objects.all()[:50]
        data = [
            {
                "id": r.pk,
                "direction": r.direction,
                "to": r.to_address,
                "subject": r.subject,
                "sent_at": r.sent_at.isoformat(),
                "success": r.success,
            }
            for r in records
        ]
        return JsonResponse({"emails": data})
