"""Start the Qt application. All presentation code lives in ui/."""
import multiprocessing
import os
import sys


def main():
    multiprocessing.freeze_support()
    # Windowed PyInstaller executables have no console streams.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LlamaCpp.BuildAssistant')
    from PySide6.QtWidgets import QApplication
    from ui.theme import apply_theme
    from ui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName('Llama.cpp Build Assistant')
    app.setOrganizationName('Llama.cpp Build Assistant')
    apply_theme(app)
    smoke = '--smoke-test' in sys.argv
    window = MainWindow(auto_start=not smoke)
    if smoke:
        from ui.validation import run_smoke
        index = sys.argv.index('--smoke-test')
        output = sys.argv[index + 1] if index + 1 < len(sys.argv) else 'build/qt-smoke'
        return run_smoke(app, window, output)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
