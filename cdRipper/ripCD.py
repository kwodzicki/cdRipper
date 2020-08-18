import logging
import os, tempfile, time, hashlib
from subprocess import Popen, DEVNULL, STDOUT
from datetime import datetime

from .getMetaData import CDMetaData

meta = CDMetaData()

def randomHash():
  """Generate random hash for temporary directory"""

  return hashlib.md5( str(time.time()).encode() ).hexdigest() 

def listDir( directory ):
  """
  Get sorted list of all files with '.wav' extension in a directory

  Arguments:
    directory (str): Top-level path of directory to search for .wav files

  Keyword arguments:
    None.

  Returns:
    list: Full file paths to all .wav files in directory

  """
  files = []
  for item in os.listdir( directory ):
    path = os.path.join( directory, item )
    if os.path.isfile( path ) and path.endswith('.wav'):
      files.append( path )
  return sorted( files )

def cleanUp( directory ):
  """Recursively delete directory"""

  for root, dirs, items in os.walk( directory ):
    for item in items:
      path = os.path.join( root, item )
      if os.path.isfile( path ):
        os.remove( path )
    os.rmdir( root )        

def ripCD( outDir ):
  """
  Rip CD to a temporary directory

  Arguments:
    outDir (str): Top-level directory to rip CD files to.

  Keyword arguments:
    None.

  Returns:
    bool

  """
  log = logging.getLogger(__name__)

  log.info('Starting CD rip')
  t0   = datetime.now()
  proc = Popen( ['cdparanoia', '-Bw'], cwd = outDir, stdout=DEVNULL, stderr=STDOUT )
  log.info('Waiting for CD rip to finish')
  proc.wait()
  log.info( 'Rip completed in: {}'.format( datetime.now() - t0 ) )

  log.debug( 'Ejecting disc' )
  Popen( ['eject'] )

  return True

def convert2FLAC( srcDir, outDir, tracks ):
  """
  Convert wav files ripped from CD to FLAC

  Arguments:
    srcDir (str): Top-level directory of ripped CD files.
    outDir (str): Top-level directory to store FLAC files in. Files will be
      placed in directory with structure: Artist/Album/Tracks.flac
    tracks (list): Dictionaries containing information for each track of the CD

  Keyword arguments:
    None.

  Returns:
    bool

  """
  log = logging.getLogger(__name__)

  log.info('Converting files to FLAC and placing in: {}'.format( outDir ) )
  if not os.path.isdir( outDir ):                                                           # If the outDir does not exist
    os.makedirs( outDir )                                                                   # Create it

  for info, inFile in zip( tracks, listDir( srcDir ) ):                                     # Zip the list of tracks and list of files in directory; iterate over them
    cmd = ['flac']                                                                          # Base command for conversion
    if ('cover-art' in info):                                                               # If key is in the info dictionary
      cmd.append( '--picture={}'.format( info.pop('cover-art') ) )                          # Append picture option to flac command
    for key, val in info.items():                                                           # Iterate over key/value pairs in info
      cmd.append( '--tag={}={}'.format( key, val ) )                                        # Append tag option to flac command
    outFile = '{:02d} - {}.flac'.format(info['tracknumber'], info['title'])                 # Set basename for flac file
    if info['totaldiscs'] > 1:                                                              # If more than one disc in the release
      outFile = '{:d}-{}'.format( info['discnumber'], outFile )                             # Prepend disc number to basename
    outFile = os.path.join( outDir, outFile )                                               # Generate full file path
    cmd.append( '--output-name={}'.format(outFile) )                                        # Append output-name option to flac command
    cmd.append( inFile )                                                                    # Append input file to command
    proc = Popen( cmd, stdout = DEVNULL, stderr = STDOUT )                                  # Run the command
    proc.wait()                                                                             # Wait for command to finish

  return True

def main( outDirBase ):
  """
  Rip CD, convert to FLAC, and tag all files using metadata from MusicBrainz

  Arguments:
    outDirBase (str): Top-level directory to store FLAC files in. Files will be
      placed in directory with structure: Artist/Album/Tracks.flac

  Keyword arguments:
    None.

  Returns:
    bool

  """
  log = logging.getLogger(__name__)

  tmpDir = os.path.join( tempfile.gettempdir(), randomHash() )
  if not os.path.isdir( tmpDir ):
    os.makedirs( tmpDir )

  meta.cache = tmpDir
  tracks     = meta.getMetaData()
  if not tracks:
    return False

  outDir = os.path.join(outDirBase, tracks[0]['albumartist'], tracks[0]['album']) 

  status = ripCD( tmpDir )
  if status:
    status = convert2FLAC( tmpDir, outDir, tracks )
  
  cleanUp( tmpDir )

  return status 
