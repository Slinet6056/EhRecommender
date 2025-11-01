"""Custom JobQueue, compatible with Application that cannot be weakref'd"""

from telegram.ext import JobQueue


class SafeJobQueue(JobQueue):
    """Fallback to strong reference when parent class cannot create weakref to Application"""

    def set_application(self, application):  # type: ignore[override]
        try:
            super().set_application(application)
        except TypeError:
            self._application = lambda: application  # type: ignore[assignment]
            self.scheduler.configure(**self.scheduler_configuration)
