"""
Utilities for ripping titles

"""

import logging
import argparse
import os
import signal
import subprocess
from threading import Event
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot

import pyudev

from . import LOG, STREAM
from . import utils
from .metadata import CDMetaThread

KEY = 'DEVNAME'
CHANGE = 'DISK_MEDIA_CHANGE'
STATUS = "ID_CDROM_MEDIA_STATE"
EJECT = "DISK_EJECT_REQUEST"  # This appears when initial eject requested
READY = "SYSTEMD_READY"  # This appears when disc tray is out

SIZE_POLL = 10

RUNNING = Event()

signal.signal(signal.SIGINT, lambda *args: RUNNING.set())
signal.signal(signal.SIGTERM, lambda *args: RUNNING.set())


class RipperWatchdog(QThread):
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

        self._outdir = None

        self.outdir = outdir
        self.progress_dialog = progress_dialog

        self._mounting = {}
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
    
            if device.properties.get(EJECT, ''):
                self.__log.debug("%s - Eject request", dev)
                self._ejecting(dev)
                continue
    
            if device.properties.get(READY, '') == '0':
                self.__log.debug("%s - Drive is ejected", dev)
                self._ejecting(dev)
                continue
    
            if device.properties.get(CHANGE, '') != '1':
                self.__log.debug("%s - Not a '%s' event, ignoring", dev, CHANGE)
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
            meta = CDMetaThread(dev)
            meta.FINISHED.connect(self.rip_disc)
            meta.start()
            self._mounted[dev] = meta

    def _ejecting(self, dev):

        proc = self._mounted.pop(dev, None)
        if proc is None:
            return

        if proc.isRunning():
            self.__log.warning("%s - Killing the ripper process!", dev)
            proc.kill()
            return

        # self.__log.debug(
        #     "Exitcode from ripping processes : %d",
        #     proc.exitcode,
        # )

    def quit(self, *args, **kwargs):
        RUNNING.set()

    @pyqtSlot(str)
    def rip_disc(self, dev):
        """
        Get information about a disc

        Given the /dev path to a disc, load information from database if
        it exists or open GUI for user to input information

        Arguments:
            dev (str) : Device to rip from

        """

        meta = self._mounted.get(dev, None)
        if meta is None:
            return

        if meta.tracks is None:
            self.__log.info("No metadata found for disc: %s", dev)
            return

        ripper = Ripper(
            dev,
            meta.tracks,
            meta.tmpdir,
            self.outdir,
            progress=self.progress_dialog,
        )
        ripper.start()
        self._mounted[dev] = ripper

    @pyqtSlot(int)
    def handle_disc_info(self, result):
        """
        Rip a whole disc

        Given information about a disc, rip
        all tracks. Intended to be run as thread
        so watchdog can keep looking for new discs

        Arguments:
            dev (str) : Device to rip from
            outdir (str) : Directory to save mkv files to
            extras (bool) : Flag for if should rip extras

        """

        # Get list of keys for mounted devices, then iterate over them
        devs = list(self._mounted.keys())
        for dev in devs:
            # Try to pop of information
            disc_info = self._mounted.pop(dev, None)
            if disc_info is None:
                continue

            # Check the "return" status of the dialog
            if result == IGNORE:
                self.__log.info('Ignoring disc: %s', dev)
                return

            # Get information about disc
            if isinstance(disc_info, tuple):
                info, sizes = disc_info
            else:
                info, sizes = disc_info.info, disc_info.sizes

            # Initialize ripper object
            if result == RIP:
                self.rip_disc(dev, info, sizes)
                return

            if result == SAVE:
                self.__log.info("Requested metadata save and eject: %s", dev)
                subprocess.call(['eject', dev])
                return

            if result == OPEN:
                self.disc_dialog(dev, discid=getDiscID(dev, self.root))
                return

            self.__log.error("Unrecognized option: %d", result)

    # def disc_dialog(self, dev, discid=None):

    #     # Open dics metadata GUI and register "callback" for when closes
    #     dialog = DiscDialog(
    #         dev,
    #         dbdir=self.dbdir,
    #         discid=discid,
    #     )
    #     dialog.finished.connect(self.handle_disc_info)
    #     self._mounted[dev] = dialog


class Ripper(QThread):

    def __init__(self, dev, tracks, tmpdir, outdir, progress=None):
        """
        Arguments:
            dev (str): Dev device to rip from
            tracks (list[dict]): List of dictionaries containing informaiton
                about each track
            tmpdir (str): Temporary directory to rip files to
            outdir (str): Directory to put tagged FLAC files in

        """

        super().__init__()
        self.log = logging.getLogger(__name__)

        self._dead = False
        self.proc = None
        self.dev = dev
        self.tracks = tracks
        self.tmpdir = tmpdir
        self.outdir = outdir
        self.progress = progress
 
        self.progress.CANCEL.connect(self.kill)

    def run(self):
        self.rip_disc()
        subprocess.call(['eject', self.dev])

    def rip_disc(self):

        if self.progress is not None:
            self.log.info('Emitting add disc signal')
            self.progress.ADD_DISC.emit(self.dev, self.tracks)

        outdir = os.path.join(
            self.outdir,
            self.tracks[0]['albumartist'],
            self.tracks[0]['album'],
        )

        self.proc = utils.cdparanoia(self.dev, self.tmpdir)
        if self.progress is not None:
            utils.cdparanoia_progress(self.dev, self.proc, self.progress)

        _ = self.proc.communicate()

        print("return code:", self.proc.returncode)

        self.status = utils.convert2FLAC(
            self.dev,
            self.tmpdir,
            outdir,
            self.tracks,
        )

        utils.cleanup(self.tmpdir)

    @pyqtSlot(str)
    def kill(self, dev: str):
        if dev != self.dev:
            return

        self._dead = True
        if self.proc is None:
            return
        self.proc.kill()



def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'outdir',
        type=str,
        help='Directory to save ripped titles to',
    )
    parser.add_argument(
        '--loglevel',
        type=int,
        default=30,
        help='Set logging level',
    )

    args = parser.parse_args()

    STREAM.setLevel(args.loglevel)
    LOG.addHandler(STREAM)
    watchdog = RipperWatchdog(
        args.outdir,
    )
    watchdog.start()
