"""Noninteractive Qt/platform-plugin smoke test, also available in frozen builds."""
import json
from pathlib import Path
from PySide6.QtCore import QLibraryInfo, QTimer
from PySide6.QtGui import QGuiApplication


def run_smoke(app, window, output):
    """Render all pages without starting builds, network checks or saving settings."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pages = []
    for name, page in window.pages.items():
        window.stack.setCurrentWidget(page)
        for key, item in window.nav_buttons.items():
            item.setChecked(key == name)
        window.ensurePolished()
        app.processEvents()
        pixmap = window.grab()
        filename = name.lower().replace(' ', '-') + '.png'
        if not pixmap.save(str(output / filename)):
            raise RuntimeError('Unable to save ' + filename)
        pages.append({'page': name, 'width': pixmap.width(), 'height': pixmap.height()})
    plugin_path = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    report = {'platform': QGuiApplication.platformName(), 'pages': pages,
              'screen_dpr': app.primaryScreen().devicePixelRatio(),
              'sidebar_width': window.sidebar.width(),
              'qwindows_present': (plugin_path / 'platforms' / 'qwindows.dll').exists(),
              'tk_loaded': any(k == 'tkinter' or k == 'customtkinter' for k in __import__('sys').modules)}
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    window.geometry_saved = True
    window.close()
    return 0
