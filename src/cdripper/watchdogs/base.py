"""
Utilities for ripping titles

"""

import logging
import sys
from subprocess import Popen

from PyQt5 import QtCore

if sys.platform.startswith('win'):
    import ctypes

from .. import OUTDIR
from .. import ripper
from ..ui import dialogs

from . import RUNNING


class BaseWatchdog(QtCore.QThread):
    """
    Main watchdog for disc monitoring/ripping

    This thread will run a pyudev monitor instance, looking for changes in
    disc. On change, will spawn the DiscHandler object for handling loading
    of disc information from the database if exists, or prompting using for
    information via a GUI.

    After information is obtained, a rip of the requested/flagged tracks
    will start.

    """

    HANDLE_INSERT = QtCore.pyqtSignal(str)
    HANDLE_EJECT = QtCore.pyqtSignal(str)
    EJECT_DISC = QtCore.pyqtSignal()

    def __init__(
        self,
        progress,
        *args,
        outdir: str = OUTDIR,
        everything: bool = False,
        extras: bool = False,
        convention: str = 'video_utils',
        **kwargs,
    ):
        super().__init__()
        self.log = logging.getLogger(__name__)

        self.HANDLE_INSERT.connect(self.handle_insert)

        self._outdir = None
        self._mounted = []

        self.progress = progress

        self.outdir = outdir

    @property
    def outdir(self):
        return self._outdir

    @outdir.setter
    def outdir(self, val):
        self.log.info('Output directory set to : %s', val)
        self._outdir = val

    def set_settings(self, **kwargs):
        """
        Set options for ripping discs

        """

        self.log.debug('Updating ripping options')
        self.outdir = kwargs.get('outdir', self.outdir)

    def get_settings(self):

        return {
            'outdir': self.outdir,
        }

    def quit(self, *args, **kwargs):
        RUNNING.set()

    @QtCore.pyqtSlot()
    def rip_failure(self):

        dev = self.sender().dev
        dialog = dialogs.RipFailure(dev)
        dialog.exec_()

    @QtCore.pyqtSlot()
    def rip_success(self):

        dev = self.sender().dev
        dialog = dialogs.RipSuccess(dev)
        dialog.exec_()

    @QtCore.pyqtSlot()
    def rip_finished(self):

        sender = self.sender()
        self.log.debug("%s - Processing finished event", sender.dev)
        sender.cancel(sender.dev)

        if sender in self._mounted:
            self._mounted.remove(sender)
        else:
            self.log.warning(
                "%s - Did not find sender object in _mounted",
                sender.dev,
            )
        sender.deleteLater()

    @QtCore.pyqtSlot(str)
    def handle_insert(self, dev):

        obj = ripper.DiscHandler(
            dev,
            self.progress,
            outdir=self.outdir,
        )

        obj.FINISHED.connect(self.rip_finished)
        obj.EJECT_DISC.connect(self.eject_disc)
        self._mounted.append(obj)

    @QtCore.pyqtSlot()
    def eject_disc(self) -> None:
        """
        Eject the disc

        """

        dev = self.sender().dev
        self.log.debug("%s - Ejecting disc", dev)

        if sys.platform.startswith('linux'):
            _ = Popen(['eject', dev])
        elif sys.platform.startswith('win'):
            command = f"open {dev}: type CDAudio alias drive"
            ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
            ctypes.windll.winmm.mciSendStringW(
                "set drive door open",
                None,
                0,
                None,
            )
            ctypes.windll.winmm.mciSendStringW("close drive", None, 0, None)
