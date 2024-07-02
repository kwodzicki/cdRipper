"""
Widgets for disc metadata

"""

import logging

from PyQt5.QtWidgets import (
    QDialog,
    QToolButton,
    QPushButton,
    QDialogButtonBox,
    QTableView,
    QLabel,
    QVBoxLayout,
)

from PyQt5.QtCore import (
    Qt,
    QSize,
    QTimer,
    QAbstractTableModel,
    QModelIndex,
    pyqtSignal,
)

from PyQt5.Qt import QUrl, QDesktopServices
from PyQt5 import QtGui

from . import NAME
from .utils import get_vendor_model

# Codes for what to do
SUBMITTED = 2
RIP = 1
IGNORE = 0


class SelectDisc(QDialog):
    """
    Dialog with timeout for releases

    When a disc is inserted, the disc ID is computed and the MusicBrainz API
    is queried to see if any releases exist. If there are matches, then we want
    the user to be able to pick which one best matches. However, we also want
    this to be headless, so that user does not HAVE to select something.

    So, this dialog will present all options that match the disc ID so that
    user can pick, but it will timeout after a bit, automatically selecting
    the first release in the list.

    """

    # Return code, dev, release information
    FINISHED = pyqtSignal(int, str, dict)

    def __init__(
        self, dev: str,
        releases: list[dict],
        timeout: int | float = 30,
        parent=None,
    ):
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
            "\tSave: Use highlight release for metadata\n"
            "\tIgnore: Ignore the disc and do nothing?\n"
        )

        self.timeout_fmt = "Disc will begin ripping in: {:>4d} seconds"
        self.timeout_label = QLabel(
            self.timeout_fmt.format(self._timeout)
        )

        # Set up model for table containing releases
        self.model = MyTableModel(releases)

        # Build the table
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)  # Hide row names
        self.table.setSelectionBehavior(QTableView.SelectRows)  # Select by row
        self.table.setSelectionMode(QTableView.SingleSelection)  # Select one
        self.table.selectRow(0)  # Select first row by default

        # Setup layout and add widgets
        layout = QVBoxLayout()
        layout.addWidget(
            QLabel(message)
        )
        layout.addWidget(self.timeout_label)
        layout.addWidget(self.table)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

        # Set up widget title
        vendor, model = get_vendor_model(self.dev)
        self.setWindowTitle(f"{NAME} - {vendor} {model}")

        # Set timeout timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._message_timeout)
        self._timer.start(1000)
        self.show()

    def _message_timeout(self) -> None:
        """
        Timeout method

        This method is called every time the timer times out (every second).
        When called, the timeout attribute is decremented by one. While the
        timeout is geater than zero, we update the QLabel for time remaining
        and return, otherwise, we stop the timer and call the done method.

        """

        self._timeout -= 1
        if self._timeout > 0:
            self.timeout_label.setText(
                self.timeout_fmt.format(self._timeout)
            )
            return

        self._timer.stop()
        self.done(RIP)

    def action(self, button) -> None:
        """
        Called on button press

        When any button is pressed, this method is triggered. We first stop
        the timeout-timer. Then, if the wait button (HelpRole) has been passed,
        we clear the timeout text QLabel and just return; we only wanted to
        disable the timeout.

        If made futher, we check if the save button was selected, passing the
        RIP flag to the done method and returning.

        If made futher, then we are ignoring and pass the IGNORE flag to done()

        """

        # Stop timer
        self._timer.stop()

        # If button has HelpRole, then erase timer label and return
        if self.button_box.buttonRole(button) == QDialogButtonBox.HelpRole:
            self.timeout_label.setText('')
            return

        # If is the Save button, then signal rip and return
        if button == self.button_box.button(QDialogButtonBox.Save):
            self.done(RIP)
            return

        # Just ignore disc
        self.done(IGNORE)

    def done(self, arg) -> None:
        """
        Overload the done method to fire custom signal

        The standard done method only pass the result through the finished
        signal. By overloading, we can run standard done() method, but then
        fire our one signal to provide more information about what to do.

        """

        # Call super class done method
        super().done(arg)

        # Initalize release; if arg is RIP, then get release from row index
        release = {}
        if arg == RIP:
            row = self.table.selectionModel().selectedRows()[0].row()
            release = self.model.releases[row]

        # Emit signal
        self.FINISHED.emit(self.result(), self.dev, release)


class SubmitDisc(QDialog):
    """
    Dialog to submit disc ID to MusicBrainz

    If no release information is obtained from MusicBrainz for a disc ID,
    provide a button the user can push to submit the ID to MusicBrainz.
    The URL is created by the discid package.

    Notes:
        Perhaps this should also be a timeout dialog, where if the user does
        not push the button within a given timeout, nothing happens.

    """

    FINISHED = pyqtSignal(str)

    def __init__(self, dev: str, url: str, parent=None):
        super().__init__(parent)

        self.log = logging.getLogger(__name__)
        self.dev = dev
        self.url = url

        # Set up botton (with icon) to trigger open of URL in browser
        self.icon = QtGui.QIcon.fromTheme("media-optical")
        self.submit_button = QToolButton()
        self.submit_button.setIcon(self.icon)
        self.submit_button.setIconSize(QSize(128, 128))
        self.submit_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        )
        self.submit_button.setText("Submit disc ID")
        self.submit_button.clicked.connect(self.submit)

        # Button for ignore the disc
        self.ignore_button = QPushButton("Ignore")
        self.ignore_button.clicked.connect(self.ignore)

        # But to signal that the disc ID has been submitted to MusciBrainz.
        # Note that this button is not initially added to the layout
        # See the submit() method
        self.submitted_button = QPushButton("Submitted!")
        self.submitted_button.clicked.connect(self.submitted)

        message = (
            "The inserted disc was not found on MusicBrainz.\n"
            "Would you like to submit the ID to the database?\n"
            "This will require you to login to MusicBrainz.\n"
        )

        self.message = QLabel(message)

        # Set layout and add widgets
        layout = QVBoxLayout()
        layout.addWidget(self.message)
        layout.addWidget(
            self.submit_button,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        layout.addWidget(self.ignore_button)
        self.setLayout(layout)

        self.show()

    def submit(self, *args, **kwargs) -> None:
        """
        Open submission URL in web browser

        """

        # Define URL and open in webbrowser
        url = QUrl(self.url)
        _ = QDesktopServices.openUrl(url)

        # Get widget layout
        layout = self.layout()

        # Remove the submit and ignore buttons
        layout.removeWidget(self.submit_button)
        layout.removeWidget(self.ignore_button)
        self.submit_button = None
        self.ignore_button = None

        # Add the "submitted" button to the layout and update text
        layout.addWidget(self.submitted_button)
        self.message.setText(
            "After you have submitted to ID on the webpage, \n"
            "press the below button"
        )

    def submitted(self, *args, **kwargs) -> None:
        """
        Triggered by the "Submitted" button

        Signals that disc ID has been submitted to MusicBrainz so that
        rescan/research of disc can be done.

        """

        self.done(SUBMITTED)

    def ignore(self, *args, **kwargs) -> None:
        """Ignore the disc; do nothing"""
        self.log.info("Ignoring")
        self.done(IGNORE)

    def done(self, arg):
        """
        Overload done() so have custom signal

        """

        # Run original done method
        super().done(arg)

        # If IGNORE signaled, then emit emtpy string and return
        if arg == IGNORE:
            self.FINISHED.emit('')
            return

        # If SUBMITTED signaled, then emit dev device
        if arg == SUBMITTED:
            self.FINISHED.emit(self.dev)
            return


class MyTableModel(QAbstractTableModel):
    """
    Table model for release information

    """

    def __init__(self, releases, parent=None):
        super().__init__(parent)

        # Column names
        self.columns = [
            'Release Title',
            'Medium Title',
            'Disc Number',
            'Artist',
            'Format',
            'Country',
            'Date',
            'Barcode',
        ]

        # Iterate to create table rows and flattend information for releases.
        # The flattened release informaiton is created by expanding each
        # medium object in the list of mediums for a release into its own
        # "release" object.
        data = []
        releases_flat = []
        for release in releases:
            for medium in release['medium-list']:
                release_flat = release.copy()
                release_flat['medium-list'] = medium
                releases_flat.append(release_flat)
                discnum = (
                    str(medium.get('position', '1')),
                    str(release.get('medium-count', '1')),
                )
                info = [
                    release.get('title', ''),
                    medium.get('title', ''),
                    '/'.join(discnum),
                    release.get('artist-credit-phrase', ''),
                    medium.get('format', '??'),
                    release.get('country', '??'),
                    release.get('date', '??'),
                    release.get('barcode', ''),
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
