"""Dev Module – Views."""

from django.http import JsonResponse
from django.views import View
from apps.dev_module.models import CodeGenerationJob


class CodeGenJobListView(View):
    def get(self, request):
        jobs = CodeGenerationJob.objects.all()[:20]
        data = [
            {
                "id": j.pk,
                "tech_stack": j.tech_stack,
                "status": j.status,
                "output_dir": j.output_dir,
                "git_pushed": j.git_pushed,
                "created_at": j.created_at.isoformat(),
            }
            for j in jobs
        ]
        return JsonResponse({"code_gen_jobs": data})
