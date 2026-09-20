"""Own worker lifetimes and deliver every callback on the GUI thread."""
import time
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt


class Task(QThread):
    result = Signal(object)
    error = Signal(str)
    log = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self._lines = []
        self._last_flush = time.monotonic()

    def write(self, line):
        # Called only by this task. Bounded batches avoid one event per line.
        self._lines.append(str(line).rstrip('\n'))
        if len(self._lines) >= 100 or time.monotonic() - self._last_flush >= .05:
            self.flush()

    def flush(self):
        if self._lines:
            self.log.emit('\n'.join(self._lines))
            self._lines.clear()
            self._last_flush = time.monotonic()

    def run(self):
        try:
            value = self.function(self.write)
            self.flush()
            self.result.emit(value)
        except Exception as exc:
            self.flush()
            self.error.emit(str(exc) or type(exc).__name__)


class Delivery(QObject):
    def __init__(self, success, error, log, done, parent):
        super().__init__(parent)
        self.success, self.failure, self.output, self.done = success, error, log, done

    @Slot(object)
    def result(self, value):
        if self.success:
            self.success(value)

    @Slot(str)
    def error(self, message):
        if self.failure:
            self.failure(message)

    @Slot(str)
    def log(self, text):
        if self.output:
            self.output(text)

    @Slot()
    def finished(self):
        self.done()


class Tasks(QObject):
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = set()

    def start(self, function, success=None, error=None, log=None):
        task = Task(function, self)
        def done():
            self.active.discard(task)
            task.deleteLater()
            delivery.deleteLater()
            if not self.active:
                self.idle.emit()
        delivery = Delivery(success, error, log, done, self)
        task.result.connect(delivery.result, Qt.ConnectionType.QueuedConnection)
        task.error.connect(delivery.error, Qt.ConnectionType.QueuedConnection)
        task.log.connect(delivery.log, Qt.ConnectionType.QueuedConnection)
        task.finished.connect(delivery.finished, Qt.ConnectionType.QueuedConnection)
        self.active.add(task)
        task.start()
        return task
