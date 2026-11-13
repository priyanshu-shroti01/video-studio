"""Local Video Studio: a desktop-browser UI over pipeline/api.py. See docs/STUDIO_GUIDE.md.

The CLI (`video-pipeline ...`) remains the primary automation interface; the Studio calls the same
service functions, so it cannot bypass validation, the scheduler or the approval gate."""


def serve(port: int = 8765, open_browser: bool = False, new_token: bool = False) -> None:
    """Start the Studio on 127.0.0.1:<port> and block (lazy import keeps `python -m studio.server` clean)."""
    from .server import serve as _serve
    _serve(port, open_browser=open_browser, new_token=new_token)
