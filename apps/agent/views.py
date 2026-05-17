"""Agent Module – Views."""

from django.http import JsonResponse
from django.views import View

from apps.agent.models import AgentRun


class AgentRunListView(View):
    def get(self, request):
        runs = AgentRun.objects.all()[:30]
        data = [
            {
                "id": r.pk,
                "status": r.status,
                "operator": r.operator_name,
                "instruction": r.instruction[:120],
                "iterations": r.iterations,
                "final_answer": r.final_answer[:300],
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ]
        return JsonResponse({"agent_runs": data})


class AgentRunDetailView(View):
    def get(self, request, pk):
        try:
            run = AgentRun.objects.get(pk=pk)
        except AgentRun.DoesNotExist:
            return JsonResponse({"error": "not found"}, status=404)
        return JsonResponse({
            "id": run.pk,
            "status": run.status,
            "operator": run.operator_name,
            "instruction": run.instruction,
            "iterations": run.iterations,
            "final_answer": run.final_answer,
            "error": run.error_detail,
            "steps": [
                {
                    "step": s.step_number,
                    "tool": s.tool_name,
                    "input": s.tool_input,
                    "output": s.tool_output,
                    "success": s.success,
                }
                for s in run.steps.all()
            ],
        })
