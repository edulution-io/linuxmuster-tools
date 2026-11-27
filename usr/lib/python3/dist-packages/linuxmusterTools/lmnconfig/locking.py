"""
Serialize the changes of a configuration file across processes, and detect
changes made in the meantime (ETag).
"""

import fcntl
import hashlib
import os
import re
from contextlib import contextmanager


LOCK_DIR = '/run/lock'


class ConfigChangedError(RuntimeError):
    """Raised when the file changed since the client read it."""


@contextmanager
def locked(path):
    """
    Hold an exclusive lock for a file, from reading it to writing it, so that a
    second change does not undo the first one.

    :param path: The file to change
    """

    name = 'lmntools.' + re.sub(r'[^A-Za-z0-9.-]', '_', str(path).strip('/')) + '.lock'
    with open(os.open(os.path.join(LOCK_DIR, name), os.O_WRONLY | os.O_CREAT, 0o600), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def file_etag(path):
    """
    :return: Strong ETag of the content of the file, the same for a missing
        and an empty file
    :rtype: basestring
    """

    try:
        with open(path, 'rb') as f:
            content = f.read()
    except FileNotFoundError:
        content = b''
    return '"' + hashlib.sha256(content).hexdigest() + '"'


def check_unchanged(path, etag):
    """
    :param etag: ETag the client read, None to skip the check
    :raises ConfigChangedError: the file changed since
    """

    if etag is not None and etag != file_etag(path):
        raise ConfigChangedError(f'{path} changed in the meantime')
