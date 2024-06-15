import logging
import os
import tempfile
from urllib.request import urlopen

try:
    import discid
except ModuleNotFoundError:
    logging.getLogger(__name__).critical(
        "Error importing 'discid', may have to set LD_LIBRARY_PATH",
    )

import musicbrainzngs as musicbrainz

from . import __version__, __url__

musicbrainz.set_useragent(
    __name__,
    __version__,
    __url__,
)


class CDMetaData(discid.Disc):
    """
    Sub-class of discid.Disc that enables searching of MusicBrainz

    """

    def __init__(
        self,
        features=["mnc", "isrc"],
        cache=tempfile.gettempdir(),
        **kwargs,
    ):
        super().__init__()
        self.log = logging.getLogger(__name__)
        self.features = features
        self.cache = cache

    def getMetaData(self, dev=None):
        """
        Download metadata based on discid

        Arguments:
          None.

        Keyword Arguments:
          None.

        Returns:
          dict: Meta

        """

        # Run method to search MusicBrainz using discid
        releases = self.searchMusicBrainz(dev=dev)
        if releases:  # If releases found based on discid
            release = self.filterReleases(releases)  # Filter the releases
            # Parse releases into internal format and return
            return self.parseRelease(release)
        return None  # If made here, no releases matched, return None

    def searchMusicBrainz(
        self,
        dev=None,
        includes=['artists', 'recordings', 'isrcs'],
    ):
        """
        Search the MusicBrainz database for release based on discid

        Arguments:
          None.

        Keyword arguments:
          includes (list) : Attributes a release must contain to be considered?

        Returns:

        """

        # Read given features from the disc
        self.read(device=dev, features=self.features)

        self.log.debug("Discid: %s", self.id)

        self.log.debug('Searching for disc on musicbrainz')
        try:
            result = (
                musicbrainz
                .musicbrainz
                .get_releases_by_discid(
                    self.id,
                    includes=includes,
                )
            )
        except musicbrainz.ResponseError:
            self.log.error("Disc not found or bad response")
            return None
        else:
            if ('disc' not in result):
                self.log.warning('No disc information returned!')
                return None
        # Return list of releases with matching discid
        return result['disc'].get('release-list', None)

    def getCoverArt(self, release):
        """
        Get cover art for given release

        Arguments:
          release : A release object

        Keyword arguments:
          None.

        Returns:
          Path to cover art if download success, None otherwise

        """

        try:
            imgs = musicbrainz.get_image_list(release['id'])
        except musicbrainz.ResponseError:
            self.log.warning("Failed to get images")
        else:
            if 'images' not in imgs:
                self.log.warning("No image information returned!")
                return None
        for img in imgs['images']:
            if img['front']:
                return self._download(img['image'])
        return None

    def parseRelease(self, release):
        """
        Parse information from release into internal format

        Arguments:
          release : Release object

        Keyword arguments:
          None.

        Returns:
          list: List of dictionaries containing track information for tagging

        """

        cover = self.getCoverArt(release)
        tracks = []
        for i, track in enumerate(release['medium-list']['track-list']):
            track = {
                'artist': release['artist-credit-phrase'],
                'albumartist': release['artist-credit-phrase'],
                'album': release['title'],
                'title': track['recording']['title'],
                'tracknumber': int(track['number']),
                'totaltracks': int(release['medium-list']['track-count']),
                'discnumber': int(release['medium-list']['position']),
                'totaldiscs': int(release['medium-count']),
                'date': release['date'],
                'asin': release['asin'],
                'isrc': self.tracks[i].isrc,
                'discid': self.id,
                'musicbrainz_trackid': track['recording']['id'],
                'musicbrainz_releasetrackid': track['id'],
                'musicbrainz_artistid': '',
                'musicbrainz_albumid': release['id'],
            }

            if cover:
                track['cover-art'] = cover
            tracks.append(track)

        return tracks

    def filterReleases(self, releases):

        isrcMatches = []
        for release in releases:
            release['medium-list'] = self.filterMediumByFormat(
                release['medium-list']
            )
            release['medium-list'] = self.filterMediumByISRCs(
                release['medium-list']
            )
            isrcMatches.append(release['medium-list']['isrc-matches'])

        return releases[isrcMatches.index(max(isrcMatches))]

    def filterMediumByFormat(
        self,
        medium_list: list[dict],
        fmt: str = 'CD',
    ) -> list[dict]:

        return [
            medium
            for medium in medium_list
            if fmt in medium['format']
        ]

    def filterMediumByISRCs(self, medium_list: list[dict]) -> dict:
        isrcMatches = []
        # Iterate over all medium; i.e., CD, vinyl, etc.
        for medium in medium_list:
            nMatch = 0
            medium['isrc-matches'] = nMatch
            isrcMatches.append(nMatch)
            # If track counts NOT match between CD and medium, skip
            if medium['track-count'] != self.last_track_num:
                continue

            # Iterate over each track in the album get counter for disc check
            for i, track in enumerate(medium['track-list']):
                # If ISRC from track is emtpy, continue
                if self.tracks[i].isrc == '':
                    continue

                # If 'isrc-list' is NOT in recoding information, continue
                if 'isrc-list' not in track['recording']:
                    continue

                nMatch += (
                    self.tracks[i].isrc in track['recording']['isrc-list']
                )  # Increment nMatch based on disc ISRC in medium ISRC list

            medium['isrc-matches'] = nMatch
            isrcMatches[-1] = nMatch

        # Get maximum number of track matches; get index of that value in
        # array, return release with most track matches based on ISRC
        return medium_list[isrcMatches.index(max(isrcMatches))]

    def _download(self, url: str):
        """
        Download remote file to local machine given url

        Arguments:
            url (str): Full URL of remote file to download

        Keyword arguments:
            None.

        Returns:
            str: Path to local file if success, None otherwise

        """

        ext = url.split('.')[-1]
        lcl = os.path.join(self.cache, f"coverart.{ext}")
        try:
            img = urlopen(url).read()  # Open and read remote file
        except Exception:
            self.log.warning('Failed to download: %s', url)
        else:  # If download success
            with open(lcl, mode='wb') as fid:
                fid.write(img)
            self.log.info('Cover art downloaded to: %s', lcl)
            return lcl  # Return path to local file

        # If made here, download failed, return None
        return None
