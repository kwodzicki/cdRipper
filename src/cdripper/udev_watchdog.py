"""
Utilities for ripping titles

"""

import logging
import signal
from threading import Event
from PyQt5 import QtCore

import pyudev

from .ripper import DiscHandler

KEY = 'DEVNAME'
CHANGE = 'DISK_MEDIA_CHANGE'
CDTYPE = "ID_CDROM"
STATUS = "ID_CDROM_MEDIA_STATE"
EJECT = "DISK_EJECT_REQUEST"  # This appears when initial eject requested
READY = "SYSTEMD_READY"  # This appears when disc tray is out

SIZE_POLL = 10

RUNNING = Event()

signal.signal(signal.SIGINT, lambda *args: RUNNING.set())
signal.signal(signal.SIGTERM, lambda *args: RUNNING.set())


class UdevWatchdog(QtCore.QThread):
    """
    Main watchdog for disc monitoring/ripping

    This function will run a pyudev monitor instance,
    looking for changes in disc. On change, will
    spawn the DiscDialog widget loading
    information from the database if exists, or
    prompting using for information via a GUI.

    After information is obtained, a rip of the
    requested/flagged tracks will start.

    The logic for disc mounting is a bit obtuse, so will try to explain.
    When the disc is initially inserted, it should trigger an event where
    the CHANGE property is set. As the dev should NOT be in mounted list,
    we add it to the mounting list. The next event for that dev is the event
    that the disc is fully mounted. This will NOT have the CHANGE property.
    As the disc is still in the mounting list at this point, will NOT enter
    the if-statement there and will remove dev from mounting list, add dev
    to mounted list, and then run the ripping process.

    On future calls without the CHANGE property, the dev will NOT be in
    the mounting list, so we will just skip them. For an event WITH the
    CHANGE property, since the dev IS in the mounted list, we remove it
    from the mounted list and log information that it has been ejected.

    """

    HANDLE_DISC = QtCore.pyqtSignal(str)

    def __init__(
        self,
        outdir,
        progress_dialog=None,
        **kwargs,
    ):
        """
        Arguments:
            outdir (str) : Top-level directory for ripping files

        Keyword arguments:
            everything (bool) : If set, then all titles identified
                for ripping will be ripped. By default, only the
                main feature will be ripped
            extras (bool) : If set, only 'extra' features will
                be ripped along with the main title(s). Main
                title(s) include Theatrical/Extended/etc.
                versions for movies, and episodes for series.
            fileGen (func) : Function to use to generate
                output file names based on information
                from the database. This function must
                accept (outdir, info, extras=bool), where info is
                a dictionary of data loaded from the
                disc database, and extras specifies if
                extras should be ripped.

        """

        super().__init__()
        self.__log = logging.getLogger(__name__)
        self.__log.debug("%s started", __name__)

        self.HANDLE_DISC.connect(self.handle_disc)
        self._outdir = None

        self.outdir = outdir
        self.progress_dialog = progress_dialog

        self._mounted = {}
        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by(subsystem='block')

    @property
    def outdir(self):
        return self._outdir

    @outdir.setter
    def outdir(self, val):
        self.__log.info('Output directory set to : %s', val)
        self._outdir = val

    def set_settings(self, **kwargs):
        """
        Set options for ripping discs

        """

        self.__log.debug('Updating ripping options')
        self.outdir = kwargs.get('outdir', self.outdir)

    def get_settings(self):

        return {
            'outdir': self.outdir,
        }

    def run(self):
        """
        Processing for thread

        Polls udev for device changes, running MakeMKV pipelines
        when dvd/bluray found

        """

        self.__log.info('Watchdog thread started')
        while not RUNNING.is_set():
            device = self._monitor.poll(timeout=1.0)
            if device is None:
                continue

            # Get value for KEY. If is None, then did not exist, so continue
            dev = device.properties.get(KEY, None)
            if dev is None:
                continue

            # Every optical drive should support CD, so check if the device
            # has the CDTYPE flag, if not we ignore it 
            if device.properties.get(CDTYPE, '') != '1':
                continue

            if device.properties.get(EJECT, ''):
                self.__log.debug("%s - Eject request", dev)
                self._ejecting(dev)
                continue

            if device.properties.get(READY, '') == '0':
                self.__log.debug("%s - Drive is ejected", dev)
                self._ejecting(dev)
                continue

            if device.properties.get(CHANGE, '') != '1':
                self.__log.debug(
                    "%s - Not a '%s' event, ignoring",
                    dev,
                    CHANGE,
                )
                continue

            # The STATUS key does not seem to exist for CD
            if device.properties.get(STATUS, '') != '':
                self.__log.debug(
                    '%s - Caught event that was NOT insert/eject, ignoring',
                    dev,
                )
                continue

            if dev in self._mounted:
                self.__log.info('%s - Device in mounted list', dev)
                continue

            self.__log.debug('%s - Finished mounting', dev)
            self._mounted[dev] = None
            self.HANDLE_DISC.emit(dev)

    def _ejecting(self, dev):

        proc = self._mounted.pop(dev, None)
        if proc is None:
            return

        if proc.isRunning():
            self.__log.warning("%s - Killing the ripper process!", dev)
            proc.terminate()
            return

    def quit(self, *args, **kwargs):
        RUNNING.set()

    @QtCore.pyqtSlot(str)
    def handle_disc(self, dev: str):

        self._mounted[dev] = DiscHandler(
            dev,
            self.outdir,
            self.progress_dialog,
        )
