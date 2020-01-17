import logging
import os, tempfile, time, hashlib
from subprocess import Popen, DEVNULL, STDOUT
from datetime import datetime

from .getMetaData import CDMetaData

meta = CDMetaData()

def randomHash():
  return hashlib.md5( str(time.time()).encode() ).hexdigest() 

def listDir( directory ):
  files = []
  for item in os.listdir( directory ):
    path = os.path.join( directory, item )
    if os.path.isfile( path ) and path.endswith('.wav'):
      files.append( path )
  return sorted( files )

def cleanUp( directory ):
  for root, dirs, items in os.listdir( directory ):
    for item in items:
      path = os.path.join( root, item )
      if os.path.isfile( path ):
        os.remove( path )
    os.rmdir( root )        

def ripCD( outDirBase ):
  log = logging.getLogger(__name__)

  tmpDir = os.path.join( tempfile.gettempdir(), randomHash() )
  tmpDir = os.path.join( tempfile.gettempdir(), '05eb03c1875061edf9478fe57945c6c6')
  if not os.path.isdir( tmpDir ):
    os.makedirs( tmpDir )

  meta.cache = tmpDir
  tracks     = meta.getMetaData()
  if not tracks:
    return False

  outDir = os.path.join(outDirBase, tracks[0]['albumartist'], tracks[0]['album']) 

  log.info('Starting CD rip')
  t0   = datetime.now()
  proc = Popen( ['cdparanoia', '-Bw'], cwd = tmpDir, stdout=DEVNULL, stderr=STDOUT )
  log.info('Waiting for CD rip to finish')
  proc.wait()
  log.info( 'Rip completed in: {}'.format( datetime.now() - t0 ) )

  log.debug( 'Ejecting disc' )
  Popen( ['eject'] )

  log.info('Converting files to FLAC and placing in: {}'.format( outDir ) )
  if not os.path.isdir( outDir ):
    os.makedirs( outDir )

  
  for info, inFile in zip( tracks, listDir( tmpDir ) ):
    cmd = ['flac']
    if ('cover-art' in info):
      cmd.append( '--picture={}'.format( info.pop('cover-art') ) )
    for key, val in info.items():
      cmd.append( '--tag={}={}'.format( key, val ) )
    outFile = '{:02d} - {}.flac'.format(info['tracknumber'], info['title'])
    outFile = os.path.join( outDir, outFile )
    cmd.append( '--output-name={}'.format(outFile) )
    cmd.append( inFile )
    proc = Popen( cmd, stdout = DEVNULL, stderr = STDOUT )
    proc.wait()
    cleanUp( tmpDir )

  return True
