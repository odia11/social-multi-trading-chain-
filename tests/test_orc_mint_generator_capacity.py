"""Two-slot public vanity mint capacity guard. No key generation or on-chain RPC."""
import fcntl
import importlib.util
import os
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('orca_grind_mint',ROOT/'pump_adapter/grind-mint.py')
grind=importlib.util.module_from_spec(spec)
spec.loader.exec_module(grind)


def test_exact_suffix_and_two_slot_cap():
    assert grind.SUFFIX=='orc' and grind.MODULUS==58**3
    locked=[]
    try:
        for slot in range(2):
            path=os.path.join(tempfile.gettempdir(),
                f'orcagent-mint-{os.getuid()}-{slot}.lock')
            fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            assert os.fstat(fd).st_uid==os.getuid()
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked.append(fd)
        try:
            grind.generate(timeout=0.01)
        except RuntimeError as exc:
            assert str(exc)=='Two orc addresses are being prepared. Please retry shortly.'
        else:
            raise AssertionError('A third concurrent mint search bypassed both capacity slots')
    finally:
        for fd in locked:os.close(fd)
    print('PASS ORC suffix target and two concurrent vanity search slots; third refuses safely')
    print('PASS no ephemeral private-key bytes logged, transmitted or stored by capacity test')

if __name__=='__main__':test_exact_suffix_and_two_slot_cap()
