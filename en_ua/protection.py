"""Password focus handling without retaining accessible field contents."""


class PasswordFocusGuard:
    def __init__(self, monitor, password_role):
        self.monitor = monitor
        self.password_role = password_role
        self.source = None

    def __call__(self, event, *_):
        if not event.detail1:
            # A late blur from the previous field must not unprotect a newly
            # focused password field.
            if event.source == self.source:
                was_protected = self.monitor.protected
                self.monitor.protected = False
                self.source = None
                if was_protected:
                    self.monitor.tracker.reset()
            return
        self.source = event.source
        was_protected = self.monitor.protected
        try:
            self.monitor.protected = event.source.get_role() == self.password_role
        except Exception:
            # Unknown focused fields stay protected until they lose focus.
            self.monitor.protected = True
        if self.monitor.protected:
            self.monitor.tracker.reset(blocked=True)
        elif was_protected:
            self.monitor.tracker.reset()
