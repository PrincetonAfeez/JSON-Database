"""Concurrent-access correctness.

The scope file says: 'If a read sees invalid JSON, raise DatabaseFormatError
rather than trying to repair the file.' That is never supposed to happen in
practice because writes use `os.replace`, which is atomic at the OS level.
This module pins that property by running a writer alongside several readers
and asserting that every read returns a structurally valid state.

This test takes a few seconds. Keep it modest so the suite stays fast.
"""

import subprocess
import sys

from json_database import Database


def test_readers_during_writer_never_see_partial_state(tmp_path):
    path = tmp_path / "app.jsondb"
    Database(path).init()

    writer_code = (
        "import sys\n"
        "from json_database import Database\n"
        "db = Database(sys.argv[1], timeout=60)\n"
        "for i in range(40):\n"
        "    db.collection('c').insert({'i': i})\n"
    )

    reader_code = (
        "import sys, time\n"
        "from json_database import Database\n"
        "db = Database(sys.argv[1], timeout=60)\n"
        "deadline = time.time() + float(sys.argv[2])\n"
        "reads = 0\n"
        "while time.time() < deadline:\n"
        "    docs = db.collection('c').all()\n"
        "    _ = [d['i'] for d in docs]\n"
        "    reads += 1\n"
        "print(reads)\n"
    )

    duration = 3.0
    writer = subprocess.Popen(
        [sys.executable, "-c", writer_code, str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    readers = [
        subprocess.Popen(
            [sys.executable, "-c", reader_code, str(path), str(duration)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(3)
    ]

    w_stdout, w_stderr = writer.communicate(timeout=duration + 30)
    assert writer.returncode == 0, w_stderr

    total_reads = 0
    for r in readers:
        r_stdout, r_stderr = r.communicate(timeout=duration + 30)
        assert r.returncode == 0, r_stderr
        total_reads += int(r_stdout.strip() or "0")

    # Each reader should have completed at least a handful of reads.
    assert total_reads > 0, "readers never observed a complete state"

    # Final on-disk state is still valid.
    db = Database(path)
    assert db.check_integrity().ok
