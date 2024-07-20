import logging
import os

from PyQt5 import QtWidgets
from PyQt5 import QtCore
from PyQt5 import Qt
from PyQt5 import QtGui

from .. import NAME
from . import utils

# Codes for what to do
SUBMITTED = 2
RIP = 1
IGNORE = 0


class MissingOutdirDialog(QtWidgets.QDialog):
    def __init__(self, outdir, name=NAME):
        super().__init__()

        self._name = name
        self.setWindowTitle(f"{self._name}: Output Directory Missing!")

        QBtn = (
            QtWidgets.QDialogButtonBox.Ok
            | QtWidgets.QDialogButtonBox.Abort
        )

        self.buttonBox = QtWidgets.QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.layout = QtWidgets.QVBoxLayout()
        message = (
            "Could not find the requested output directory: ",
            os.linesep,
            outdir,
            os.linesep,
            "Would you like to select a new one?",
        )
        message = QtWidgets.QLabel(
            os.linesep.join(message)
        )
        self.layout.addWidget(message)
        self.layout.addWidget(self.buttonBox)
        self.setLayout(self.layout)


class SettingsWidget(QtWidgets.QDialog):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.outdir = PathSelector('Output Location:')

        self.set_settings()

        buttons = (
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box = QtWidgets.QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.outdir)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def set_settings(self):

        settings = utils.load_settings()
        if 'outdir' in settings:
            self.outdir.setText(settings['outdir'])

    def get_settings(self):

        settings = {
            'outdir': self.outdir.getText(),
        }
        utils.save_settings(settings)
        return settings


class SelectDisc(QtWidgets.QDialog):
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

    # Return dev, code, release information
    FINISHED = QtCore.pyqtSignal(str, int, dict)

    def __init__(
        self, dev: str,
        releases: list[dict],
        timeout: int | float = 30,
        name: str = NAME,
        parent=None,
    ):
        super().__init__(parent)

        self.log = logging.getLogger(__name__)
        self.dev = dev
        self._timeout = timeout
        self._name = name

        qbtn = (
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Ignore
        )
        self.button_box = QtWidgets.QDialogButtonBox(qbtn)
        self.button_box.addButton('Wait', QtWidgets.QDialogButtonBox.HelpRole)
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
        self.timeout_label = QtWidgets.QLabel(
            self.timeout_fmt.format(self._timeout)
        )

        # Set up model for table containing releases
        self.model = MyTableModel(releases)

        # Build the table
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        # Hide row names
        self.table.verticalHeader().setVisible(False)
        # Select by row
        self.table.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        # Select one
        self.table.setSelectionMode(QtWidgets.QTableView.SingleSelection)
        self.table.selectRow(0)  # Select first row by default

        # Setup layout and add widgets
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(
            QtWidgets.QLabel(message)
        )
        layout.addWidget(self.timeout_label)
        layout.addWidget(self.table)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

        # Set up widget title
        vendor, model = utils.get_vendor_model(self.dev)
        self.setWindowTitle(f"{self._name} - {vendor} {model}")

        # Set timeout timer
        self._timer = QtCore.QTimer()
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
        role = self.button_box.buttonRole(button)
        if role == QtWidgets.QDialogButtonBox.HelpRole:
            self.timeout_label.setText('')
            return

        # If is the Save button, then signal rip and return
        if button == self.button_box.button(QtWidgets.QDialogButtonBox.Save):
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
        self.FINISHED.emit(self.dev, self.result(), release)


class SubmitDisc(QtWidgets.QDialog):
    """
    Dialog to submit disc ID to MusicBrainz

    If no release information is obtained from MusicBrainz for a disc ID,
    provide a button the user can push to submit the ID to MusicBrainz.
    The URL is created by the discid package.

    Notes:
        Perhaps this should also be a timeout dialog, where if the user does
        not push the button within a given timeout, nothing happens.

    """

    FINISHED = QtCore.pyqtSignal(str)

    def __init__(self, dev: str, url: str, name=NAME, parent=None):
        super().__init__(parent)

        self.log = logging.getLogger(__name__)
        self.dev = dev
        self.url = url
        self._name = name

        # Set up botton (with icon) to trigger open of URL in browser
        self.icon = QtGui.QIcon.fromTheme("media-optical")
        self.submit_button = QtWidgets.QToolButton()
        self.submit_button.setIcon(self.icon)
        self.submit_button.setIconSize(QtCore.QSize(128, 128))
        self.submit_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        )
        self.submit_button.setText("Submit disc ID")
        self.submit_button.clicked.connect(self.submit)

        # Button for ignore the disc
        self.ignore_button = QtWidgets.QPushButton("Ignore")
        self.ignore_button.clicked.connect(self.ignore)

        # But to signal that the disc ID has been submitted to MusciBrainz.
        # Note that this button is not initially added to the layout
        # See the submit() method
        self.submitted_button = QtWidgets.QPushButton("Submitted!")
        self.submitted_button.clicked.connect(self.submitted)

        message = (
            "The inserted disc was not found on MusicBrainz.\n"
            "Would you like to submit the ID to the database?\n"
            "This will require you to login to MusicBrainz.\n"
        )

        self.message = QtWidgets.QLabel(message)

        # Set layout and add widgets
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.message)
        layout.addWidget(
            self.submit_button,
            0,
            QtCore.Qt.AlignmentFlag.AlignHCenter,
        )
        layout.addWidget(self.ignore_button)
        self.setLayout(layout)

        vendor, model = utils.get_vendor_model(self.dev)
        self.setWindowTitle(f"{self._name} - {vendor} {model}")

        self.show()

    def submit(self, *args, **kwargs) -> None:
        """
        Open submission URL in web browser

        """

        # Define URL and open in webbrowser
        url = Qt.QUrl(self.url)
        _ = Qt.QDesktopServices.openUrl(url)

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


class PathSelector(QtWidgets.QWidget):

    def __init__(self, label, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.__log = logging.getLogger(__name__)
        self.path = None

        self.path_text = QtWidgets.QLineEdit()
        self.path_button = QtWidgets.QPushButton('Select Path')
        self.path_button.clicked.connect(self.path_select)

        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(self.path_text)
        layout.addWidget(self.path_button)
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(QtWidgets.QLabel(label))
        layout.addWidget(widget)

        self.setLayout(layout)

    def setText(self, var):

        self.path_text.setText(var)

    def getText(self):

        return self.path_text.text()

    def path_select(self, *args, **kwargs):

        path = (
            QtWidgets
            .QFileDialog
            .getExistingDirectory(self, 'Select Folder')
        )
        if path != '' and os.path.isdir(path):
            self.setText(path)
            self.__log.info(path)


class MyTableModel(QtCore.QAbstractTableModel):
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
        orientation: QtCore.Qt.Orientation,
        role: int,
    ):
        if role == QtCore.Qt.DisplayRole:
            if orientation == QtCore.Qt.Horizontal:
                return self.columns[section]
            return ""

    def columnCount(self, parent=None):
        return len(self.data[0])

    def rowCount(self, parent=None):
        return len(self.data)

    def data(self, index: QtCore.QModelIndex, role: int):
        if role == QtCore.Qt.DisplayRole:
            row = index.row()
            col = index.column()
            return str(self.data[row][col])
