from django.conf import settings


def project_version(request):
    return {"PROJECT_VERSION": settings.PROJECT_VERSION}
