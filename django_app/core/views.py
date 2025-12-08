from django.http import JsonResponse


def health(request):
    return JsonResponse(
        {
            "status": "ok",
            "service": "django",
            "message": "Django service running",
        }
    )
