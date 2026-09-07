from rest_framework.routers import DefaultRouter

from apps.mails.views import MailboxMessageViewSet


router = DefaultRouter()

router.register(
    "my-mails",
    MailboxMessageViewSet,
    basename="mail",
)

urlpatterns = router.urls