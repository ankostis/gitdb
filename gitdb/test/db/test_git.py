# Copyright (C) 2010, 2011 Sebastian Thiel (byronimo@gmail.com) and contributors
#
# This module is part of GitDB and is released under
# the New BSD License: http://www.opensource.org/licenses/bsd-license.php
import os

import smmap

from gitdb.base import OStream, OInfo
from gitdb.db import GitDB
from gitdb.exc import BadObject
from gitdb.test.db.lib import (
    TestDBBase,
    with_rw_directory
)
from gitdb.util import bin_to_hex


class TestGitDB(TestDBBase):

    def test_reading(self):
        with smmap.managed_mmaps() as mman:
            gdb = GitDB(mman, os.path.join(self.gitrepopath, 'objects'))

            # we have packs and loose objects, alternates doesn't necessarily exist
            assert 1 < len(gdb.databases()) < 4

            # access should be possible
            gitdb_sha = next(gdb.sha_iter())
            assert isinstance(gdb.info(gitdb_sha), OInfo)
#            with gdb.stream(gitdb_sha) as stream:
#                assert isinstance(stream, OStream)
#            ni = 50
#            assert gdb.size() >= ni
#            sha_list = list(gdb.sha_iter())
#            assert len(sha_list) == gdb.size()
#            sha_list = sha_list[:ni]  # speed up tests ...
#
#            # This is actually a test for compound functionality, but it doesn't
#            # have a separate test module
#            # test partial shas
#            # this one as uneven and quite short
#            gitdb_sha_hex = bin_to_hex(gitdb_sha)
#            assert gdb.partial_to_complete_sha_hex(gitdb_sha_hex[:5]) == gitdb_sha
#
#            # mix even/uneven hexshas
#            for i, binsha in enumerate(sha_list):
#                assert gdb.partial_to_complete_sha_hex(bin_to_hex(binsha)[:8 - (i % 2)]) == binsha
#            # END for each sha
#
#            self.failUnlessRaises(BadObject, gdb.partial_to_complete_sha_hex, "0000")

    @with_rw_directory
    def test_writing(self, path):
        with smmap.managed_mmaps() as mman:
            gdb = GitDB(mman, path)

            # its possible to write objects
            self._assert_object_writing(gdb)
