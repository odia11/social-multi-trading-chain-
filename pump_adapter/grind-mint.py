"""Generate an ephemeral ORC-branded mint; stdout is PRIVATE subprocess IPC only."""
import base64
import fcntl
import secrets
import os
import stat
import sys
import tempfile
import time
from solders.keypair import Keypair

SUFFIX='orc'
ALPHABET='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
TARGET=0
for char in SUFFIX:
    TARGET=TARGET*58+ALPHABET.index(char)
MODULUS=58**len(SUFFIX)

def generate(timeout=85):
    """Bounded vanity search with TWO worker slots for concurrent creators.

    Each slot is a per-UID OS file lock (no mint secrets on disk). Requests
    above the cap fail fast, rather than blocking all Flask workers. Unlike a
    fixed 45-second cutoff, 85 seconds covers long-tail 3-char vanity searches
    while leaving room for the SDK builder and gunicorn's request timeout.
    """
    fd=None
    start=secrets.randbelow(2)
    for slot in (start,1-start):
        path=os.path.join(tempfile.gettempdir(),
                          'orcagent-mint-'+str(os.getuid())+'-'+str(slot)+'.lock')
        candidate=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        info=os.fstat(candidate)
        if info.st_uid!=os.getuid() or not stat.S_ISREG(info.st_mode):
            os.close(candidate)
            raise RuntimeError('Mint generator lock unavailable')
        try:
            fcntl.flock(candidate,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(candidate)
            continue
        fd=candidate
        break
    if fd is None:
        raise RuntimeError('Two orc addresses are being prepared. Please retry shortly.')
    try:
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            for _ in range(256):
                key=Keypair()
                if int.from_bytes(bytes(key.pubkey()),'big')%MODULUS==TARGET:
                    assert str(key.pubkey()).endswith(SUFFIX)
                    return base64.b64encode(bytes(key)).decode('ascii')
        raise RuntimeError('Finding an orc address took too long. Please retry; nothing was sent.')
    finally:
        os.close(fd)

if __name__=='__main__':
    try:
        sys.stdout.write(generate()+'\n')
    except Exception as exc:
        # Only known operational messages; never serialize a key or traceback.
        sys.stderr.write(str(exc) if isinstance(exc,RuntimeError) else 'Mint generator unavailable')
        sys.exit(1)
