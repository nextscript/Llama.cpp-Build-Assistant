"""Local responsiveness probe with real hardware checks and a synthetic build log."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.theme import apply_theme

app = QApplication([])
apply_theme(app)
window = MainWindow(auto_start=False)
window.ensurePolished()
ticks = []
start = time.monotonic()
frame = [0]
failures = []
window.error = failures.append

def tick():
    ticks.append(time.monotonic())
    frame[0] += 1
    window.resize(1200 + frame[0] % 400, 800 + frame[0] % 200)
    window.move(frame[0] % 100, frame[0] % 100)
    window.stack.setCurrentIndex(frame[0] % window.stack.count())

def work(log):
    for n in range(50000):
        log(f'Build output line {n}')
        if n % 1000 == 0:
            time.sleep(.005)

pulse = QTimer()
pulse.setInterval(10)
pulse.timeout.connect(tick)
pulse.start()
window.run_hardware_check()
window.tasks.start(work, log=window.build_page.log.append)

def finish():
    if window.tasks.active:
        return
    pulse.stop()
    gaps = sorted(b-a for a, b in zip(ticks, ticks[1:]))
    report = {'elapsed_seconds': time.monotonic()-start, 'timer_ticks': len(ticks),
              'max_event_gap_ms': max(gaps, default=0)*1000,
              'p95_event_gap_ms': gaps[int(len(gaps)*.95)]*1000 if gaps else 0,
              'log_blocks': window.build_page.log.document().blockCount(),
              'hardware_check_completed': window.hardware_report is not None,
              'dependency_check_completed': window.dependencies is not None,
              'errors': failures}
    output = Path('build/qt-responsiveness.json')
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    window.geometry_saved = True
    window.close()
    app.exit(0 if not failures else 1)

window.tasks.idle.connect(finish)
sys.exit(app.exec())
