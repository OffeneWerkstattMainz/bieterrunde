"""
Periodic jobs, run by the RQ cron scheduler (``manage.py rqcron owm_portal.cron``).

The worker uses ``django_tasks_rq.Job``, which only runs jobs whose import path points to a
django-tasks ``Task`` and which carry the task backend's name in their meta. Registering the
undecorated function (``task.func``) yields exactly that import path.
"""

from django.conf import settings
from rq import cron

from signup.tasks import process_signups

TASK_META = {"backend_name": "default"}

cron.register(process_signups.func, "default", interval=settings.SIGNUP_INTERVAL, meta=TASK_META)
