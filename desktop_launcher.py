"""Frozen Windows entry point; divert spawned workers before importing the GUI."""
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    from workflow_dashboard.desktop import launch_desktop
    raise SystemExit(launch_desktop())
