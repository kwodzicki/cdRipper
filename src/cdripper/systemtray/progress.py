import logging

from PyQt5.QtWidgets import (
    QWidget,
    QProgressBar,
    QLabel,
    QPushButton,
    QMessageBox,
    QVBoxLayout,
    QGridLayout,
    QFrame,
)
from PyQt5.QtCore import Qt, pyqtSlot, pyqtSignal

from ..utils import get_vendor_model


class ProgressDialog(QWidget):

    # First arg in dev, second is all info
    ADD_DISC = pyqtSignal(str, list)
    # Arg is dev of disc to remove
    REMOVE_DISC = pyqtSignal(str)
    # First arg is dev, second is track num
    CUR_TRACK = pyqtSignal(str, int)
    # First arg is dev, second is size of cur track
    TRACK_SIZE = pyqtSignal(str, int)
    # dev of the rip to cancel
    CANCEL = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.log = logging.getLogger(__name__)
        self.enabled = False

        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowCloseButtonHint
        )

        self.widgets = {}
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        self.ADD_DISC.connect(self.add_disc)
        self.REMOVE_DISC.connect(self.remove_disc)
        self.CUR_TRACK.connect(self.current_track)
        self.TRACK_SIZE.connect(self.track_size)

    def __len__(self):
        return len(self.widgets)

    @pyqtSlot(str, list)
    def add_disc(self, dev: str, info: list):
        self.log.debug("Adding disc: %s", dev)
        widget = ProgressWidget(dev, info)
        widget.CANCEL.connect(self.cancel)

        self.layout.addWidget(widget)
        self.widgets[dev] = widget
        self.show()

    @pyqtSlot(str)
    def remove_disc(self, dev: str):
        self.log.debug("Removing disc: %s", dev)
        widget = self.widgets.pop(dev, None)
        if widget is not None:
            self.layout.removeWidget(widget)
            widget.deleteLater()
        if len(self.widgets) == 0:
            self.setVisible(False)

    @pyqtSlot(str, int)
    def current_track(self, dev: str, title: int):
        self.log.debug("Setting current track: %s - %s", dev, title)
        widget = self.widgets.get(dev, None)
        if widget is None:
            return
        widget.current_track(title)

    @pyqtSlot(str, int)
    def track_size(self, dev, tsize):
        self.log.debug("Update current track size: %s - %d", dev, tsize)
        widget = self.widgets.get(dev, None)
        if widget is None:
            return
        widget.track_size(tsize)

    @pyqtSlot(str)
    def cancel(self, dev):
        self.CANCEL.emit(dev)
        self.REMOVE_DISC.emit(dev)


class ProgressWidget(QFrame):
    """
    Progress for a single disc

    Notes:
        All sizes are converted from bytes (assumed input units) to megabytes
        to stay unders 32-bit integer range.

    """

    CANCEL = pyqtSignal(str)  # dev to cancel rip of

    def __init__(self, dev: str, info: list):
        super().__init__()

        self.setFrameStyle(
            QFrame.StyledPanel | QFrame.Plain
        )
        self.setLineWidth(1)

        self.track_progs = [0] * len(info)
        self.current_title = None
        self.dev = dev
        self.info = info

        vendor, model = get_vendor_model(dev)
        self.title = QLabel(f"{vendor} {model} : {dev}")
        self.track_label = QLabel('')
        self.track_count = QLabel('')
        self.track_prog = QProgressBar()
        self.track_prog.setRange(0, 100)
        self.track_prog.setValue(0)

        self.disc_label = QLabel('Overall Progress')
        self.disc_prog = QProgressBar()
        self.disc_prog.setRange(0, len(info) * 100)
        self.disc_prog.setValue(0)

        self.cancel_but = QPushButton("Cancel Rip")
        self.cancel_but.clicked.connect(self.cancel)

        layout = QGridLayout()
        layout.addWidget(self.title, 0, 0, 1, 3)
        layout.addWidget(self.track_label, 10, 0)
        layout.addWidget(self.track_count, 10, 2)
        layout.addWidget(self.track_prog, 11, 0, 1, 3)
        layout.addWidget(self.disc_label, 20, 0, 1, 3)
        layout.addWidget(self.disc_prog, 21, 0, 1, 3)
        layout.addWidget(self.cancel_but, 30, 0, 1, 3)

        self.setLayout(layout)

    def __len__(self):
        return len(self.info)

    def cancel(self, *args, **kwargs):

        message = QMessageBox()
        res = message.question(
            self,
            '',
            "Are you sure you want to cancel the rip?",
            message.Yes | message.No,
        )
        if res == message.Yes:
            self.CANCEL.emit(self.dev)

    def current_track(self, title: int):
        """
        Update current track index

        Change the currently-being-worked-on-track to a new track

        Arguments:
            title (str): Title number from disc being ripperd

        """

        # If the current_title is not None, then refers to previously
        # processed track and must update the total size of that track
        # to be maximum size of the track
        if self.current_title is not None:
            self.track_prog.setValue(100)
            self.track_progs[self.current_title] = 100

        self.track_label.setText(
            f"Outfile: ",
        )
        self.track_count.setText(
            f"Title: {title}/{len(self)}",
        )

        self.track_prog.setValue(0)
        self.current_title = title - 1 

    def track_size(self, tsize: int):
        """
        Update track size progress

        Updat

        """

        self.track_progs[self.current_title] = tsize
        self.track_prog.setValue(tsize)
        self.disc_prog.setValue(sum(self.track_progs))
