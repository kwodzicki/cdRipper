"""
Utilities for ripping titles

"""

import logging
import os
import subprocess
from PyQt5 import QtCore

from . import utils
from . import metadata
from .ui import dialogs


class DiscHandler(QtCore.QObject):
    """
    Handle new disc event

    """

    def __init__(self, dev: str, outdir=None, progress_dialog=None):
        super().__init__()
        self.log = logging.getLogger(__name__)
        self.dev = dev
        self.outdir = outdir
        self.progress_dialog = progress_dialog

        self.metadata = None
        self.selector = None
        self.submitter = None
        self.ripper = None

        self.disc_lookup(self.dev)

    def isRunning(self):
        """
        Check if is Running:

        """

        # If ripper not yet defined, still going through motions
        # i.e., running
        if self.ripper is None:
            return True

        # Else, return status of the ripper
        return self.ripper.isRunning()

    def terminate(self):
        """
        Kill/close all objects

        """

        if self.metadata is not None:
            self.metadata.terminate()
            self.metadata = None
        if self.selector is not None:
            self.selector.close()
            self.selector = None
        if self.submitter is not None:
            self.submitter.close()
            self.submitter = None
        if self.ripper is not None:
            self.ripper.terminate()
            self.ripper = None

    def submit_discid(self, dev: str, submit_url: str):
        """
        Submit a discid to musicbrainz

        The disc_lookup() method is connected to the dialog so that when
        closes, method is called.

        Arguments:
            dev (str): Dev device discid was run on
            submit_url (str): URL used to submit the disc ID to MusicBrainz

        """

        if dev != self.dev:
            return

        self.submitter = dialogs.SubmitDisc(dev, submit_url)
        self.submitter.FINISHED.connect(self.disc_lookup)

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

        if dev != self.dev:
            return

        self.selector = dialogs.SelectDisc(dev, releases)
        self.selector.FINISHED.connect(self.rip_disc)

    @QtCore.pyqtSlot(str)
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

        if dev != self.dev:
            return

        self.metadata = metadata.CDMetaThread(dev)
        self.metadata.FINISHED.connect(self.process_search)
        self.metadata.start()

    @QtCore.pyqtSlot(str)
    def process_search(self, dev: str) -> None:
        """
        Process result of disc ID search

        This method is meant to be called after a CDMetaThread thread finishes
        scanning and search MusicBrainz. The results of that search are
        processed here, calling the necessary function to either submit the
        disc ID to MusicBrainz or to attempt a rip.

        Arguments:
            dev (str): The dev device that was used to compute disc ID.

        """

        if dev != self.dev:
            return

        self.log.info("%s - Running select release", dev)
        if self.metadata is None:
            return

        if self.metadata.result is None:
            self.log.info("%s - No metadata found for disc", dev)
            return

        if isinstance(self.metadata.result, str):
            self.submit_discid(dev, self.metadata.result)
            return

        self.select_release(dev, self.metadata.result)

    @QtCore.pyqtSlot(str, int, dict)
    def rip_disc(self, dev: str, result: int, release: dict) -> None:
        """
        Attempt disc rip

        Given the /dev path to a disc, load information from database if
        it exists or open GUI for user to input information

        Arguments:
            dev (str) : Device to rip from

        """

        if dev != self.dev:
            return

        if result == dialogs.IGNORE:
            return

        if self.metadata is None:
            return

        self.ripper = Ripper(
            dev,
            self.metadata,
            release,
            self.outdir,
            progress=self.progress_dialog,
        )
        self.ripper.start()


class Ripper(QtCore.QThread):

    def __init__(
        self,
        dev: str,
        metadata: metadata.CDMetaThread,
        release: dict,
        outdir: str,
        progress=None,
    ):
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
        self.metadata = metadata
        self.release = release
        self.tmpdir = metadata.tmpdir
        self.outdir = outdir
        self.progress = progress

        self.progress.CANCEL.connect(self.terminate)

    def run(self):
        """
        Process run in separate thread

        """

        tracks = self.metadata.parseRelease(self.release)
        if self.progress is not None:
            self.log.info('Emitting add disc signal')
            self.progress.ADD_DISC.emit(self.dev, tracks)

        outdir = os.path.join(
            self.outdir,
            tracks['album_info']['albumartist'],
            tracks['album_info']['album'],
        )

        self.proc = utils.cdparanoia(self.dev, self.tmpdir)
        if self.progress is not None:
            utils.cdparanoia_progress(self.dev, self.proc, self.progress)

        _ = self.proc.communicate()
        if self.proc.returncode == 0:
            self.status = utils.convert2FLAC(
                self.dev,
                self.tmpdir,
                outdir,
                tracks,
            )

        utils.cleanup(self.tmpdir)

        subprocess.call(['eject', self.dev])

    @QtCore.pyqtSlot(str)
    def terminate(self, dev: str):
        if dev != self.dev:
            return

        self._dead = True
        if self.proc is None:
            return
        self.proc.kill()
