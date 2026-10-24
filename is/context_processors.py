from django.conf import settings


def settings_processor(request):
    return {
        'WEBPACK_DEPLOYED': settings.WEBPACK_DEPLOYED
    }
