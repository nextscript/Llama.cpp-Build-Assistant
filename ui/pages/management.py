import json
from PySide6.QtWidgets import QTableWidgetItem
from ui.widgets import Page, card, row, button, table


class ManagementPage(Page):
    def __init__(self, owner, kind):
        super().__init__('Build Sources Management' if kind == 'Sources' else 'Build Profiles')
        self.kind, self.owner = kind, owner
        panel, layout = card()
        singular = 'Source' if kind == 'Sources' else 'Profile'
        layout.addWidget(row(button('Add ' + singular, lambda: owner.edit_item(kind), True),
                             button('Refresh', owner.reload_data)))
        self.body.addWidget(panel)
        headers = (['Name', 'Repository URL', 'Branch', 'Commit', 'Actions'] if kind == 'Sources'
                   else ['Name', 'Build Type', 'CMake Flags', 'Actions'])
        self.table = table(headers)
        self.body.addWidget(self.table, 1)

    def populate(self, values):
        self.table.setRowCount(len(values))
        for index, value in enumerate(values):
            keys = ['name', 'repo_url', 'branch', 'commit'] if self.kind == 'Sources' else ['name', 'build_type', 'cmake_flags']
            for column, key in enumerate(keys):
                content = value.get(key, '')
                if isinstance(content, list):
                    content = ' '.join(content)
                item = QTableWidgetItem(str(content))
                item.setToolTip(str(content))
                self.table.setItem(index, column, item)
            actions = row(button('Edit', lambda checked=False, v=value: self.owner.edit_item(self.kind, v)),
                          button('Delete', lambda checked=False, v=value: self.owner.delete_item(self.kind, v), danger=True))
            self.table.setCellWidget(index, len(keys), actions)
        self.table.horizontalHeader().resizeSection(len(keys) if values else self.table.columnCount()-1, 190)


class HistoryPage(Page):
    def __init__(self, owner):
        super().__init__('Build History')
        panel, layout = card()
        layout.addWidget(button('Refresh History', owner.load_history, True))
        self.body.addWidget(panel)
        self.table = table(['Date', 'Source', 'Type', 'Build', 'Commit', 'Branch', 'Success', 'Path', 'Duration', 'Error'])
        self.body.addWidget(self.table, 1)
        self.entries = []
        self.table.cellDoubleClicked.connect(lambda r, c: owner.show_text('Build Result', json.dumps(self.entries[r], indent=2)))

    def populate(self, entries):
        self.entries = list(reversed(entries))
        self.table.setRowCount(len(entries))
        keys = ['date', 'source_name', 'build_type', 'build_number', 'commit', 'branch', 'success', 'build_path', 'duration_seconds', 'error_message']
        for r, entry in enumerate(self.entries):
            for c, key in enumerate(keys):
                text = str(entry.get(key, ''))
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(r, c, item)
