"""Catch startup and Qt callback errors before windowed builds can lose diagnostics."""

import sys


def launch():
    from rpg_vkr.diagnostics import show_error

    sys.excepthook = lambda kind, error, tb: show_error(error, tb)
    try:
        from rpg_vkr.app import main

        return main()
    except Exception as error:
        if "--self-check" in sys.argv or "--smoke-test" in sys.argv:
            from rpg_vkr.diagnostics import record_error
            from rpg_vkr.self_check import write_report

            record_error(error)
            report = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv else None
            try:
                write_report(report, {"ok": False, "error_type": type(error).__name__})
            except (OSError, ValueError):
                pass
        else:
            show_error(error)
        return 1
