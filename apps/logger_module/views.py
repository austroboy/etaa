"""Logger Module – Views."""

from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from apps.logger_module.models import ActionLog


@method_decorator(csrf_exempt, name="dispatch")
class ActionLogListView(View):
    def get(self, request):
        logs = ActionLog.objects.all()[:100]
        data = [
            {
                "id": l.pk,
                "timestamp": l.timestamp.isoformat(),
                "operator": l.operator_name,
                "task_type": l.task_type,
                "status": l.status,
                "output_location": l.output_location,
            }
            for l in logs
        ]
        return JsonResponse({"logs": data})
