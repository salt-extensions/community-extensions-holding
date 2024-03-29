#  Copyright (C) 2014 Floris Bruynooghe <flub@devork.be>

r"""
Use remote Mercurial repository as a Pillar source.

.. versionadded:: 2015.8.0

The module depends on the ``hglib`` python module being available.
This is the same requirement as for hgfs\_ so should not pose any extra
hurdles.

This external Pillar source can be configured in the master config file as such:

.. code-block:: yaml

   ext_pillar:
     - hg: ssh://hg@example.co/user/repo
"""
import copy
import hashlib
import logging
import os

import salt.pillar
import salt.utils.stringutils
from salt.config import DEFAULT_HASH_TYPE

try:
    import hglib
except ImportError:
    hglib = None

log = logging.getLogger(__name__)

__virtualname__ = "hg"


def __virtual__():
    """
    Only load if hglib is available.
    """
    ext_pillar_sources = [x for x in __opts__.get("ext_pillar", [])]
    if not any(["hg" in x for x in ext_pillar_sources]):
        return False
    if not hglib:
        log.error("hglib not present")
        return False
    return __virtualname__


def __init__(__opts__):
    """
    Initialise

    This is called every time a minion calls this external pillar.
    """


def ext_pillar(minion_id, pillar, repo, branch="default", root=None):
    """
    Extract pillar from an hg repository
    """
    with Repo(repo) as repo:
        repo.update(branch)
    envname = "base" if branch == "default" else branch
    if root:
        path = os.path.normpath(os.path.join(repo.working_dir, root))
    else:
        path = repo.working_dir

    opts = copy.deepcopy(__opts__)
    opts["pillar_roots"][envname] = [path]
    pil = salt.pillar.Pillar(opts, __grains__, minion_id, envname)
    return pil.compile_pillar(ext=False)


def update(repo_uri):
    """
    Execute an hg pull on all the repos
    """
    with Repo(repo_uri) as repo:
        repo.pull()


class Repo:
    """
    Deal with remote hg (mercurial) repository for Pillar
    """

    def __init__(self, repo_uri):
        """Initialize a hg repo (or open it if it already exists)"""
        self.repo_uri = repo_uri
        cachedir = os.path.join(__opts__["cachedir"], "hg_pillar")
        hash_type = getattr(hashlib, __opts__.get("hash_type", DEFAULT_HASH_TYPE))
        repo_hash = hash_type(salt.utils.stringutils.to_bytes(repo_uri)).hexdigest()
        self.working_dir = os.path.join(cachedir, repo_hash)
        if not os.path.isdir(self.working_dir):
            self.repo = hglib.clone(repo_uri, self.working_dir)
            self.repo.open()
        else:
            self.repo = hglib.open(self.working_dir)

    def pull(self):
        log.debug("Updating hg repo from hg_pillar module (pull)")
        self.repo.pull()

    def update(self, branch="default"):
        """
        Ensure we are using the latest revision in the hg repository
        """
        log.debug("Updating hg repo from hg_pillar module (pull)")
        self.repo.pull()
        log.debug("Updating hg repo from hg_pillar module (update)")
        self.repo.update(branch, clean=True)

    def close(self):
        """
        Cleanup mercurial command server
        """
        self.repo.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
