import logging
import os, tempfile, time, hashlib
from subprocess import Popen, DEVNULL, STDOUT

def randomHash():
  return hashlib.md5( str(time.time()).encode() ).hexdigest() ) 

def ripCD( outDir ):
  log = logging.getLogger(__name__)

  tmpDir = os.path.join( tempfile.gettmpdir, randomHash )
  if not os.path.isdir( tmpDir ):
    os.makedirs( tmpDir )


  log.info('Starting CD rip')
  proc = Popen( ['cdparanoia', '-Bw'], cwd = tmpDir, stdout=DEVNULL, stderr=STDOUT )



  log.info('Waiting for CD rip to finish')
  proc.wait()
  Popen( ['eject'] )
