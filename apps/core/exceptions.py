from rest_framework.views import exception_handler


# Custom exception handler for DRF to format error responses consistently
def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            "success": False,
            "errors": response.data
        }

    return response