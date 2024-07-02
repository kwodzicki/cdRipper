"""
Utilities for ripping titles

"""

import logging
import argparse
import os
import signal
import subprocess
from threading import Event
from PyQt5.QtCore import QThread, pyqtSlot

import pyudev

from . import LOG, STREAM
from . import utils
from .disc_metadata import CDMetaThread
from .disc_select import SelectDisc, SubmitDisc, IGNORE

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

        self._selector = {}
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
            self.disc_lookup(dev)

    def _ejecting(self, dev):

        proc = self._mounted.pop(dev, None)
        if proc is None:
            return

        if proc.isRunning():
            self.__log.warning("%s - Killing the ripper process!", dev)
            proc.kill()
            return

    def quit(self, *args, **kwargs):
        RUNNING.set()

    def submit_discid(self, dev: str, submit_url: str):
        """
        Submit a discid to musicbrainz

        The disc_lookup() method is connected to the dialog so that when
        closes, method is called.

        Arguments:
            dev (str): Dev device discid was run on
            submit_url (str): URL used to submit the disc ID to MusicBrainz

        """

        submitter = SubmitDisc(dev, submit_url)
        submitter.FINISHED.connect(self.disc_lookup)
        self._selector[dev] = submitter

    def select_release(self, dev: str, releases: list[dict]):
        """
        Dialog to select release for disc

        If releases found, then open a dialog that contains a table of all
        releases with matching disc ID so that user can select which one is
        correct.

        The rip_disc() method is connected to the dialog so that when closes,
        method is called.

        Arguments:
            dev (str): Device dics is mount in
            releases (list): List of releases that match the disc id

        """

        selector = SelectDisc(dev, releases)
        selector.FINISHED.connect(self.rip_disc)
        self._selector[dev] = selector

    @pyqtSlot(str)
    def disc_lookup(self, dev: str):
        """
        Used to compute and search disc ID

        Launch a QThread that will scan dev device to compute the disc ID.
        Then, use this disc ID to search for matching releases in the
        MusicBrainz database.

        We connect the process_search() to the thread so that is called when
        thread completes.

        """

        # If empty dev device name, then we are ignorning
        if dev == '':
            return

        meta = CDMetaThread(dev)
        meta.FINISHED.connect(self.process_search)
        self._mounted[dev] = meta
        meta.start()

    @pyqtSlot(str)
    def process_search(self, dev: str):
        """
        Process result of disc ID search

        This method is meant to be called after a CDMetaThread thread finishes
        scanning and search MusicBrainz. The results of that search are
        processed here, calling the necessary function to either submit the
        disc ID to MusicBrainz or to attempt a rip.

        Arguments:
            dev (str): The dev device that was used to compute disc ID.

        """

        self.__log.warning("%s - Running select release", dev)
        meta = self._mounted.get(dev, None)
        if meta is None:
            return

        if meta.result is None:
            self.__log.info("No metadata found for disc: %s", dev)
            return

        print(meta.result)
        if isinstance(meta.result, str):
            self.submit_discid(dev, meta.result)
            return

        self.select_release(dev, meta.result)

    @pyqtSlot(int, str, dict)
    def rip_disc(self, result, dev, release):
        """
        Attempt disc rip

        Given the /dev path to a disc, load information from database if
        it exists or open GUI for user to input information

        Arguments:
            dev (str) : Device to rip from

        """

        if result == IGNORE:
            return

        meta = self._mounted.get(dev, None)
        if meta is None:
            return

        ripper = Ripper(
            dev,
            meta.parseRelease(release),
            meta.tmpdir,
            self.outdir,
            progress=self.progress_dialog,
        )
        ripper.start()
        self._mounted[dev] = ripper


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
            self.tracks['album_info']['albumartist'],
            self.tracks['album_info']['album'],
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
