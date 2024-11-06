import logging

from PyQt5 import QtWidgets
from PyQt5 import QtCore

from .. import NAME
from .utils import get_vendor_model


class ProgressDialog(QtWidgets.QWidget):

    # First arg in dev, second is all info
    CD_ADD_DISC = QtCore.pyqtSignal(str, dict)
    # Arg is dev of disc to remove
    CD_REMOVE_DISC = QtCore.pyqtSignal(str)
    # First arg is dev, second is track num
    CD_CUR_TRACK = QtCore.pyqtSignal(str, str)
    # First arg is dev, second is size of cur track
    CD_TRACK_SIZE = QtCore.pyqtSignal(str, int)
    # dev of the rip to cancel
    CANCEL = QtCore.pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.log = logging.getLogger(__name__)
        self.enabled = False

        self.setWindowFlags(
            self.windowFlags()
            & ~QtCore.Qt.WindowCloseButtonHint
        )

        self.setWindowTitle(f"{NAME} - Rip Progress")

        self.widgets = {}
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)

        self.CD_ADD_DISC.connect(self.cd_add_disc)
        self.CD_REMOVE_DISC.connect(self.cd_remove_disc)
        self.CD_CUR_TRACK.connect(self.cd_current_track)
        self.CD_TRACK_SIZE.connect(self.cd_track_size)

    def __len__(self):
        return len(self.widgets)

    @QtCore.pyqtSlot(str, dict)
    def cd_add_disc(self, dev: str, info: dict):
        self.log.debug("%s - Disc addeds", dev)
        widget = ProgressWidget(dev, info)
        widget.CANCEL.connect(self.cancel)

        self.layout.addWidget(widget)
        self.widgets[dev] = widget
        self.show()
        self.adjustSize()

    @QtCore.pyqtSlot(str)
    def cd_remove_disc(self, dev: str):
        widget = self.widgets.pop(dev, None)
        if widget is not None:
            self.layout.removeWidget(widget)
            widget.deleteLater()
            self.log.debug("%s - Disc removed", dev)
        if len(self.widgets) == 0:
            self.setVisible(False)
        self.adjustSize()

    @QtCore.pyqtSlot(str, str)
    def cd_current_track(self, dev: str, title: str):
        widget = self.widgets.get(dev, None)
        if widget is None:
            return
        self.log.debug("%s - Setting current track: %s", dev, title)
        widget.current_track(title)

    @QtCore.pyqtSlot(str, int)
    def cd_track_size(self, dev, tsize):
        widget = self.widgets.get(dev, None)
        if widget is None:
            return
        self.log.debug("%s - Update current track size: %d", dev, tsize)
        widget.track_size(tsize)

    @QtCore.pyqtSlot(str)
    def cancel(self, dev):
        self.CANCEL.emit(dev)
        self.CD_REMOVE_DISC.emit(dev)


class ProgressWidget(QtWidgets.QFrame):
    """
    Progress for a single disc

    Notes:
        All sizes are converted from bytes (assumed input units) to megabytes
        to stay unders 32-bit integer range.

    """

    CANCEL = QtCore.pyqtSignal(str)  # dev to cancel rip of

    def __init__(self, dev: str, info: dict):
        super().__init__()

        self.log = logging.getLogger(__name__)
        self.setFrameStyle(
            QtWidgets.QFrame.StyledPanel | QtWidgets.QFrame.Plain
        )
        self.setLineWidth(1)

        self.track_progs = []
        self.current_title = None
        self.dev = dev
        self.info = info

        album_info = info.get('album_info', {})
        tot_tracks = album_info.get('totaltracks', 'NA')
        disc_num = album_info.get('discnumber', 'NA')
        tot_discs = album_info.get('totaldiscs', 'NA')

        vendor, model = get_vendor_model(dev)

        # Set up label for name of the drive disc is in
        self.drive_name = QtWidgets.QLabel(
            f"Device: {vendor} {model} [{dev}]",
        )

        # Set up label for name of the artist
        self.artist_label = QtWidgets.QLabel("Artist:")
        self.artist = QtWidgets.QLabel(
            album_info.get('artist', 'NA')
        )

        # Set up label for name of the album
        self.album_label = QtWidgets.QLabel("Album:")
        self.album = QtWidgets.QLabel(
            album_info.get('album', 'NA')
        )

        # Set up label for name of the track being ripped
        self.track_label = QtWidgets.QLabel("Track:")
        self.track = QtWidgets.QLabel('')

        # Set label for total number of tracks on album
        self.track_count = QtWidgets.QLabel(
            f"[of {tot_tracks}]"
        )

        # Set label for disc number/total number of discs
        self.disc_count_label = QtWidgets.QLabel("Disc:")
        self.disc_count = QtWidgets.QLabel(
            f"{disc_num}/{tot_discs}"
        )

        # Set up progress bar for rip of track
        self.track_prog = QtWidgets.QProgressBar()
        self.track_prog.setRange(0, 100)
        self.track_prog.setValue(0)

        # Set up progress bar for overall disc rip
        self.disc_label = QtWidgets.QLabel('Overall Progress')
        self.disc_prog = QtWidgets.QProgressBar()
        self.disc_prog.setRange(0, len(info) * 100)
        self.disc_prog.setValue(0)

        # Button to cancel ripping
        self.cancel_but = QtWidgets.QPushButton("Cancel Rip")
        self.cancel_but.clicked.connect(self.cancel)

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self.drive_name, 0, 0, 1, 3)

        layout.addWidget(self.artist_label, 10, 0)
        layout.addWidget(self.artist, 10, 1)

        layout.addWidget(self.album_label, 11, 0)
        layout.addWidget(self.album, 11, 1)

        layout.addWidget(self.track_label, 12, 0)
        layout.addWidget(self.track, 12, 1)
        layout.addWidget(self.track_count, 12, 2)

        layout.addWidget(self.disc_count_label, 13, 0)
        layout.addWidget(self.disc_count, 13, 1)

        layout.addWidget(self.track_prog, 15, 0, 1, 3)
        layout.addWidget(self.disc_label, 20, 0, 1, 3)
        layout.addWidget(self.disc_prog, 21, 0, 1, 3)
        layout.addWidget(self.cancel_but, 30, 0, 1, 3)

        self.setLayout(layout)

    def __len__(self):
        return len(self.info)

    def cancel(self, *args, **kwargs):

        message = QtWidgets.QMessageBox()
        res = message.question(
            self,
            '',
            "Are you sure you want to cancel the rip?",
            message.Yes | message.No,
        )
        if res == message.Yes:
            self.CANCEL.emit(self.dev)

    def current_track(self, title: str):
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
            self.track_progs[-1] = 100

        self.track_progs.append(0)
        info = self.info.get(title, {})
        if len(info) == 0:
            self.log.error(
                "%s - Missing track info for track # %s",
                self.dev,
                title,
            )

        self.track.setText(
            f"{title} - {info.get('title', 'N/A')}",
        )

        self.current_title = title

    def track_size(self, tsize: int):
        """
        Update track size progress

        Updat

        """

        if len(self.track_progs) == 0:
            return

        self.track_progs[-1] = tsize
        self.track_prog.setValue(tsize)
        self.disc_prog.setValue(sum(self.track_progs))
