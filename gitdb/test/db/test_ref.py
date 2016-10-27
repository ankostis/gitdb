# Copyright (C) 2010, 2011 Sebastian Thiel (byronimo@gmail.com) and contributors
#
# This module is part of GitDB and is released under
# the New BSD License: http://www.opensource.org/licenses/bsd-license.php
import os

from gitdb.const import NULL_BIN_SHA
from gitdb.db import ReferenceDB
from gitdb.test.db.lib import (
    TestDBBase,
    with_rw_directory,
)
import smmap


def make_alt_file(alt_path, alt_list):
    """Create an alternates file which contains the given alternates.
    The list can be empty"""
    with open(alt_path, "wb") as alt_file:
        for alt in alt_list:
            alt_file.write(alt.encode("utf-8") + "\n".encode("ascii"))


class TestReferenceDB(TestDBBase):

    @with_rw_directory
    def test_writing(self, path):
        alt_path = os.path.join(path, 'alternates')
        with smmap.memory_managed() as mman:
            rdb = ReferenceDB(alt_path, mman)
            self.assertEqual(len(rdb.databases()), 0)
            self.assertEqual(rdb.size(), 0)
            self.assertEqual(len(list(rdb.sha_iter())), 0)

            # try empty, non-existing
            assert not rdb.has_object(NULL_BIN_SHA)

            # setup alternate file
            # add two, one is invalid
            own_repo_path = os.path.join(self.gitrepopath, 'objects')       # use own repo
            make_alt_file(alt_path, [own_repo_path, "invalid/path"])
            rdb.update_cache()
            self.assertEqual(len(rdb.databases()), 1)

            # we should now find a default revision of ours
            gitdb_sha = next(rdb.sha_iter())
            assert rdb.has_object(gitdb_sha)

            # remove valid
            make_alt_file(alt_path, ["just/one/invalid/path"])
            rdb.update_cache()
            self.assertEqual(len(rdb.databases()), 0)

            # add valid
            make_alt_file(alt_path, [own_repo_path])
            rdb.update_cache()
            self.assertEqual(len(rdb.databases()), 1)
