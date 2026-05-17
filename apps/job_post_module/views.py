"""Job Post Module – Views."""

from django.http import JsonResponse
from django.views import View
from apps.job_post_module.models import JobPost


class JobPostListView(View):
    def get(self, request):
        posts = JobPost.objects.all()[:20]
        data = [
            {
                "id": p.pk,
                "job_title": p.job_title,
                "department": p.department,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
                "jpg_path": p.jpg_path,
            }
            for p in posts
        ]
        return JsonResponse({"job_posts": data})
