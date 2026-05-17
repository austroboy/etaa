"""Confirmation Module – Views."""

import json
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from apps.confirmation.services import process_confirmation_response


@method_decorator(csrf_exempt, name="dispatch")
class ConfirmationResponseView(View):
    def post(self, request):
        data = json.loads(request.body or "{}")
        phone = data.get("phone", "")
        text  = data.get("text", "")
        result = process_confirmation_response(phone, text)
        if result:
            return JsonResponse({"resolved": True, "status": result.status, "id": result.pk})
        return JsonResponse({"resolved": False})
