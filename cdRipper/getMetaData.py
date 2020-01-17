import logging
try:
  import discid
except:
  logging.getLogger(__name__).critcal("Error importing 'discid', may have to set LD_LIBRARY_PATH")

import os, tempfile
from urllib.request import urlopen
import musicbrainzngs as musicbrainz

from .version import __version__, __url__

musicbrainz.set_useragent( __name__, __version__, __url__ )
  

class CDMetaData( discid.Disc ):
  def __init__(self, features = ["mnc", "isrc"], cache = tempfile.gettempdir() ):
    super().__init__()
    self.log      = logging.getLogger(__name__)
    self.features = features
    self.cache    = cache

  def getMetaData(self):
    releases = self.searchMusicBrainz()
    if releases:
      release = self.filterReleases( releases )
      return self.parseRelease( release )
    return None

  def searchMusicBrainz(self, includes = ['artists', 'recordings', 'isrcs'] ):
   # try:
   #   self.id
   # except:
   #   self.log.debug('Getting information from CD')
   #   self.read( features = self.features )
   # else:
   #   self.log.info("Already have discID: '{}', using it again".format( self.id ) )
    self.read( features = self.features )
    
    self.log.debug( 'Searching for disc on musicbrainz' )
    try:
      result = musicbrainz.musicbrainz.get_releases_by_discid( self.id, 
                 includes = includes )
    except musicbrainz.ResponseError:
      self.log.error( "Disc not found or bad response" )
      return None
    else:
      if ('disc' not in result):
        self.log.warning( 'No disc information returned!' )
        return None
    return result['disc']['release-list']

  def getCoverArt(self, release):
    try:
      imgs = musicbrainz.get_image_list( release['id'] ) 
    except musicbrainz.ResponseError:
      self.log.warning( "Failed to get images" )
    else:
      if ('images' not in imgs):
        self.log.warning( "No image information returned!" )
        return None 
    for img in imgs['images']:
      if img['front']:
        return self._download( img['image'] )
    return None

  def parseRelease( self, release ):
    cover  = self.getCoverArt( release )
    tracks = []
    for i, track in enumerate( release['medium-list']['track-list'] ):
      track = {'artist'                     : release['artist-credit-phrase'],
               'albumartist'                : release['artist-credit-phrase'],
               'album'                      : release['title'],
               'title'                      : track['recording']['title'],
               'tracknumber'                : int(track['number']),
               'totaltracks'                : int(release['medium-list']['track-count']),
               'date'                       : release['date'],
               'asin'                       : release['asin'],
               'isrc'                       : self.tracks[i].isrc,
               'discid'                     : self.id,
               'musicbrainz_trackid'        : track['recording']['id'],
               'musicbrainz_releasetrackid' : track['id'],
               'musicbrainz_artistid'       : '',
               'musicbrainz_albumid'        : release['id'],
        }
      if cover: track['cover-art'] = cover
      tracks.append( track )
    return tracks

  def filterReleases( self, releases ):
    isrcMatches = []
    for release in releases:
      release['medium-list'] = self.filterMediumByFormat( release['medium-list'] )    
      release['medium-list'] = self.filterMediumByISRCs( release['medium-list'] )    
      isrcMatches.append( release['medium-list']['isrc-matches'] )
 
    return releases[ isrcMatches.index( max(isrcMatches) ) ]

  def filterMediumByFormat(self, medium_list, fmt = 'CD'):
    return [ medium for medium in medium_list if medium['format'] == fmt ]
 
  def filterMediumByISRCs( self, medium_list):
    isrcMatches = []
    for medium in medium_list:                                                              # Iterate over all medium; i.e., CD, vinyl, etc.
      nMatch = 0                                                                            # Initialize counter for number of tracks with matching ISRC for given medium
      if (medium['track-count'] == self.last_track_num):                                    # If track counts match between CD and medium
        for i, track in enumerate( medium['track-list'] ):                                  # Iterate over each track in the album get counter for disc check
          if (self.tracks[i].isrc != '') and ('isrc-list' in track['recording']):           # If the ISRC from the disc is NOT empty, and 'isrc-list' is in recoding information
            nMatch += (self.tracks[i].isrc in track['recording']['isrc-list'])              # Increment nMatch based on disc ISRC in medium ISRC list
      medium['isrc-matches'] = nMatch
      isrcMatches.append( nMatch )                                                          # Append nMatch to list of number of track matches
    return medium_list[ isrcMatches.index( max(isrcMatches) ) ]                             # Get maximum number of track matches; get index of that value in array, return release with most track matches based on ISRC

  def _download(self, URL):
    lcl = os.path.join(self.cache, URL.split('/')[-1])
    try:
      img = urlopen( URL ).read()
    except:
      self.log.warning('Failed to download: {}'.format(URL) )
    else:
      with open( lcl, 'wb' ) as fid:
        fid.write( img )
      self.log.info( 'Cover art downloaded to: {}'.format(lcl) )
      return lcl
    return None
