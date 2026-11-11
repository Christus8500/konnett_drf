## CELERY
**After setting up celery and django celery beat, run:**

````bash
python manage.py migrate django_celery_beat
````

**Running celery worker**
In a *separate terminal* (keep your Django server running in another one):
```bash
celery -A myproject worker -l info -P eventlet
```
* `-A myproject` — points to the app defined in `myproject/celery.py`
* `-l info` — log level
* `-P eventlet` — use the eventlet pool (works on Windows, unlike the default `prefork`)


**Running celery beat**
Run beat in yet another terminal:
```bash
celery -A myproject beat -l info
```

1. Terminal 1: `python manage.py runserver`
2. Terminal 2: `celery -A myproject worker -l info -P eventlet`
3. (Optional) Terminal 3: `celery -A myproject beat -l info`


**Quick Troubleshooting**
| Issue | Fix |
|---|---|
| `ValueError: not enough values to unpack` on Windows worker start | You're using the default `prefork` pool — add `-P eventlet` or `-P solo` |
| Worker doesn't pick up tasks | Ensure `CELERY_BROKER_URL` matches your running Redis instance/port |
| Tasks not found / `NotRegistered` error | Check `app.autodiscover_tasks()` is called and `tasks.py` is inside an app listed in `INSTALLED_APPS` |
| Redis connection refused | Confirm Redis is running: `redis-cli ping` should return `PONG` |




## PASSWORD AND EMAIL CHANGE

***-- Frontend requirements***
**PAGES**
**`/forgot-password`**
- Email input, submits `POST /password-reset/` with `{ "email": "..." }`.
- Always show the server's generic message on a 200 ("If an account with that email exists, a reset link has been sent."). Do not add anything that implies whether the account exists.
- Handle `429` (throttled) with a "try again later" message.

**`/reset-password`** (the link target)
- Read `uid` and `token` from the query string.
- Show new password and confirm password fields. Validate they match before submitting.
- Submit `POST /password-reset/confirm/` with `{ uid, token, new_password, confirm_password }`.
- On 200, redirect to login with a success message.
- On 400, show the error. A generic "Invalid or expired reset link" should offer a button back to `/forgot-password`. Field errors (`new_password`, `confirm_password`) should show under their inputs.
- After reading `uid` and `token`, remove them from the address bar with `history.replaceState`, so they do not linger in history or leak through the Referer header.
- Add `<meta name="referrer" content="no-referrer">` on this page.

**`/confirm-email-change`** (the link target)
- Read `token` from the query string.
- Do **not** confirm automatically on page load if you can avoid it. Show a "Confirm email change" button and POST on click, so an accidental load or a prefetch cannot change the email.
- Submit `POST /email-change/confirm/` with `{ "token": "..." }`.
- On 200, show success. If the user is logged in, refetch `/me` (the backend cache is cleared on save). If the user is logged out, send them to login with the new email.
- On 400, show "This link is invalid or has expired" with a link back to settings to request a new one.
- Strip `token` from the URL with `history.replaceState`, as above.

*-- Frontend Settings page (logged-in)*
**Change password**
- A "Send me a reset link" button calls `POST /password-reset/me/` with the auth header and no body. Show the returned message.
**Change email**
- Form with new email and current password, submits `POST /email-change/` with the auth header.
- On 200, show: "Check your new inbox and click the confirmation link. Your email will not change until you do."
- On 400, show field errors: `password` ("Incorrect password."), `new_email` ("Email already exists." or "This is already your email.").
- Handle `429`.

*-- General*
- All the above calls are plain JSON `POST`s. Reset and confirm endpoints need no auth header. `/password-reset/me/` and `/email-change/` do.
- Tell users in the UI that links expire after 24 hours.
- Frontend route names must match the paths used in the email links: `/reset-password` and `/confirm-email-change`. If you rename them, change `send_password_reset_email` and `send_email_change_confirmation` too.
- Set `FRONTEND_URL` correctly per environment (dev, staging, production), or the email links will point to the wrong place.



## Generating the reviewer salt
The salt just needs to be a long random string. Any of these works:
````bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
````
````bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
````

## WEBHOOK
Webhook hardening beyond the signature. After verifying the signature, call the provider’s “verify transaction” endpoint with the reference and confirm the status, amount and currency server-side, rather than trusting the payload. Test it with a wrong signature, a missing header, and the same valid webhook delivered twice.