"""Generate an ephemeral ORC-branded mint; stdout is PRIVATE subprocess IPC only."""
import base64
import fcntl
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

def generate(timeout=45):
    path=os.path.join(tempfile.gettempdir(),'orcagent-mint-'+str(os.getuid())+'.lock')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if info.st_uid!=os.getuid() or not stat.S_ISREG(info.st_mode):
            raise RuntimeError('Mint generator lock unavailable')
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('An orc address is being prepared. Please retry shortly.') from None
        os.nice(10)
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
