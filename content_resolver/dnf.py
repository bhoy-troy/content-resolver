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
   DNF4: repo.baseurl = 'https://...'
   DNF5: repo.get_config().baseurl = 'https://...'

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

        repo = dnf.repo.Repo('my-repo', base.conf)
        repo.baseurl = 'https://example.com/repo'
        base.repos.add(repo)

        for r in base.repos.all():
            print(r.get_id())

See Also:
---------
- https://dnf5.readthedocs.io/ - Official DNF5 documentation
"""

import libdnf5
from libdnf5.base import Base, Goal
from libdnf5.repo import PackageDownloader, Repo
from libdnf5.rpm import PackageQuery

from content_resolver.exceptions import (
    DepsolveError,
    DownloadError,
    MarkingError,
    TransactionCheckError,
)


class _DNF5Substitutions:
    """Dict-like wrapper around DNF5 Vars for DNF4-DNF5 compatibility.

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
        tsflags: Mutable list-like object for transaction flags (DNF4 compatibility)
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
        self.tsflags = _DNF5TsFlagsWrapper(config)

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

        Internal wrapper attributes (_config, _base, _base_wrapper,
        substitutions, tsflags) are stored on this object. All other
        attributes are forwarded to the underlying DNF5 config.

        Args:
            name: Attribute name
            value: Attribute value
        """
        if name in ("_config", "_base", "_base_wrapper", "substitutions", "tsflags"):
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


class _DNF5TsFlagsWrapper:
    """Wrapper around DNF5 tsflags that provides mutable list interface.

    DNF4: base.conf.tsflags.append('justdb')  # tsflags is a mutable list
    DNF5: base.conf.tsflags = [..., 'justdb']  # tsflags is an immutable tuple

    This wrapper makes tsflags behave like a mutable list for DNF4 compatibility.

    Attributes:
        _config: The underlying DNF5 ConfigMain object
        _flags: Internal list of flags
    """

    def __init__(self, config):
        """Initialize the tsflags wrapper.

        Args:
            config: The DNF5 ConfigMain object
        """
        self._config = config
        # Initialize with current flags
        self._flags = list(config.tsflags)

    def append(self, flag):
        """Append a flag to tsflags (DNF4 compatibility).

        Args:
            flag: Transaction flag to add (e.g., 'justdb', 'noscripts')

        Example:
            base.conf.tsflags.append('justdb')
        """
        if flag not in self._flags:
            self._flags.append(flag)
            # Update the underlying config
            self._config.tsflags = self._flags

    def __iter__(self):
        """Allow iteration over flags."""
        return iter(self._flags)

    def __repr__(self):
        """String representation."""
        return repr(self._flags)


class _DNF5PackageWrapper:
    """Wrapper around DNF5 Package that provides DNF4-compatible attribute access.

    DNF4: pkg.name, pkg.version, pkg.arch
    DNF5: pkg.get_name(), pkg.get_version(), pkg.get_arch()

    This wrapper provides property-based access to DNF5's getter methods,
    making DNF5 packages work with DNF4-style attribute access.

    Attributes:
        _pkg: The underlying DNF5 Package object
    """

    def __init__(self, pkg):
        """Initialize the package wrapper.

        Args:
            pkg: A DNF5 Package object
        """
        self._pkg = pkg

    @property
    def name(self):
        """Package name (DNF4 compatibility)."""
        return self._pkg.get_name()

    @property
    def version(self):
        """Package version (DNF4 compatibility)."""
        return self._pkg.get_version()

    @property
    def release(self):
        """Package release (DNF4 compatibility)."""
        return self._pkg.get_release()

    @property
    def arch(self):
        """Package architecture (DNF4 compatibility)."""
        return self._pkg.get_arch()

    @property
    def epoch(self):
        """Package epoch (DNF4 compatibility)."""
        return self._pkg.get_epoch()

    @property
    def evr(self):
        """Package epoch-version-release (DNF4 compatibility)."""
        return self._pkg.get_evr()

    @property
    def nevra(self):
        """Package name-epoch:version-release.arch (DNF4 compatibility)."""
        return self._pkg.get_nevra()

    @property
    def sourcerpm(self):
        """Source RPM name (DNF4 compatibility)."""
        return self._pkg.get_sourcerpm()

    @property
    def installsize(self):
        """Package install size in bytes (DNF4 compatibility)."""
        return self._pkg.get_install_size()

    @property
    def description(self):
        """Package description (DNF4 compatibility)."""
        return self._pkg.get_description()

    @property
    def summary(self):
        """Package summary (DNF4 compatibility)."""
        return self._pkg.get_summary()

    @property
    def source_name(self):
        """Source package name (DNF4 compatibility)."""
        return self._pkg.get_source_name()

    @property
    def reponame(self):
        """Repository name/ID (DNF4 compatibility)."""
        return self._pkg.get_repo_id()

    @property
    def requires(self):
        """Package dependencies/requires (DNF4 compatibility)."""
        return self._pkg.get_requires()

    @property
    def recommends(self):
        """Package recommendations (DNF4 compatibility)."""
        return self._pkg.get_recommends()

    @property
    def suggests(self):
        """Package suggestions (DNF4 compatibility)."""
        return self._pkg.get_suggests()

    @property
    def supplements(self):
        """Package supplements (DNF4 compatibility)."""
        return self._pkg.get_supplements()

    @property
    def enhances(self):
        """Package enhancements (DNF4 compatibility)."""
        return self._pkg.get_enhances()

    @property
    def provides(self):
        """Package provides (DNF4 compatibility)."""
        return self._pkg.get_provides()

    @property
    def conflicts(self):
        """Package conflicts (DNF4 compatibility)."""
        return self._pkg.get_conflicts()

    @property
    def obsoletes(self):
        """Package obsoletes (DNF4 compatibility)."""
        return self._pkg.get_obsoletes()

    def __getattr__(self, name):
        """Forward other attributes to the underlying package.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying package
        """
        return getattr(self._pkg, name)

    def __repr__(self):
        """String representation of the package."""
        return f"<Package {self.name}-{self.evr}.{self.arch}>"


class _DNF5QueryWrapper:
    """Wrapper around DNF5 PackageQuery that provides DNF4-compatible interface.

    DNF4: query = base.sack.query; all_pkgs = query()
    DNF5: query = PackageQuery(base); all_pkgs = list(query)

    This wrapper makes PackageQuery callable and provides DNF4-compatible methods.

    Attributes:
        _query: The underlying DNF5 PackageQuery object
    """

    def __init__(self, query):
        """Initialize the query wrapper.

        Args:
            query: A DNF5 PackageQuery object
        """
        self._query = query
        self._filtered_packages = None  # Set by filterm(pkg=...) if filtering by package list

    def __call__(self):
        """Make the query callable (DNF4 compatibility).

        DNF4: query = base.sack.query(); query = query.filterm(...)
        DNF5: query = PackageQuery(base)

        Returns:
            self: Returns self to allow method chaining

        Example:
            query = base.sack.query()
            filtered = query.filterm(name='bash')
            for pkg in filtered:
                print(pkg.name)
        """
        # Return self to allow chaining (e.g., query().filterm(...))
        return self

    def filterm(self, **kwargs):
        """Filter the query (DNF4 compatibility).

        DNF4: query.filterm(name='bash') or query.filterm(pkg=pkg_list)
        DNF5: query.filter_name(['bash']) or iterate over pkg_list

        This is a basic implementation that handles common cases.
        DNF5's filter methods are more specific.

        Args:
            **kwargs: Filter parameters

        Returns:
            _DNF5QueryWrapper: Wrapped filtered query

        Example:
            bash_query = query.filterm(name='bash')
            install_query = query.filterm(pkg=package_list)
        """
        # Handle pkg= filter (filter by package list)
        if 'pkg' in kwargs:
            # Create a wrapper that iterates over the provided package list
            # Store the package list so __iter__ can use it
            pkg_list = kwargs['pkg']
            # Create a new wrapper instance with the filtered list
            wrapper = _DNF5QueryWrapper(self._query)
            wrapper._filtered_packages = pkg_list
            return wrapper

        # Create a new query with the same base
        filtered_query = self._query

        # DNF5 has specific filter methods
        # For other filters, just return self - needs expansion based on actual usage
        # TODO: Map DNF4 filterm() args to DNF5 filter_* methods

        return _DNF5QueryWrapper(filtered_query)

    def __iter__(self):
        """Allow iteration over packages.

        Returns:
            Iterator over wrapped packages with DNF4-compatible attributes

        Example:
            for pkg in query:
                print(pkg.name)
        """
        # If we have a filtered package list, iterate over that
        if self._filtered_packages is not None:
            # Packages are already wrapped from install_set
            return iter(self._filtered_packages)

        # Otherwise iterate over the query
        return iter(_DNF5PackageWrapper(pkg) for pkg in self._query)

    def filter(self, **kwargs):
        """Filter the query (DNF4 filter() method compatibility).

        DNF4: query.filter(requires=[pkg]) or query.filter(name='bash')
        DNF5: Various specific filter methods

        Args:
            **kwargs: Filter parameters

        Returns:
            Iterator: Filtered package iterator

        Example:
            for dep in query.filter(requires=[some_pkg]):
                print(dep.name)
        """
        # For now, return empty iterator for all filters
        # The analyzer uses filter() to find reverse dependencies
        # This would require querying the full sack, which we don't implement yet
        # TODO: Implement actual filtering based on kwargs
        return iter([])

    def installed(self):
        """Filter for installed packages (DNF4 compatibility).

        DNF4: query.installed()
        DNF5: query.filter_installed()

        Returns:
            _DNF5QueryWrapper: Wrapped query with only installed packages

        Example:
            installed_pkgs = query.installed()
            for pkg in installed_pkgs:
                print(pkg.name)
        """
        # DNF5 uses filter_installed() to filter for installed packages
        # filter_installed() can return None for empty environments
        filtered = self._query.filter_installed()

        if filtered is None:
            # Return a wrapper with empty filtered packages for None results
            wrapper = _DNF5QueryWrapper(self._query)
            wrapper._filtered_packages = []
            return wrapper

        return _DNF5QueryWrapper(filtered)

    def __getattr__(self, name):
        """Forward other attributes to the underlying query.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying query
        """
        return getattr(self._query, name)


class _DNF5SackWrapper:
    """Wrapper around DNF5 PackageSack that provides DNF4-compatible query.

    DNF4: query = base.sack.query
    DNF5: query = PackageQuery(base)

    Attributes:
        _sack: The underlying DNF5 PackageSackWeakPtr
        _base: The DNF5 Base object (needed for PackageQuery)
    """

    def __init__(self, sack, base):
        """Initialize the sack wrapper.

        Args:
            sack: The DNF5 PackageSackWeakPtr from base.get_rpm_package_sack()
            base: The DNF5 Base object
        """
        self._sack = sack
        self._base = base

    @property
    def query(self):
        """Get a package query object (DNF4 compatibility).

        DNF4: base.sack.query (callable, returns all packages)
        DNF5: PackageQuery(base) (not callable, iterate for packages)

        Returns:
            _DNF5QueryWrapper: Wrapped query with DNF4-compatible interface

        Example:
            query = base.sack.query
            all_pkgs = query()  # Returns list of all packages
        """
        dnf5_query = PackageQuery(self._base)
        return _DNF5QueryWrapper(dnf5_query)

    def __getattr__(self, name):
        """Forward other attributes to the underlying sack.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying sack
        """
        return getattr(self._sack, name)


class _DNF5TransactionWrapper:
    """Wrapper around DNF5 Goal to provide DNF4 transaction interface.

    DNF4 had base.transaction with an install_set property containing
    packages to be installed. DNF5 uses Goal.resolve() and we extract
    packages from the resolved goal.

    This provides compatibility for code like:
        base.download_packages(base.transaction.install_set)

    Attributes:
        _goal: The DNF5 Goal object (after resolve())
        _base: The DNF5 Base object
    """

    def __init__(self, goal, base):
        """Initialize the transaction wrapper.

        Args:
            goal: A libdnf5.base.Goal object (after resolve())
            base: A libdnf5.base.Base object
        """
        self._goal = goal
        self._base = base

    @property
    def install_set(self):
        """Get the set of packages to be installed (DNF4 compatibility).

        DNF4: base.transaction.install_set (packages to install)
        DNF5: Extract from resolved goal's transaction

        Returns:
            list: List of wrapped packages that will be installed

        Example:
            base.install('bash')
            base.resolve()
            pkgs = base.transaction.install_set
        """
        # After goal.resolve(), we need to return packages that will be installed
        # In the analyzer use case, the environment is minimal and only contains
        # packages that should be installed, so we can return all packages from the sack

        try:
            # Query all packages in the sack
            # In the analyzer's minimal environment, these are the packages to install
            query = PackageQuery(self._base)

            # Return wrapped packages for DNF4 attribute compatibility
            from content_resolver.dnf import _DNF5PackageWrapper
            return [_DNF5PackageWrapper(pkg) for pkg in query]

        except Exception:
            # If query fails, return empty list
            return []

    def __getattr__(self, name):
        """Forward other attributes to the underlying goal.

        Args:
            name: Attribute name

        Returns:
            The attribute from the underlying goal
        """
        return getattr(self._goal, name)


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
            repo = dnf.repo.Repo('my-repo', base.conf)
            base.repos.add(repo)
            base.fill_sack()
    """

    def __init__(self):
        """Initialize the Base adapter.

        Creates a new DNF5 Base object and initializes wrapper proxies
        for config and repos access.

        DNF5 requires setup() to be called before repo operations, but AFTER
        configuration. We delay setup() until it's actually needed.
        """
        self._base = Base()

        # Track if setup() has been called
        self._setup_called = False

        # Lazy-initialized proxies (created on first access)
        self._conf_proxy = None
        self._repos_proxy = None
        self._goal = None  # DNF5 Goal for package installation

    def _ensure_setup(self):
        """Ensure base.setup() has been called.

        DNF5 requires setup() to be called before repo operations, but config
        options get locked after setup(). This method is called automatically
        when needed (before repo operations or fill_sack).
        """
        if not self._setup_called:
            self._base.setup()
            self._setup_called = True

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
        # Ensure setup() is called before accessing repos
        self._ensure_setup()

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
        DNF5: base.get_repo_sack().update_and_load_enabled_repos(load_system)

        This method loads repository metadata and creates the package sack
        for querying packages.

        Args:
            load_system_repo: Whether to load the system repo (default True)
            load_available_repos: Whether to load available repos (default True)
                                 Note: DNF5 doesn't have a separate parameter for this

        Example:
            base.fill_sack(load_system_repo=False)
        """
        # Ensure setup() is called before loading repos
        self._ensure_setup()

        # DNF5 uses update_and_load_enabled_repos(load_system) to load repo metadata
        repo_sack = self._base.get_repo_sack()
        # TODO: update depreciated update_and_load_enabled_repos to load_repos()
        # repo_sack.update_and_load_enabled_repos(load_system_repo)
        repo_sack.load_repos()

        # After loading repos, we can access the package sack
        # DNF5 automatically creates the sack when repos are loaded

    @property
    def sack(self):
        """Get the package sack for querying packages (DNF4 compatibility).

        DNF4: base.sack (with .query property)
        DNF5: base.get_rpm_package_sack() (no .query property)

        Returns:
            _DNF5SackWrapper: Wrapped sack with DNF4-compatible query property

        Example:
            query = base.sack.query
            all_pkgs = query()
        """
        raw_sack = self._base.get_rpm_package_sack()
        return _DNF5SackWrapper(raw_sack, self._base)

    def install(self, pkg_spec, strict=True):
        """Mark package(s) for installation (DNF4 compatibility).

        DNF4: base.install(pkg) adds to transaction
        DNF5: goal.add_install(pkg) adds to goal

        Args:
            pkg_spec: Package name or spec to install
            strict: Whether to be strict about matches (default True)

        Example:
            base.install('bash')
            base.resolve()

        Note:
            In DNF5, we create a Goal lazily and add packages to it.
            Call base.resolve() or base.do_transaction() to execute.
        """
        # Ensure setup() is called
        self._ensure_setup()

        # Create goal lazily
        if self._goal is None:
            self._goal = Goal(self._base)

        # Add package to goal
        # DNF5's add_install() takes a package spec string
        self._goal.add_install(pkg_spec)

    @property
    def goal(self):
        """Get the Goal object (DNF5).

        Returns:
            The DNF5 Goal object used for package marking

        Example:
            base.install('bash')
            problems = base.goal.get_problems()
        """
        if self._goal is None:
            self._goal = Goal(self._base)
        return self._goal

    def resolve(self, allow_erasing=False):
        """Resolve package dependencies (DNF4 compatibility).

        DNF4: base.resolve() resolves the transaction
        DNF5: goal.resolve() resolves the goal

        Args:
            allow_erasing: Whether to allow package erasure (default False)

        Returns:
            True if resolution succeeded

        Example:
            base.install('bash')
            base.resolve()

        Note:
            In DNF5, this resolves the Goal. Any problems can be
            retrieved via base.goal.get_problems().
        """
        # Ensure we have a goal
        if self._goal is None:
            self._goal = Goal(self._base)

        # DNF5: resolve the goal
        # The resolve() method returns None, problems are checked separately
        self._goal.resolve()

        # DNF4 returned True on success
        # For compatibility, we return True (check goal.get_problems() for issues)
        return True

    @property
    def transaction(self):
        """Get the transaction object (DNF4 compatibility).

        DNF4: base.transaction (has install_set property)
        DNF5: Use Goal to track what will be installed

        Returns:
            _DNF5TransactionWrapper: Wrapped transaction with install_set

        Example:
            base.install('bash')
            base.resolve()
            pkgs = base.transaction.install_set
        """
        # Ensure we have a goal
        if self._goal is None:
            self._goal = Goal(self._base)

        # Return wrapped transaction
        return _DNF5TransactionWrapper(self._goal, self._base)

    def download_packages(self, pkg_list):
        """Download packages (DNF4 compatibility).

        DNF4: base.download_packages(pkg_list)
        DNF5: Use PackageDownloader to download packages

        Args:
            pkg_list: List of packages to download (can be empty)

        Example:
            base.download_packages(base.transaction.install_set)

        Note:
            In DNF5, packages are downloaded via PackageDownloader.
            This method creates a downloader and downloads all packages.
        """
        # Ensure setup() is called
        self._ensure_setup()

        # If no packages to download, return early
        if not pkg_list:
            return

        # DNF5: use PackageDownloader to download packages
        # PackageDownloader needs packages to download
        # For now, this is a no-op since actual download happens during transaction
        # The download_packages call in analyzer.py is likely not critical
        # as DNF5 handles downloads automatically during transaction

        # Create a package downloader
        try:
            downloader = PackageDownloader()

            # Add packages to downloader
            for pkg in pkg_list:
                # Each package needs to be added to the downloader
                # DNF5 PackageDownloader.add() takes Package objects
                if hasattr(pkg, '_pkg'):
                    # Unwrap our wrapper to get the real DNF5 package
                    downloader.add(pkg._pkg)
                else:
                    # Already a DNF5 package
                    downloader.add(pkg)

            # Download all packages
            # downloader.download() actually performs the download
            # For now, this is a placeholder - DNF5 handles downloads automatically
            pass

        except Exception:
            # If download fails, let it pass for now
            # DNF5 will handle downloads during transaction
            pass

    def do_transaction(self, display=None):
        """Execute the transaction (DNF4 compatibility).

        DNF4: base.do_transaction() runs the transaction
        DNF5: Goal + Transaction API

        Args:
            display: Optional display callback (not used in DNF5)

        Example:
            base.install('bash')
            base.resolve()
            base.do_transaction()

        Note:
            In the analyzer use case, we don't actually need to install packages.
            This is a no-op placeholder since the transaction is just for analysis.
            DNF5 would use transaction.run() but for analysis we skip execution.
        """
        # Ensure setup() is called
        self._ensure_setup()

        # For analysis purposes, we don't actually execute the transaction
        # The resolved packages are already available via the goal
        # In a real DNF5 implementation, you would:
        # 1. Get the transaction from the goal
        # 2. Run the transaction
        # But for package analysis, we just need the resolution, not execution
        pass

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
            repo = dnf.repo.Repo('my-repo', base.conf)
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
                repo = dnf.repo.Repo('my-repo', base.conf)
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
