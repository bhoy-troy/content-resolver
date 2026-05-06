"""DNF4 to DNF5 Adapter Layer

This module provides a compatibility shim that allows DNF4-style code to work
with DNF5 (libdnf5) without modifications. It wraps the DNF5 API to provide
the same interface as DNF4.

Key API Differences Addressed:
------------------------------

1. Module Structure:
   DNF4: import dnf; dnf.Base()
   DNF5: from libdnf5.base import Base; Base()

2. Configuration:
   DNF4: base.conf.debuglevel = 0
   DNF5: base.get_config().debuglevel = 0

3. Substitutions (variables like releasever):
   DNF4: base.conf.substitutions['releasever'] = 'rawhide'
   DNF5: base.get_vars().set('releasever', 'rawhide')

4. Repository Creation:
   DNF4: repo = dnf.repo.Repo(name, parent_conf); base.repos.add(repo)
   DNF5: repo = base.get_repo_sack().create_repo(name)

5. Repository Attributes:
   DNF4: repo.baseurl = 'http://...'
   DNF5: repo.get_config().baseurl = 'http://...'

6. Repository Iteration:
   DNF4: for repo in base.repos.all(): ...
   DNF5: No direct iteration - must track repos manually

Usage:
------
    from content_resolver.dnf import _DNFAdapter

    dnf = _DNFAdapter()

    # DNF4-style code now works with DNF5
    with dnf.Base() as base:
        base.conf.debuglevel = 0
        base.conf.substitutions['releasever'] = 'rawhide'

        repo = dnf.repo.Repo('myrepo', base.conf)
        repo.baseurl = 'http://example.com/repo'
        base.repos.add(repo)

        for r in base.repos.all():
            print(r.get_id())

See Also:
---------
- https://dnf5.readthedocs.io/ - Official DNF5 documentation
"""

import libdnf5
from libdnf5.base import Base
from libdnf5.repo import Repo

from content_resolver.exceptions import (
    DepsolveError,
    DownloadError,
    MarkingError,
    TransactionCheckError,
)


class _DNF5Substitutions:
    """Dict-like wrapper around DNF5 Vars for DNF4 compatibility.

    DNF4 used base.conf.substitutions as a dict-like object for template
    variables like 'releasever', 'arch', etc. DNF5 uses base.get_vars()
    with set() and get_value() methods instead.

    This class provides a dict-like interface that translates to DNF5's
    vars API, allowing DNF4 code like:
        base.conf.substitutions['releasever'] = 'rawhide'

    to work transparently with DNF5.

    Attributes:
        _base: The DNF5 Base object
        _vars: The DNF5 VarsWeakPtr object from base.get_vars()
    """

    def __init__(self, base):
        """Initialize the substitutions dict wrapper.

        Args:
            base: A libdnf5.base.Base object
        """
        self._base = base
        self._vars = base.get_vars()

    def __setitem__(self, key, value):
        """Set a substitution variable.

        Args:
            key: Variable name (e.g., 'releasever')
            value: Variable value (e.g., 'rawhide')

        Example:
            substitutions['releasever'] = 'rawhide'
        """
        self._vars.set(key, value)

    def __getitem__(self, key):
        """Get a substitution variable.

        Args:
            key: Variable name

        Returns:
            The variable value

        Raises:
            Exception: If variable doesn't exist

        Example:
            version = substitutions['releasever']
        """
        return self._vars.get_value(key)

    def get(self, key, default=None):
        """Get a substitution variable with a default fallback.

        Args:
            key: Variable name
            default: Value to return if variable doesn't exist

        Returns:
            The variable value or default if not found

        Example:
            version = substitutions.get('releasever', 'rawhide')
        """
        try:
            return self._vars.get_value(key)
        except Exception:
            return default


class _DNF5ConfigAdapter:
    """Wrapper around DNF5 ConfigMain that adds DNF4-compatible substitutions.

    DNF4's base.conf object had a 'substitutions' attribute for template
    variables. DNF5's config object doesn't have this - variables are accessed
    via base.get_vars() instead.

    This wrapper adds a 'substitutions' attribute to the config object while
    forwarding all other attributes to the underlying DNF5 ConfigMain object.

    Attributes:
        _config: The underlying DNF5 ConfigMain object
        _base: The DNF5 Base object (needed for vars access)
        _base_wrapper: The _DNF5BaseAdapter that owns this config
        substitutions: Dict-like object for variable access (DNF4 compatibility)
    """

    def __init__(self, config, base, base_wrapper):
        """Initialize the config adapter.

        Args:
            config: A libdnf5 ConfigMain object from base.get_config()
            base: The libdnf5.base.Base object
            base_wrapper: The _DNF5BaseAdapter instance that created this config
        """
        self._config = config
        self._base = base
        self._base_wrapper = base_wrapper
        self.substitutions = _DNF5Substitutions(base)

    def __getattr__(self, name):
        """Forward attribute access to the underlying DNF5 config.

        This allows code like base.conf.debuglevel to work by forwarding
        to the real config object.

        Args:
            name: Attribute name

        Returns:
            The attribute value from the underlying config
        """
        return getattr(self._config, name)

    def __setattr__(self, name, value):
        """Forward attribute setting to underlying config.

        Internal wrapper attributes (_config, _base, substitutions) are
        stored on this object. All other attributes are forwarded to
        the underlying DNF5 config.

        Args:
            name: Attribute name
            value: Attribute value
        """
        if name in ("_config", "_base", "_base_wrapper", "substitutions"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._config, name, value)


class _DNF5RepoWrapper:
    """Wrapper around DNF5 Repo to provide DNF4-compatible attribute access.

    DNF4 allowed setting repository configuration directly on the repo object:
        repo.baseurl = 'http://...'
        repo.priority = 100

    DNF5 requires accessing repo configuration via repo.get_config():
        repo.get_config().baseurl = 'http://...'
        repo.get_config().priority = 100

    This wrapper intercepts attribute access and automatically routes
    configuration attributes (baseurl, priority, exclude) to the repo's
    config object, while forwarding other attributes to the repo itself.

    Attributes:
        _repo: The underlying DNF5 Repo object
        _config: The repo's ConfigRepo object from repo.get_config()
    """

    def __init__(self, dnf5_repo):
        """Initialize the repo wrapper.

        Args:
            dnf5_repo: A libdnf5.repo.Repo object (or RepoWeakPtr)
        """
        self._repo = dnf5_repo
        self._config = dnf5_repo.get_config()

        # DNF5: Enable the repo by default
        # In DNF4, repos were enabled by default
        # In DNF5, repos must be explicitly enabled
        self._config.enabled = True

    def __setattr__(self, name, value):
        """Intercept attribute setting and route to config when appropriate.

        Configuration attributes (baseurl, priority, exclude) are set on
        the repo's config object. Other attributes are set on the repo itself.

        Args:
            name: Attribute name
            value: Attribute value

        Example:
            repo.baseurl = 'http://example.com'  # → repo.get_config().baseurl
            repo.priority = 100                   # → repo.get_config().priority
        """
        if name in ("_repo", "_config"):
            # Internal wrapper attributes
            object.__setattr__(self, name, value)
        elif name in ("baseurl", "priority", "exclude"):
            # DNF4: repo.baseurl = value
            # DNF5: repo.get_config().baseurl = value
            setattr(self._config, name, value)
        else:
            # Other attributes go to the repo object itself
            setattr(self._repo, name, value)

    def __getattr__(self, name):
        """Forward attribute access to the underlying repo.

        Args:
            name: Attribute name

        Returns:
            The attribute value from the underlying repo

        Example:
            repo_id = repo.get_id()  # Forwarded to DNF5 repo
        """
        return getattr(self._repo, name)


class _DNF5RepoAdapter:
    """Wrapper around libdnf5 RepoSack that provides DNF4-compatible methods.

    DNF4's base.repos provided methods like all(), iter_enabled(), and add()
    for working with repositories. DNF5's RepoSack has a different API:

    - DNF4: base.repos.add(repo) - explicitly add a repo to the sack
    - DNF5: repo_sack.create_repo(name) - creates AND adds in one step

    - DNF4: for repo in base.repos.all() - iterate all repos
    - DNF5: No direct iteration method provided

    This wrapper tracks repos created via our Repo factory and provides
    DNF4-compatible iteration methods.

    Attributes:
        _repo_sack: The underlying DNF5 RepoSackWeakPtr object
        _base: The DNF5 Base object
        _created_repos: List of repos created via our wrapper (for iteration)
    """

    def __init__(self, repo_sack, base):
        """Initialize the repo sack adapter.

        Args:
            repo_sack: A libdnf5 RepoSackWeakPtr from base.get_repo_sack()
            base: The libdnf5.base.Base object
        """
        self._repo_sack = repo_sack
        self._base = base
        # Track created repos since DNF5 doesn't provide easy iteration
        self._created_repos = []

    def _register_repo(self, repo):
        """Track a created repo for iteration support.

        Internal method called by the Repo factory when creating repos.

        Args:
            repo: A _DNF5RepoWrapper instance to track
        """
        if repo not in self._created_repos:
            self._created_repos.append(repo)

    def iter_enabled(self):
        """Iterate over enabled repositories (DNF4 compatibility).

        In DNF4, this returned an iterator over enabled repos. In DNF5,
        we track all created repos and return an iterator over them.

        Returns:
            Iterator over _DNF5RepoWrapper objects

        Example:
            for repo in base.repos.iter_enabled():
                print(repo.get_id())
        """
        return iter(self._created_repos)

    def all(self):
        """Get all repositories (DNF4 compatibility).

        In DNF4, base.repos.all() returned a list of all repos. In DNF5,
        we return the list of repos we've tracked.

        Returns:
            List of _DNF5RepoWrapper objects

        Example:
            for repo in base.repos.all():
                repo.module_hotfixes = True
        """
        return self._created_repos

    def add(self, repo):
        """Add a repository to the sack (DNF4 compatibility).

        In DNF4, repos were created first, then added:
            repo = dnf.repo.Repo(name, config)
            base.repos.add(repo)

        In DNF5, create_repo() both creates and adds the repo in one step,
        so by the time add() is called, the repo is already in the sack.
        We just need to register it for iteration support.

        Args:
            repo: A _DNF5RepoWrapper instance (already added to sack)

        Example:
            repo = dnf.repo.Repo('myrepo', base.conf)
            base.repos.add(repo)  # No-op in DNF5, just tracks for iteration
        """
        if isinstance(repo, _DNF5RepoWrapper):
            self._register_repo(repo)

    def __getattr__(self, name):
        """Forward other attributes to the underlying repo sack.

        This allows direct access to DNF5 RepoSack methods not wrapped here.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying RepoSack

        Example:
            base.repos.create_repo('name')  # Forwarded to DNF5
        """
        return getattr(self._repo_sack, name)


class _DNF5BaseAdapter:
    """Wrapper around libdnf5.base.Base providing DNF4-compatible interface.

    This is the main wrapper that coordinates all DNF4 compatibility. It wraps
    a DNF5 Base object and provides DNF4-style access to configuration and
    repositories.

    Key compatibility features:
    - base.conf: Returns wrapped config with substitutions support
    - base.repos: Returns wrapped repo sack with iteration support
    - Context manager support (with statement)
    - Forwards all other attributes to underlying DNF5 Base

    Attributes:
        _base: The underlying libdnf5.base.Base object
        _conf_proxy: Cached _DNF5ConfigAdapter instance
        _repos_proxy: Cached _DNF5RepoAdapter instance

    Example:
        with dnf.Base() as base:
            base.conf.debuglevel = 0
            base.conf.substitutions['releasever'] = 'rawhide'
            repo = dnf.repo.Repo('myrepo', base.conf)
            base.repos.add(repo)
            base.fill_sack()
    """

    def __init__(self):
        """Initialize the Base adapter.

        Creates a new DNF5 Base object and initializes wrapper proxies
        for config and repos access.
        """
        self._base = Base()
        # Lazy-initialized proxies (created on first access)
        self._conf_proxy = None
        self._repos_proxy = None

    @property
    def conf(self):
        """Get the configuration object with DNF4-compatible interface.

        Returns a wrapped config that provides:
        - Direct attribute access: base.conf.debuglevel = 0
        - Substitutions support: base.conf.substitutions['releasever']

        Returns:
            _DNF5ConfigAdapter: Wrapped config with substitutions

        Example:
            base.conf.debuglevel = 0
            base.conf.cachedir = '/tmp/cache'
            base.conf.substitutions['releasever'] = 'rawhide'
        """
        if self._conf_proxy is None:
            raw_config = self._base.get_config()
            self._conf_proxy = _DNF5ConfigAdapter(raw_config, self._base, self)
        return self._conf_proxy

    @property
    def repos(self):
        """Get the repository sack with DNF4-compatible interface.

        Returns a wrapped repo sack that provides:
        - all() method: Get list of all repos
        - iter_enabled() method: Iterate over repos
        - add() method: Add a repo (no-op, for compatibility)

        Returns:
            _DNF5RepoAdapter: Wrapped repo sack with iteration support

        Example:
            for repo in base.repos.all():
                print(repo.get_id())
        """
        if self._repos_proxy is None:
            self._repos_proxy = _DNF5RepoAdapter(self._base.get_repo_sack(), self._base)
        return self._repos_proxy

    def __enter__(self):
        """Context manager entry (for 'with' statements).

        Returns:
            self: This adapter instance

        Example:
            with dnf.Base() as base:
                base.conf.debuglevel = 0
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup if needed.

        Args:
            exc_type: Exception type (if raised)
            exc_val: Exception value (if raised)
            exc_tb: Exception traceback (if raised)

        Returns:
            False: Don't suppress exceptions
        """
        # DNF5 cleanup if needed
        return False

    def fill_sack(self, load_system_repo=True, load_available_repos=True):
        """Load repository metadata and fill the package sack (DNF4 compatibility).

        DNF4: base.fill_sack(load_system_repo=False)
        DNF5: base.get_repo_sack().update_and_load_enabled_repos()

        This method loads repository metadata and creates the package sack
        for querying packages.

        Args:
            load_system_repo: Whether to load the system repo (default True)
                             Note: In DNF5, system repo is handled differently
            load_available_repos: Whether to load available repos (default True)

        Example:
            base.fill_sack(load_system_repo=False)
        """
        # DNF5 uses update_and_load_enabled_repos() to load repo metadata
        repo_sack = self._base.get_repo_sack()
        repo_sack.update_and_load_enabled_repos()

        # After loading repos, we can access the package sack
        # DNF5 automatically creates the sack when repos are loaded

    @property
    def sack(self):
        """Get the package sack for querying packages (DNF4 compatibility).

        DNF4: base.sack
        DNF5: base.get_rpm_package_sack()

        Returns:
            The RPM package sack

        Example:
            query = base.sack.query
        """
        return self._base.get_rpm_package_sack()

    def __getattr__(self, name):
        """Forward other attributes to the underlying DNF5 Base object.

        This allows direct access to DNF5 Base methods not wrapped here,
        such as fill_sack(), read_all_repos(), etc.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying Base object

        Example:
            base.fill_sack(load_system_repo=False)  # Forwarded to DNF5
        """
        return getattr(self._base, name)


class _DNFAdapter:
    """Main compatibility adapter - mimics DNF4 module structure.

    This class provides the top-level interface that mimics the old 'dnf'
    module structure, allowing code like:

        import dnf
        with dnf.Base() as base:
            repo = dnf.repo.Repo(name, config)

    to work with DNF5 under the hood.

    Components:
        - Base(): Factory method returning wrapped DNF5 Base
        - repo.Repo(): Factory method for creating wrapped repos
        - exceptions: Namespace for DNF exception types

    Usage:
        from content_resolver.dnf import _DNFAdapter
        dnf = _DNFAdapter()

        # Now use DNF4-style code
        with dnf.Base() as base:
            repo = dnf.repo.Repo('myrepo', base.conf)
            base.repos.add(repo)

    See module docstring for complete API differences documentation.
    """

    @staticmethod
    def Base():
        """Create a new DNF Base object with DNF4-compatible interface.

        Returns:
            _DNF5BaseAdapter: Wrapped DNF5 Base object

        Example:
            base = dnf.Base()
            # or with context manager:
            with dnf.Base() as base:
                base.conf.debuglevel = 0
        """
        return _DNF5BaseAdapter()

    class repo:
        """Repository factory - mimics dnf.repo namespace."""

        @staticmethod
        def Repo(name, parent_conf):
            """Create a repository with DNF4-compatible signature.

            DNF4 signature: Repo(name, parent_conf)
            - name: Repository ID string
            - parent_conf: Config object from base.conf

            DNF5 equivalent: repo_sack.create_repo(name)
            - Takes base object and name
            - Creates AND adds repo in one step

            This factory method bridges the difference by:
            1. Extracting base from the wrapped config
            2. Using DNF5's create_repo() to create the repo
            3. Wrapping it for DNF4-compatible attribute access
            4. Registering it for iteration support

            Args:
                name: Repository ID string
                parent_conf: Config object (must be from dnf.Base().conf)

            Returns:
                _DNF5RepoWrapper: Wrapped repo with DNF4-compatible interface

            Raises:
                ValueError: If parent_conf is not from a wrapped Base

            Example:
                repo = dnf.repo.Repo('myrepo', base.conf)
                repo.baseurl = 'http://example.com/repo'
                repo.priority = 100
                base.repos.add(repo)
            """
            # Extract base from wrapped config
            if isinstance(parent_conf, _DNF5ConfigAdapter):
                base_wrapper = parent_conf._base_wrapper
                base = base_wrapper._base
            else:
                # This shouldn't happen if using our dnf.Base()
                raise ValueError(
                    "DNF5 requires Base object for Repo creation, but got raw config. "
                    "Make sure you're using dnf.Base() from content_resolver.dnf"
                )

            # DNF5: create_repo() both creates and adds the repo
            repo_sack = base.get_repo_sack()
            dnf5_repo = repo_sack.create_repo(name)

            # Wrap for DNF4-compatible attribute access
            wrapped_repo = _DNF5RepoWrapper(dnf5_repo)

            # Register with repos adapter for iteration support
            base_wrapper.repos._register_repo(wrapped_repo)

            return wrapped_repo

    class exceptions:
        """DNF exception types - mapped to DNF5 equivalents.

        DNF4 had a rich exception hierarchy in dnf.exceptions. DNF5 has
        a different exception structure in libdnf5.common.

        This namespace provides compatibility mappings. Where DNF5 doesn't
        have a direct equivalent, we map to base Exception class. Error
        handling should check for these exception types to maintain
        DNF4 code compatibility.

        Attributes:
            Error: Base DNF error (mapped to Exception)
            RepoError: Repository errors (mapped to libdnf5.common.RepoError if available)
            MarkingError: Package marking errors (mapped to Exception - no DNF5 equivalent)
            DepsolveError: Dependency resolution errors (mapped to Exception)
            DownloadError: Download errors (mapped to Exception)
            TransactionCheckError: Transaction errors (mapped to Exception)

        Note:
            These are fallback mappings. DNF5 may raise different exception
            types that should be caught and handled appropriately. The mappings
            ensure DNF4-style exception handling doesn't break, but new code
            should consider DNF5's exception model.

        Example:
            try:
                base.fill_sack()
            except dnf.exceptions.RepoError as e:
                log(f"Repo error: {e}")
        """

        # Generic base error
        Error = Exception

        # Repository errors - use DNF5 version if available
        RepoError = libdnf5.common.RepoError if hasattr(libdnf5.common, "RepoError") else Exception

        # Package marking errors - no direct DNF5 equivalent
        MarkingError = MarkingError

        # Dependency resolution errors - handled differently in DNF5
        DepsolveError = DepsolveError

        # Download errors - handled differently in DNF5
        DownloadError = DownloadError

        # Transaction check errors - handled differently in DNF5
        TransactionCheckError = TransactionCheckError
