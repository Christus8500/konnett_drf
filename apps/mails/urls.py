from rest_framework.routers import SimpleRouter

from apps.mails.views import MailboxMessageViewSet


router = SimpleRouter()

router.register(
    "my-mails",
    MailboxMessageViewSet,
    basename="mail",
)

urlpatterns = router.urls