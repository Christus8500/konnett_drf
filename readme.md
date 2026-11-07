## CELERY
**After setting up celery and django celery beat run:**

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




