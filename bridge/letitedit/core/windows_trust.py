"""Downloads check certificates the way Windows and its browsers do.

Python's own check reads the root certificates already in Windows' store. A fresh Windows holds only a few and
fetches the others the first time something asks Windows itself to check a site, so on a clean PC Python's check
fails ("CERTIFICATE_VERIFY_FAILED") where Edge succeeds. `truststore` (MIT, in the tool environment) hands the check
to Windows. use() turns it on for this process, once; without the package nothing changes.
"""
_done = False


def use():
    global _done
    if _done:
        return True
    try:
        import truststore
        truststore.inject_into_ssl()
        _done = True
    except Exception:       # no truststore (an older environment): Python's own check, as before
        return False
    return True
