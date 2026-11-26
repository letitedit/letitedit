"""Per-render light match controls for the creator backdrop compositor."""

import contextlib
_enabled = True


@contextlib.contextmanager
def use(enabled=True):
    global _enabled
    old = _enabled
    _enabled = bool(enabled)
    try:
        yield
    finally:
        _enabled = old


def install(backdrop):
    if getattr(backdrop.composite, '_letitedit_light_control', False):
        return
    original = backdrop.composite

    def composite(frame, a, bgf, *args, **kwargs):
        if _enabled and bgf is not None:
            kwargs.setdefault('wrap', .25)
        else:
            kwargs['match'] = 0
            kwargs['wrap'] = 0
        return original(frame, a, bgf, *args, **kwargs)

    composite._letitedit_light_control = True
    backdrop.composite = composite
