"""Keep the core importable without the optional viewer dependency."""


def require_open3d():
    try:
        import open3d
    except ImportError as exc:
        raise RuntimeError(
            "Open3D is required for PLY import and the viewer. Install the viewer extra "
            "in the project virtual environment: python -m pip install -e '.[viewer]'. "
            "The synthetic --headless probe only needs NumPy."
        ) from exc
    return open3d
