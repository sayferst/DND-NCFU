"""Windowed entry point, offline release probes and asynchronous animated startup."""

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--report")
    parser.add_argument("--data-dir")
    args = parser.parse_args(sys.argv[1:])
    if args.data_dir:
        os.environ["RPG_VKR_DATA_DIR"] = args.data_dir
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from rpg_vkr.build_info import APP_NAME, DISPLAY_NAME, VERSION, WINDOWS_APP_ID
    from rpg_vkr.resources import resource_path

    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(QIcon(str(resource_path("rpg_vkr/ui/assets/DND-NCFU.png"))))
    if args.self_check or args.smoke_test:
        from rpg_vkr.self_check import check_resources, write_report

        report = check_resources()
        if args.smoke_test:
            from rpg_vkr.packaged_probe import smoke_test

            report.update(smoke_test(app))
        write_report(args.report, report)
        return 0
    from rpg_vkr.diagnostics import show_error
    from rpg_vkr.ui.loading_screen import LoadingScreen, StartupWorker

    splash = LoadingScreen()
    app._startup_splash = splash
    splash.show()
    worker = StartupWorker(app)
    app._startup_worker = worker
    worker.progress.connect(splash.set_stage)

    def finish():
        try:
            splash.set_stage(85, "Подготовка интерфейса")
            app.processEvents()
            from rpg_vkr.ui.main_window import MainWindow

            app._main_window = MainWindow()
            splash.set_stage(100, "Добро пожаловать")
            app._main_window.show()
            splash.close()
        except Exception as error:
            splash.close()
            show_error(error)
            app.exit(1)

    def failure(error):
        splash.close()
        show_error(error)
        app.exit(1)

    worker.ready.connect(finish)
    worker.failed.connect(failure)
    app.aboutToQuit.connect(worker.wait)
    worker.start()
    return app.exec()
