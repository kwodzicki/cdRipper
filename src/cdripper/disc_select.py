import logging
import sys

from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QTableView,
    QLabel,
    QVBoxLayout,
)

from PyQt5.QtCore import (
    Qt,
    QTimer,
    QAbstractTableModel,
    QModelIndex,
    pyqtSignal,
)

# from ..utils import get_vendor_model

RIP = 1
IGNORE = 0


class SelectDisc(QDialog):
    """
    Dialog with timeout for discs in database

    When a disc is inserted, a check is done to see if the disc
    exisis in the disc database. If the disc does exist, this
    dialog should be shown to give the use some options for what
    to do; save/rip the disc, open the disc metadata for editing,
    or just ignore the disc all together.

    To enable user-less interaction, however, the dialog has a
    timeout feature that automatically selects save/rip disc
    after a certain amount of time. This way, the user can
    just insert discs and forget about them (assuming they are in
    the database) or do other things.

    """

    # Return code, dev, release information
    FINISHED = pyqtSignal(int, str, dict)

    def __init__(self, dev, releases, parent=None, timeout=30):
        super().__init__(parent)

        self.log = logging.getLogger(__name__)
        self.dev = dev
        self._timeout = timeout
        qbtn = (
            QDialogButtonBox.Save
            | QDialogButtonBox.Ignore
        )
        self.button_box = QDialogButtonBox(qbtn)
        self.button_box.addButton('Wait', QDialogButtonBox.HelpRole)
        self.button_box.clicked.connect(self.action)

        message = (
            "The inserted disc matched to the following releases.\n"
            "Select the on that best matches your disc.\n"
            "On timeout the first will be selected automatically.\n"
            "Would you like to:\n\n"
            "\tWait: I need more time; disable timeout\n"
            "\tSelect: Use highlight release for metadata\n"
            "\tIgnore: Ignore the disc and do nothing?\n"
        )

        self.timeout_fmt = "Disc will begin ripping in: {:>4d} seconds"
        self.timeout_label = QLabel(
            self.timeout_fmt.format(self._timeout)
        )

        self.row = None

        self.model = MyTableModel(releases)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.selectRow(0)

        layout = QVBoxLayout()
        layout.addWidget(
            QLabel(message)
        )
        layout.addWidget(self.timeout_label)
        layout.addWidget(self.table)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

        self._timer = QTimer()
        self._timer.timeout.connect(self._message_timeout)
        self._timer.start(1000)
        self.show()

    def _message_timeout(self):
        self._timeout -= 1
        if self._timeout > 0:
            self.timeout_label.setText(
                self.timeout_fmt.format(self._timeout)
            )
            return
        self._timer.stop()
        self.done(RIP)

    def action(self, button):
        self._timer.stop()
        if self.button_box.buttonRole(button) == QDialogButtonBox.HelpRole:
            self.timeout_label.setText('')
            return

        if button == self.button_box.button(QDialogButtonBox.Save):
            self.row = self.table.selectionModel().selectedRows()[0].row()
            self.done(RIP)
            return

        self.done(IGNORE)

    def done(self, arg):

        super().done(arg)

        release = {} if self.row is None else self.model.releases[self.row]
        self.FINISHED.emit(self.result(), self.dev, release)


class MyTableModel(QAbstractTableModel):
    def __init__(self, releases, parent=None):
        super().__init__(parent)

        self.columns = ['Title', 'Artist', 'Format', 'Country', 'Date']

        data = []
        releases_flat = []
        for release in releases:
            for medium in release['medium-list']:
                release_flat = release.copy()
                release_flat['medium-list'] = medium
                releases_flat.append(release_flat)

                info = [
                    release['title'],
                    release['artist-credit-phrase'],
                    medium.get('format', 'NA'),
                    release['country'],
                    release['date'],
                ]
                data.append(info)

        self.data = data
        self.releases = releases_flat

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int,
    ):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self.columns[section]
            return ""

    def columnCount(self, parent=None):
        return len(self.data[0])

    def rowCount(self, parent=None):
        return len(self.data)

    def data(self, index: QModelIndex, role: int):
        if role == Qt.DisplayRole:
            row = index.row()
            col = index.column()
            return str(self.data[row][col])


if __name__ == "__main__":
    app = QApplication(sys.argv)

    inst = SelectDiscOptions('/dev/sr0')

    # print(view.selectionModel().selectedRows())
    app.exec_()
