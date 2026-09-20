from PySide6.QtWidgets import QDialog, QVBoxLayout
from ui.widgets import label, Log, button, row
from ui.workers.update_worker import update_files


class ProgressDialog(QDialog):
    def __init__(self, owner, title, size=(600, 400)):
        super().__init__(owner)
        self.busy = False
        self.setWindowTitle(title)
        self.resize(*size)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 15, 20, 20)
        self.body.addWidget(label(title, 'subtitle'))
        self.log = Log()
        self.body.addWidget(self.log, 1)
        self.close_button = button('Close', self.reject)
        self.body.addWidget(self.close_button)

    def set_busy(self, busy):
        self.busy = busy
        self.close_button.setEnabled(not busy)

    def reject(self):
        if not self.busy:
            super().reject()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)


class UpdateDialog(ProgressDialog):
    def __init__(self, owner, result):
        super().__init__(owner, 'Application Update', (700, 550))
        self.owner, self.result = owner, result
        self.body.insertWidget(1, label(f"Current version: v{result['local']}\nNew version: v{result['remote']}\nCommit: {result['message']}"))
        self.log.setPlainText('\n'.join(result['files']) or '(see commit history)')
        self.download = button('Download Update', self.start, True)
        self.body.addWidget(self.download)

    def start(self):
        self.set_busy(True)
        self.download.setEnabled(False)
        self.log.clear()
        files = list(self.result['files'])
        def done(count):
            self.set_busy(False)
            self.download.setEnabled(True)
            self.download.setText('Restart Now')
            self.download.clicked.disconnect()
            self.download.clicked.connect(self.owner.restart)
        def failed(message):
            self.log.append(f'Update failed: {message}')
            self.set_busy(False)
            self.download.setEnabled(True)
            self.download.setText('Retry')
        self.owner.tasks.start(lambda log: update_files(files, log), done, failed, self.log.append)
