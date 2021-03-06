# Copyright (C) 2010, 2011 Sebastian Thiel (byronimo@gmail.com) and contributors
#
# This module is part of GitDB and is released under
# the New BSD License: http://www.opensource.org/licenses/bsd-license.php
import binascii
import errno
import hashlib
from io import BytesIO
import logging
import mmap
import os
import shutil
import stat
import sys

from smmap import (
    StaticWindowMapManager,
    SlidingWindowMapManager,
    SlidingWindowMapBuffer
)


#{ Aliases

hex_to_bin = binascii.a2b_hex
bin_to_hex = binascii.b2a_hex

# errors
ENOENT = errno.ENOENT

# os shortcuts
exists = os.path.exists
mkdir = os.mkdir
chmod = os.chmod
isdir = os.path.isdir
isfile = os.path.isfile
rename = os.rename
remove = os.remove
dirname = os.path.dirname
basename = os.path.basename
join = os.path.join
read = os.read
write = os.write
close = os.close
fsync = os.fsync

is_win = (os.name == 'nt')
is_darwin = (os.name == 'darwin')

#} END Aliases

log = logging.getLogger(__name__)

#{ compatibility stuff ...


class _RandomAccessBytesIO(object):

    """Wrapper to provide required functionality in case memory maps cannot or may
    not be used. This is only really required in python 2.4"""
    __slots__ = '_sio'

    def __init__(self, buf=''):
        self._sio = BytesIO(buf)

    def __getattr__(self, attr):
        return getattr(self._sio, attr)

    def __len__(self):
        return len(self.getvalue())

    def __getitem__(self, i):
        return self.getvalue()[i]

    def __getslice__(self, start, end):
        return self.getvalue()[start:end]


def byte_ord(b):
    """
    Return the integer representation of the byte string.  This supports Python
    3 byte arrays as well as standard strings.
    """
    try:
        return ord(b)
    except TypeError:
        return b

#} END compatibility stuff ...

#{ Routines


def rmtree(path):
    """Remove the given recursively.

    :note: we use shutil rmtree but adjust its behaviour to see whether files that
        couldn't be deleted are read-only. Windows will not remove them in that case"""

    def onerror(func, path, exc_info):
        # Is the error an access error ?
        os.chmod(path, stat.S_IWUSR)

        try:
            func(path)  # Will scream if still not possible to delete.
        except Exception:
            raise

    return shutil.rmtree(path, False, onerror)


def make_sha(source=''.encode("ascii")):
    """A python2.4 workaround for the sha/hashlib module fiasco

    **Note** From the dulwich project """
    try:
        return hashlib.sha1(source)
    except NameError:
        import sha  # @UnresolvedImport
        sha1 = sha.sha(source)
        return sha1


def allocate_memory(size):
    """:return: a file-protocol accessible memory block of the given size"""
    if size == 0:
        return _RandomAccessBytesIO(b'')
    # END handle empty chunks gracefully

    try:
        return mmap.mmap(-1, size)  # read-write by default
    except EnvironmentError:
        # setup real memory instead
        # this of course may fail if the amount of memory is not available in
        # one chunk - would only be the case in python 2.4, being more likely on
        # 32 bit systems.
        return _RandomAccessBytesIO(b"\0" * size)
    # END handle memory allocation


def file_contents_ro(fd, stream=False, allow_mmap=True):
    """:return: read-only contents of the file represented by the file descriptor fd

    :param fd: file descriptor opened for reading
    :param stream: if False, random access is provided, otherwise the stream interface
        is provided.
    :param allow_mmap: if True, its allowed to map the contents into memory, which
        allows large files to be handled and accessed efficiently. The file-descriptor
        will change its position if this is False"""
    try:
        if allow_mmap:
            # supports stream and random access
            try:
                return mmap.mmap(fd, 0, access=mmap.ACCESS_READ)
            except EnvironmentError:
                # python 2.4 issue, 0 wants to be the actual size
                return mmap.mmap(fd, os.fstat(fd).st_size, access=mmap.ACCESS_READ)
            # END handle python 2.4
    except OSError:
        pass
    # END exception handling

    # read manully
    contents = os.read(fd, os.fstat(fd).st_size)
    if stream:
        return _RandomAccessBytesIO(contents)
    return contents


def file_contents_ro_filepath(filepath, stream=False, allow_mmap=True, flags=0):
    """Get the file contents at filepath as fast as possible

    :return: random access compatible memory of the given filepath
    :param stream: see ``file_contents_ro``
    :param allow_mmap: see ``file_contents_ro``
    :param flags: additional flags to pass to os.open
    :raise OSError: If the file could not be opened

    **Note** for now we don't try to use O_NOATIME directly as the right value needs to be
    shared per database in fact. It only makes a real difference for loose object
    databases anyway, and they use it with the help of the ``flags`` parameter"""
    fd = os.open(filepath, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | flags)
    try:
        return file_contents_ro(fd, stream, allow_mmap)
    finally:
        close(fd)
    # END assure file is closed


def sliding_ro_buffer(mman, filepath, flags=0):
    """
    :param mman: an instance of :class:`StaticWindowMapManager` to use
    :return: a buffer compatible object which uses our mapped memory manager internally
        ready to read the whole given filepath"""
    return SlidingWindowMapBuffer(mman.make_cursor(filepath), flags=flags)


def to_hex_sha(sha):
    """:return: hexified version  of sha"""
    if len(sha) == 40:
        return sha
    return bin_to_hex(sha)


def to_bin_sha(sha):
    if len(sha) == 20:
        return sha
    return hex_to_bin(sha)


#} END routines


#{ Utilities

## Copied from python std-lib.
class suppress:
    """Context manager to suppress specified exceptions

    After the exception is suppressed, execution proceeds with the next
    statement following the with statement.

         with suppress(FileNotFoundError):
             os.remove(somefile)
         # Execution still resumes here if the file was already removed
    """

    def __init__(self, *exceptions):
        self._exceptions = exceptions

    def __enter__(self):
        pass

    def __exit__(self, exctype, excinst, exctb):
        # Unlike isinstance and issubclass, CPython exception handling
        # currently only looks at the concrete type hierarchy (ignoring
        # the instance and subclass checking hooks). While Guido considers
        # that a bug rather than a feature, it's a fairly hard one to fix
        # due to various internal implementation details. suppress provides
        # the simpler issubclass based semantics, rather than trying to
        # exactly reproduce the limitations of the CPython interpreter.
        #
        # See http://bugs.python.org/issue12029 for more details
        supp = exctype is not None and issubclass(exctype, self._exceptions)
        if supp:
            log.debug("Suppressed exception: %s(%s)", exctype, excinst, exc_info=1)
        return supp


class LazyMixin(object):

    """
    Base class providing an interface to lazily retrieve attribute values upon
    first access. If slots are used, memory will only be reserved once the attribute
    is actually accessed and retrieved the first time. All future accesses will
    return the cached value as stored in the Instance's dict or slot.
    """

    __slots__ = ()

    def __getattr__(self, attr):
        """
        Whenever an attribute is requested that we do not know, we allow it
        to be created and set. Next time the same attribute is reqeusted, it is simply
        returned from our dict/slots. """
        self._set_cache_(attr)
        # will raise in case the cache was not created
        return object.__getattribute__(self, attr)

    def _set_cache_(self, attr):
        """
        This method should be overridden in the derived class.
        It should check whether the attribute named by attr can be created
        and cached. Do nothing if you do not know the attribute or call your subclass

        The derived class may create as many additional attributes as it deems
        necessary in case a git command returns more information than represented
        in the single attribute."""
        pass


class LockedFD(object):

    """
    This class facilitates a safe read and write operation to a file on disk.
    If we write to 'file', we obtain a lock file at 'file.lock' and write to
    that instead. If we succeed, the lock file will be renamed to overwrite
    the original file.

    When reading, we obtain a lock file, but to prevent other writers from
    succeeding while we are reading the file.

    This type handles error correctly in that it will assure a consistent state
    on destruction.

    **note** with this setup, parallel reading is not possible"""
    __slots__ = ("_filepath", '_fd', '_write')

    def __init__(self, filepath):
        """Initialize an instance with the givne filepath"""
        self._filepath = filepath
        self._fd = None
        self._write = None          # if True, we write a file

    def __del__(self):
        # will do nothing if the file descriptor is already closed
        if self._fd is not None:
            self.rollback()

    def _lockfilepath(self):
        return "%s.lock" % self._filepath

    def open(self, write=False, stream=False):
        """
        Open the file descriptor for reading or writing, both in binary mode.

        :param write: if True, the file descriptor will be opened for writing. Other
            wise it will be opened read-only.
        :param stream: if True, the file descriptor will be wrapped into a simple stream
            object which supports only reading or writing
        :return: fd to read from or write to. It is still maintained by this instance
            and must not be closed directly
        :raise IOError: if the lock could not be retrieved
        :raise OSError: If the actual file could not be opened for reading

        **note** must only be called once"""
        if self._write is not None:
            raise AssertionError("Called %s multiple times" % self.open)

        self._write = write

        # try to open the lock file
        binary = getattr(os, 'O_BINARY', 0)
        lockmode = os.O_WRONLY | os.O_CREAT | os.O_EXCL | binary
        try:
            fd = os.open(self._lockfilepath(), lockmode, int("600", 8))
            if not write:
                os.close(fd)
            else:
                self._fd = fd
            # END handle file descriptor
        except OSError:
            raise IOError("Lock at %r could not be obtained" % self._lockfilepath())
        # END handle lock retrieval

        # open actual file if required
        if self._fd is None:
            # we could specify exlusive here, as we obtained the lock anyway
            try:
                self._fd = os.open(self._filepath, os.O_RDONLY | binary)
            except:
                # assure we release our lockfile
                os.remove(self._lockfilepath())
                raise
            # END handle lockfile
        # END open descriptor for reading

        if stream:
            # need delayed import
            from gitdb.stream import FDStream
            return FDStream(self._fd)
        else:
            return self._fd
        # END handle stream

    def commit(self):
        """When done writing, call this function to commit your changes into the
        actual file.
        The file descriptor will be closed, and the lockfile handled.

        **Note** can be called multiple times"""
        self._end_writing(successful=True)

    def rollback(self):
        """Abort your operation without any changes. The file descriptor will be
        closed, and the lock released.

        **Note** can be called multiple times"""
        self._end_writing(successful=False)

    def _end_writing(self, successful=True):
        """Handle the lock according to the write mode """
        if self._write is None:
            raise AssertionError("Cannot end operation if it wasn't started yet")

        if self._fd is None:
            return

        os.close(self._fd)
        self._fd = None

        lockfile = self._lockfilepath()
        if self._write and successful:
            # on windows, rename does not silently overwrite the existing one
            if is_win:
                if isfile(self._filepath):
                    os.remove(self._filepath)
                # END remove if exists
            # END win32 special handling
            os.rename(lockfile, self._filepath)

            # assure others can at least read the file - the tmpfile left it at rw--
            # We may also write that file, on windows that boils down to a remove-
            # protection as well
            chmod(self._filepath, int("644", 8))
        else:
            # just delete the file so far, we failed
            os.remove(lockfile)
        # END successful handling

#} END utilities
