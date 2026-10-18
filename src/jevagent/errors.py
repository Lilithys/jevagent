"""Errors shared by the device layer and replay (kept free of the slow Airtest import)."""


class DeviceError(RuntimeError):
    """The phone cannot be used safely right now; stop and let the user fix it."""


class Interrupted(RuntimeError):
    """Stopped on request; the current gesture has been released."""
