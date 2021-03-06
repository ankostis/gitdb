# Copyright (C) 2010, 2011 Sebastian Thiel (byronimo@gmail.com) and contributors
#
# This module is part of GitDB and is released under
# the New BSD License: http://www.opensource.org/licenses/bsd-license.php
"""Module containing a database to deal with packs"""
from gitdb.db.base import (
    FileDBBase,
    ObjectDBR,
    CachingDB
)

from gitdb.util import LazyMixin

from gitdb.exc import (
    BadObject,
    UnsupportedOperation,
    AmbiguousObjectName
)

from gitdb.pack import PackEntity
from gitdb.utils.compat import xrange

import os
import glob

__all__ = ('PackedDB',)

#{ Utilities


class PackedDB(FileDBBase, ObjectDBR, CachingDB, LazyMixin):

    """A database operating on a set of object packs"""

    # sort the priority list every N queries
    # Higher values are better, performance tests don't show this has
    # any effect, but it should have one
    _sort_interval = 500

    def __init__(self, mman, root_path):
        super(PackedDB, self).__init__(root_path)
        # list of lists with three items:
        # * hits - number of times the pack was hit with a request
        # * entity - Pack entity instance
        # * sha_to_index - PackIndexFile.sha_to_index method for direct cache query
        # self._entities = []       # lazy loaded list
        self._mman = mman
        self._hit_count = 0             # amount of hits
        self._st_mtime = 0              # last modification data of our root path

    def _set_cache_(self, attr):
        if attr == '_entities':
            self._entities = []
            self.update_cache(force=True)
        # END handle entities initialization

    def _sort_entities(self):
        self._entities.sort(key=lambda l: l[0], reverse=True)

    def _pack_info(self, sha):
        """:return: tuple(entity, index) for an item at the given sha
        :param sha: 20 or 40 byte sha
        :raise BadObject:
        **Note:** This method is not thread-safe, but may be hit in multi-threaded
            operation. The worst thing that can happen though is a counter that
            was not incremented, or the list being in wrong order. So we safe
            the time for locking here, lets see how that goes"""
        # presort ?
        if self._hit_count % self._sort_interval == 0:
            self._sort_entities()
        # END update sorting

        for item in self._entities:
            ent = item[1]
            with ent.index() as index:
                index = index.sha_to_index(sha)
            if index is not None:
                item[0] += 1            # one hit for you
                self._hit_count += 1    # general hit count
                return (item[1], index)
            # END index found in pack
        # END for each item

        # no hit, see whether we have to update packs
        # NOTE: considering packs don't change very often, we safe this call
        # and leave it to the super-caller to trigger that
        raise BadObject(sha)

    #{ Object DB Read

    def has_object(self, sha):
        try:
            self._pack_info(sha)
            return True
        except BadObject:
            return False
        # END exception handling

    def info(self, sha):
        entity, index = self._pack_info(sha)
        with entity:
            return entity.info_at_index(index)

    def stream(self, sha):
        entity, index = self._pack_info(sha)
        with entity:
            return entity.stream_at_index(index)

    def sha_iter(self):
        for entity in self.entities():
            with entity.index() as index:
                sha_by_index = index.sha
                for index in xrange(index.size()):
                    yield sha_by_index(index)

    def size(self):
        sz = 0
        for entity in self.entities():
            with entity.index() as idx:
                sz += idx.size()
        return sz

    #} END object db read

    #{ object db write

    def store(self, istream):
        """Storing individual objects is not feasible as a pack is designed to
        hold multiple objects. Writing or rewriting packs for single objects is
        inefficient"""
        raise UnsupportedOperation()

    #} END object db write

    #{ Interface

    def update_cache(self, force=False):
        """
        Update our cache with the acutally existing packs on disk. Add new ones,
        and remove deleted ones. We keep the unchanged ones

        :param force: If True, the cache will be updated even though the directory
            does not appear to have changed according to its modification timestamp.
        :return: True if the packs have been updated so there is new information,
            False if there was no change to the pack database"""
        stat = os.stat(self.root_path())
        if not force and stat.st_mtime <= self._st_mtime:
            return False
        # END abort early on no change
        self._st_mtime = stat.st_mtime

        # packs are supposed to be prefixed with pack- by git-convention
        # get all pack files, figure out what changed
        pack_files = set(glob.glob(os.path.join(self.root_path(), "pack-*.pack")))
        our_pack_files = set(item[1].pack().path() for item in self._entities)

        # new packs
        for pack_file in (pack_files - our_pack_files):
            # init the hit-counter/priority with the size, a good measure for hit-
            # probability. Its implemented so that only 12 bytes will be read
            with PackEntity(self._mman, pack_file) as entity:
                self._entities.append([entity.pack().size(), entity, entity.index().sha_to_index])
        # END for each new packfile

        # removed packs
        for pack_file in (our_pack_files - pack_files):
            del_index = -1
            for i, item in enumerate(self._entities):
                if item[1].pack().path() == pack_file:
                    del_index = i
                    break
                # END found index
            # END for each entity
            assert del_index != -1
            del(self._entities[del_index])
        # END for each removed pack

        # reinitialize prioritiess
        self._sort_entities()
        return True

    def entities(self):
        """:return: list of pack entities operated upon by this database"""
        return [item[1] for item in self._entities]

    def partial_to_complete_sha(self, partial_binsha, canonical_length):
        """:return: 20 byte sha as inferred by the given partial binary sha
        :param partial_binsha: binary sha with less than 20 bytes
        :param canonical_length: length of the corresponding canonical representation.
            It is required as binary sha's cannot display whether the original hex sha
            had an odd or even number of characters
        :raise AmbiguousObjectName:
        :raise BadObject: """
        candidate = None
        for item in self._entities:
            with item[1] as entity:
                item_index = entity.index().partial_sha_to_index(partial_binsha, canonical_length)
                if item_index is not None:
                    sha = entity.index().sha(item_index)
                    if candidate and candidate != sha:
                        raise AmbiguousObjectName(partial_binsha)
                    candidate = sha
            # END handle full sha could be found
        # END for each entity

        if candidate:
            return candidate

        # still not found ?
        raise BadObject(partial_binsha)

    #} END interface
