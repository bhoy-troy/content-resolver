"""
Test glob pattern expansion for DNF5 package resolution.

DNF5's goal.add_install() parses specs as NEVRA, so glob patterns like
"uwsgi-*" get misinterpreted as name="uwsgi" version="*". These tests
verify that glob expansion correctly resolves patterns into individual
package names before passing them to the goal.

See: https://github.com/fedora-eln/content-resolver/issues/138
"""
import sys
from unittest.mock import MagicMock, Mock, patch, call

import pytest

# Mock libdnf5 if not available
try:
    from libdnf5.base import Base, Goal
    from libdnf5.common import QueryCmp_GLOB
    from libdnf5.rpm import PackageQuery
except ModuleNotFoundError:
    mock_libdnf5 = MagicMock()
    mock_libdnf5.base = MagicMock()
    mock_libdnf5.common = MagicMock()
    mock_libdnf5.rpm = MagicMock()
    mock_libdnf5.exception = MagicMock()

    class DnfErr(Exception):
        pass

    class UserAssertionError(Exception):
        pass

    mock_libdnf5.exception.Error = DnfErr
    mock_libdnf5.exception.UserAssertionError = UserAssertionError

    # Make QueryCmp_GLOB available
    QueryCmp_GLOB = mock_libdnf5.common.QueryCmp_GLOB

    sys.modules['libdnf5'] = mock_libdnf5
    sys.modules['libdnf5.base'] = mock_libdnf5.base
    sys.modules['libdnf5.common'] = mock_libdnf5.common
    sys.modules['libdnf5.rpm'] = mock_libdnf5.rpm
    sys.modules['libdnf5.exception'] = mock_libdnf5.exception
    sys.modules['libdnf5.repo'] = MagicMock()

from content_resolver.analyzer import _is_glob, is_package_resolvable, expand_package_glob


def _make_mock_pkg(name):
    """Create a mock package with a get_name() method."""
    pkg = Mock()
    pkg.get_name.return_value = name
    return pkg


class TestIsGlob:
    """Test the _is_glob helper function."""

    def test_plain_package_name(self):
        assert _is_glob("bash") is False

    def test_hyphenated_name(self):
        assert _is_glob("uwsgi-plugin-python3") is False

    def test_star_wildcard(self):
        assert _is_glob("uwsgi-*") is True

    def test_question_mark_wildcard(self):
        assert _is_glob("uwsgi-plugin-?") is True

    def test_star_in_middle(self):
        assert _is_glob("lib*-devel") is True

    def test_multiple_wildcards(self):
        assert _is_glob("*uwsgi*") is True

    def test_empty_string(self):
        assert _is_glob("") is False

    def test_only_star(self):
        assert _is_glob("*") is True

    def test_version_like_string(self):
        """A version string without glob chars is not a glob."""
        assert _is_glob("python3-3.14") is False


class TestIsPackageResolvable:
    """Test is_package_resolvable with mocked DNF5 objects."""

    def _make_base_and_queries(self, name_results=None, provides_results=None):
        """Set up mock base with PackageQuery that returns specified results."""
        base = Mock()
        queries = []

        def make_query(query_base):
            query = Mock()
            # First query created is for name, second is for provides
            if len(queries) == 0:
                query.empty.return_value = not bool(name_results)
            else:
                query.empty.return_value = not bool(provides_results)
            queries.append(query)
            return query

        return base, make_query, queries

    @patch('content_resolver.analyzer.PackageQuery')
    def test_exact_name_found(self, MockPackageQuery):
        base = Mock()
        query = Mock()
        query.empty.return_value = False
        MockPackageQuery.return_value = query

        assert is_package_resolvable(base, "bash") is True
        query.filter_name.assert_called_once_with(["bash"])

    @patch('content_resolver.analyzer.PackageQuery')
    def test_exact_name_not_found_but_provides(self, MockPackageQuery):
        base = Mock()
        name_query = Mock()
        name_query.empty.return_value = True
        provides_query = Mock()
        provides_query.empty.return_value = False
        MockPackageQuery.side_effect = [name_query, provides_query]

        assert is_package_resolvable(base, "bash") is True
        provides_query.filter_provides.assert_called_once_with(["bash"])

    @patch('content_resolver.analyzer.PackageQuery')
    def test_not_found_anywhere(self, MockPackageQuery):
        base = Mock()
        query = Mock()
        query.empty.return_value = True
        MockPackageQuery.return_value = query

        assert is_package_resolvable(base, "nonexistent") is False

    @patch('content_resolver.analyzer.PackageQuery')
    def test_glob_uses_QueryCmp_GLOB_for_name(self, MockPackageQuery):
        base = Mock()
        query = Mock()
        query.empty.return_value = False
        MockPackageQuery.return_value = query

        assert is_package_resolvable(base, "uwsgi-*") is True
        query.filter_name.assert_called_once_with(["uwsgi-*"], QueryCmp_GLOB)

    @patch('content_resolver.analyzer.PackageQuery')
    def test_glob_uses_QueryCmp_GLOB_for_provides(self, MockPackageQuery):
        base = Mock()
        name_query = Mock()
        name_query.empty.return_value = True
        provides_query = Mock()
        provides_query.empty.return_value = False
        MockPackageQuery.side_effect = [name_query, provides_query]

        assert is_package_resolvable(base, "collectd-*") is True
        provides_query.filter_provides.assert_called_once_with(["collectd-*"], QueryCmp_GLOB)

    @patch('content_resolver.analyzer.PackageQuery')
    def test_new_query_created_for_provides(self, MockPackageQuery):
        """Verify a fresh query is created for provides check (not reusing filtered query)."""
        base = Mock()
        name_query = Mock()
        name_query.empty.return_value = True
        provides_query = Mock()
        provides_query.empty.return_value = True
        MockPackageQuery.side_effect = [name_query, provides_query]

        is_package_resolvable(base, "foo")
        assert MockPackageQuery.call_count == 2


class TestExpandPackageGlob:
    """Test expand_package_glob with mocked DNF5 objects."""

    @patch('content_resolver.analyzer.PackageQuery')
    def test_non_glob_returns_unchanged(self, MockPackageQuery):
        """Non-glob package names should be returned as-is without querying."""
        base = Mock()
        result = expand_package_glob(base, "bash")
        assert result == ["bash"]
        MockPackageQuery.assert_not_called()

    @patch('content_resolver.analyzer.PackageQuery')
    def test_glob_expands_to_matching_names(self, MockPackageQuery):
        base = Mock()
        query = Mock()
        mock_pkgs = [
            _make_mock_pkg("uwsgi"),
            _make_mock_pkg("uwsgi-plugin-python3"),
            _make_mock_pkg("uwsgi-plugin-rack"),
            _make_mock_pkg("uwsgi-plugin-python3"),  # duplicate
        ]
        query.__iter__ = Mock(return_value=iter(mock_pkgs))
        MockPackageQuery.return_value = query

        result = expand_package_glob(base, "uwsgi-*")

        assert result == ["uwsgi", "uwsgi-plugin-python3", "uwsgi-plugin-rack"]
        query.filter_name.assert_called_once_with(["uwsgi-*"], QueryCmp_GLOB)
        query.filter_latest_evr.assert_called_once()

    @patch('content_resolver.analyzer.PackageQuery')
    def test_glob_deduplicates_and_sorts(self, MockPackageQuery):
        base = Mock()
        query = Mock()
        mock_pkgs = [
            _make_mock_pkg("collectd-write_redis"),
            _make_mock_pkg("collectd-apache"),
            _make_mock_pkg("collectd-mysql"),
            _make_mock_pkg("collectd-apache"),  # duplicate
        ]
        query.__iter__ = Mock(return_value=iter(mock_pkgs))
        MockPackageQuery.return_value = query

        result = expand_package_glob(base, "collectd-*")

        assert result == ["collectd-apache", "collectd-mysql", "collectd-write_redis"]

    @patch('content_resolver.analyzer.PackageQuery')
    def test_glob_falls_back_to_provides(self, MockPackageQuery):
        """If name glob finds nothing, try provides glob."""
        base = Mock()
        name_query = Mock()
        name_query.__iter__ = Mock(return_value=iter([]))
        provides_query = Mock()
        provides_query.__iter__ = Mock(return_value=iter([
            _make_mock_pkg("lighttpd-mod_auth"),
            _make_mock_pkg("lighttpd-mod_cgi"),
        ]))
        MockPackageQuery.side_effect = [name_query, provides_query]

        result = expand_package_glob(base, "lighttpd-mod_*")

        assert result == ["lighttpd-mod_auth", "lighttpd-mod_cgi"]
        provides_query.filter_provides.assert_called_once_with(["lighttpd-mod_*"], QueryCmp_GLOB)

    @patch('content_resolver.analyzer.PackageQuery')
    def test_glob_returns_original_if_no_matches(self, MockPackageQuery):
        """If nothing matches the glob, return the original pattern as fallback."""
        base = Mock()
        query = Mock()
        query.__iter__ = Mock(return_value=iter([]))
        MockPackageQuery.return_value = query

        result = expand_package_glob(base, "nonexistent-*")

        assert result == ["nonexistent-*"]

    @patch('content_resolver.analyzer.PackageQuery')
    def test_question_mark_glob(self, MockPackageQuery):
        base = Mock()
        query = Mock()
        mock_pkgs = [
            _make_mock_pkg("libX11"),
            _make_mock_pkg("libX12"),
        ]
        query.__iter__ = Mock(return_value=iter(mock_pkgs))
        MockPackageQuery.return_value = query

        result = expand_package_glob(base, "libX1?")

        assert result == ["libX11", "libX12"]
        query.filter_name.assert_called_once_with(["libX1?"], QueryCmp_GLOB)

    @patch('content_resolver.analyzer.PackageQuery')
    def test_issue_138_epel_ertzing(self, MockPackageQuery):
        """Regression test for issue #138 - epel-ertzing--all workload."""
        base = Mock()
        query = Mock()
        mock_pkgs = [
            _make_mock_pkg("uwsgi-plugin-python3"),
            _make_mock_pkg("uwsgi-plugin-rack"),
            _make_mock_pkg("uwsgi-plugin-common"),
            _make_mock_pkg("uwsgi-plugin-php"),
        ]
        query.__iter__ = Mock(return_value=iter(mock_pkgs))
        MockPackageQuery.return_value = query

        result = expand_package_glob(base, "uwsgi-*")

        assert len(result) == 4
        assert "uwsgi-plugin-python3" in result
        assert "uwsgi-plugin-rack" in result
        # Results should be sorted
        assert result == sorted(result)

    @patch('content_resolver.analyzer.PackageQuery')
    def test_issue_138_epel_jonathanspw(self, MockPackageQuery):
        """Regression test for issue #138 - epel-jonathanspw--all workload."""
        base = Mock()

        def make_query_for_pattern(base_arg):
            query = Mock()
            return query

        # Test collectd-* expansion
        query = Mock()
        mock_pkgs = [
            _make_mock_pkg("collectd-apache"),
            _make_mock_pkg("collectd-mysql"),
            _make_mock_pkg("collectd-write_redis"),
        ]
        query.__iter__ = Mock(return_value=iter(mock_pkgs))
        MockPackageQuery.return_value = query

        result = expand_package_glob(base, "collectd-*")

        assert len(result) == 3
        assert "collectd-apache" in result

    @patch('content_resolver.analyzer.PackageQuery')
    def test_issue_138_epel_limb(self, MockPackageQuery):
        """Regression test for issue #138 - epel-limb--all workload."""
        base = Mock()
        query = Mock()
        mock_pkgs = [
            _make_mock_pkg("lighttpd-mod_auth"),
            _make_mock_pkg("lighttpd-mod_authn_mysql"),
            _make_mock_pkg("lighttpd-mod_cgi"),
        ]
        query.__iter__ = Mock(return_value=iter(mock_pkgs))
        MockPackageQuery.return_value = query

        result = expand_package_glob(base, "lighttpd-mod_*")

        assert len(result) == 3
        assert "lighttpd-mod_cgi" in result


class TestGlobIntegrationWithGoal:
    """Test that glob expansion integrates correctly with goal.add_install()."""

    @patch('content_resolver.analyzer.PackageQuery')
    def test_expanded_packages_added_individually(self, MockPackageQuery):
        """Verify each expanded package gets its own goal.add_install() call."""
        base = Mock()
        goal = Mock()

        # Set up query to return multiple packages for glob
        query = Mock()
        mock_pkgs = [
            _make_mock_pkg("uwsgi-plugin-python3"),
            _make_mock_pkg("uwsgi-plugin-rack"),
        ]
        query.__iter__ = Mock(return_value=iter(mock_pkgs))
        MockPackageQuery.return_value = query

        expanded = expand_package_glob(base, "uwsgi-*")
        for pkg in expanded:
            goal.add_install(pkg)

        assert goal.add_install.call_count == 2
        goal.add_install.assert_any_call("uwsgi-plugin-python3")
        goal.add_install.assert_any_call("uwsgi-plugin-rack")

    @patch('content_resolver.analyzer.PackageQuery')
    def test_non_glob_passed_directly_to_goal(self, MockPackageQuery):
        """Non-glob packages should result in a single goal.add_install() call."""
        base = Mock()
        goal = Mock()

        expanded = expand_package_glob(base, "bash")
        for pkg in expanded:
            goal.add_install(pkg)

        goal.add_install.assert_called_once_with("bash")
        MockPackageQuery.assert_not_called()

    @patch('content_resolver.analyzer.PackageQuery')
    def test_mixed_glob_and_plain_packages(self, MockPackageQuery):
        """Simulate a workload with both plain and glob packages."""
        base = Mock()
        goal = Mock()

        packages = ["pam_url", "uwsgi", "uwsgi-*"]

        query = Mock()
        mock_pkgs = [
            _make_mock_pkg("uwsgi-plugin-python3"),
            _make_mock_pkg("uwsgi-plugin-rack"),
        ]
        query.__iter__ = Mock(return_value=iter(mock_pkgs))
        MockPackageQuery.return_value = query

        for pkg in packages:
            for expanded_pkg in expand_package_glob(base, pkg):
                goal.add_install(expanded_pkg)

        # pam_url + uwsgi + uwsgi-plugin-python3 + uwsgi-plugin-rack = 4 calls
        assert goal.add_install.call_count == 4
        goal.add_install.assert_any_call("pam_url")
        goal.add_install.assert_any_call("uwsgi")
        goal.add_install.assert_any_call("uwsgi-plugin-python3")
        goal.add_install.assert_any_call("uwsgi-plugin-rack")
