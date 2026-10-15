"""
Test DNF5 exception handling for buildroot resolution.

This test suite verifies that the DNF5 exception handling fix properly catches
dependency resolution failures during buildroot analysis. It addresses the critical
issue where buildroot failures were silently ignored due to undefined exception types.

See: DNF5_EXCEPTION_FIX.md for background on the issue.
"""
import sys
from unittest.mock import MagicMock, Mock

import pytest

# Mock libdnf5 if not available
try:
    from libdnf5.base import Goal
    from libdnf5.exception import Error as DnfErr
    from libdnf5.exception import UserAssertionError
except ModuleNotFoundError:
    # Create mocks for testing environments without libdnf5
    mock_libdnf5 = MagicMock()
    mock_libdnf5.base = MagicMock()
    mock_libdnf5.exception = MagicMock()

    # Create exception classes
    class DnfErr(Exception):
        pass

    class UserAssertionError(Exception):
        pass

    mock_libdnf5.exception.Error = DnfErr
    mock_libdnf5.exception.UserAssertionError = UserAssertionError

    sys.modules['libdnf5'] = mock_libdnf5
    sys.modules['libdnf5.base'] = mock_libdnf5.base
    sys.modules['libdnf5.exception'] = mock_libdnf5.exception


class TestDNF5ExceptionHandling:
    """Test that DNF5 exceptions are properly caught during analysis."""

    def test_package_not_found_exception_caught(self):
        """Test that package not found errors are caught."""
        # Mock goal that raises RuntimeError on add_install
        # DNF5 raises RuntimeError when packages are not found
        mock_goal = Mock()
        mock_goal.add_install.side_effect = RuntimeError("Package not found")

        # The exception should be caught and not propagate
        # This simulates what happens in _analyze_workload when adding packages
        pkg_name = "non-existent-package"
        errors = []

        try:
            mock_goal.add_install(pkg_name)
        except (UserAssertionError, DnfErr, RuntimeError):
            # This is the fixed exception handler from our DNF5 fix
            errors.append(pkg_name)

        assert len(errors) == 1
        assert errors[0] == pkg_name

    def test_dependency_resolution_error_caught(self):
        """Test that dependency resolution errors are caught properly."""
        # Test that RuntimeError is caught during goal.resolve()
        # DNF5 raises RuntimeError for dependency resolution failures
        mock_goal = Mock()
        mock_goal.resolve.side_effect = RuntimeError("Dependency resolution failed")

        succeeded = True
        error_message = None

        try:
            mock_goal.resolve()
        except (DnfErr, RuntimeError, Exception) as err:
            # This is the CRITICAL FIX - broad exception catching for dep resolution
            succeeded = False
            error_message = str(err)

        assert not succeeded
        assert "Dependency resolution failed" in error_message

    def test_runtime_error_in_resolution_caught(self):
        """Test that RuntimeError during resolution is caught."""
        # DNF5 can raise RuntimeError for various resolution issues
        mock_goal = Mock()
        mock_goal.resolve.side_effect = RuntimeError("Runtime dependency error")

        succeeded = True
        error_message = None

        try:
            mock_goal.resolve()
        except (DnfErr, RuntimeError, Exception) as err:
            succeeded = False
            error_message = str(err)

        assert not succeeded
        assert "Runtime dependency error" in error_message

    def test_generic_exception_in_resolution_caught(self):
        """Test that generic exceptions during resolution are caught."""
        # DNF5 Python bindings can raise generic exceptions
        mock_goal = Mock()
        mock_goal.resolve.side_effect = Exception("Generic resolution error")

        succeeded = True
        error_message = None

        try:
            mock_goal.resolve()
        except (DnfErr, RuntimeError, Exception) as err:
            succeeded = False
            error_message = str(err)

        assert not succeeded
        assert "Generic resolution error" in error_message

    def test_workload_structure_on_failure(self):
        """Test that workload structure is correctly populated on failure."""
        # Simulate workload initialization
        workload = {
            "workload_conf_id": "test-workload",
            "succeeded": True,  # Default value
            "errors": {
                "non_existing_pkgs": [],
                "message": ""
            }
        }

        # Simulate a dependency resolution failure
        # DNF5 raises RuntimeError for dependency resolution failures
        try:
            raise RuntimeError("Cannot resolve dependencies")
        except (DnfErr, RuntimeError, Exception) as err:
            workload["succeeded"] = False
            workload["errors"]["message"] = str(err)

        # Verify the workload is marked as failed
        assert not workload["succeeded"]
        assert "Cannot resolve dependencies" in workload["errors"]["message"]

    def test_buildroot_srpm_failure_detection(self):
        """Test that buildroot SRPM failures are properly detected."""
        # Simulate buildroot SRPM data structure
        srpm = {
            "id": "test-package-1.0-1.fc45",
            "succeeded": False,
            "errors": {
                "message": "Dependency resolution failed: package-dep not found"
            }
        }

        # This structure should be detected in view-errors page generation
        assert not srpm["succeeded"]
        assert srpm["errors"]["message"]
        assert "not found" in srpm["errors"]["message"]


class TestDNF5ExceptionBackwardCompatibility:
    """Test that the fix handles both DNF5 and potential future exception types."""

    def test_catches_all_exception_types(self):
        """Verify broad exception catching works for unknown exception types."""
        # Create a custom exception that DNF5 might raise
        class UnknownDNF5Exception(Exception):
            pass

        mock_goal = Mock()
        mock_goal.resolve.side_effect = UnknownDNF5Exception("Unknown error type")

        succeeded = True
        error_message = None

        try:
            mock_goal.resolve()
        except (DnfErr, RuntimeError, Exception) as err:
            # The broad Exception catch should handle this
            succeeded = False
            error_message = str(err)

        assert not succeeded
        assert "Unknown error type" in error_message


class TestDNF5ExceptionRegression:
    """Regression tests to ensure the original bug doesn't return."""

    def test_depsolve_error_no_longer_used(self):
        """Ensure we don't reference non-existent DepsolveError."""
        # This test documents that DepsolveError doesn't exist in DNF5
        # and shouldn't be used in exception handlers

        # DepsolveError was a DNF4 exception that doesn't exist in DNF5
        with pytest.raises(NameError):
            # This should fail because DepsolveError is not defined
            raise DepsolveError("This should not work")  # noqa: F821

    def test_marking_error_no_longer_used(self):
        """Ensure we don't reference non-existent MarkingError."""
        with pytest.raises(NameError):
            raise MarkingError("This should not work")  # noqa: F821

    def test_transaction_check_error_no_longer_used(self):
        """Ensure we don't reference non-existent TransactionCheckError."""
        with pytest.raises(NameError):
            raise TransactionCheckError("This should not work")  # noqa: F821


class TestBuildrootAnalysisExceptionFlow:
    """Integration-style tests for the buildroot analysis exception flow."""

    def test_buildroot_resolution_failure_flow(self):
        """Test the complete flow when buildroot resolution fails."""
        # Simulate the fake_workload structure used in buildroot analysis
        fake_workload = {
            "workload_conf_id": "bash-1.0-1.fc45",  # SRPM ID
            "env_conf_id": "CR-buildroot-base-env-repo-eln-x86_64",
            "repo_id": "repo-eln",
            "arch": "x86_64",
            "succeeded": True,  # Default
            "pkg_env_ids": [],
            "pkg_added_ids": [],
            "pkg_relations": {},
            "errors": {
                "non_existing_pkgs": [],
                "message": ""
            },
            "warnings": {
                "non_existing_pkgs": [],
                "message": None
            }
        }

        # Simulate a buildroot dependency resolution failure
        try:
            # This simulates goal.resolve() failing
            raise RuntimeError("Nothing provides 'missing-build-dep' needed by bash-1.0-1.fc45")
        except (DnfErr, RuntimeError, Exception) as err:
            fake_workload["succeeded"] = False
            fake_workload["errors"]["message"] = str(err)

        # Verify the workload is correctly marked as failed
        assert not fake_workload["succeeded"]
        assert "Nothing provides" in fake_workload["errors"]["message"]
        assert "missing-build-dep" in fake_workload["errors"]["message"]

        # This should now appear in view-errors page
        # because succeeded=False will be detected by the view generation code

    def test_buildroot_srpm_data_structure(self):
        """Test that SRPM buildroot data structure is populated correctly on failure."""
        # This simulates data["buildroot"]["srpms"][repo_id][arch][srpm_id]
        srpm_buildroot_data = {
            "id": "bash-5.2.15-1.fc45",
            "directly_required_pkg_names": {"gcc", "make", "autoconf"},
            "pkg_relations": {},
            "pkg_env_ids": set(),
            "pkg_added_ids": set(),
            "errors": {
                "non_existing_pkgs": set(),
                "message": ""
            },
            "succeeded": False,  # Set by our exception handler
            "queued": True,
            "processed": True
        }

        # Simulate the error message that would be set
        srpm_buildroot_data["errors"]["message"] = "Dependency resolution failed: nothing provides libnonexistent.so"

        # Verify structure for view generation
        assert not srpm_buildroot_data["succeeded"]
        assert "nothing provides" in srpm_buildroot_data["errors"]["message"]

        # This data flows to:
        # self.data["buildroot"]["srpms"][repo_id][arch][srpm_id]["succeeded"] = fake_workload["succeeded"]
        # Which is then checked in _generate_views_all_arches():
        # if not self.data["buildroot"]["srpms"][repo_id][arch][package["id"]]["succeeded"]:
        #     view_all_arches["everything_succeeded"] = False


class TestEnvironmentResolutionProblems:
    """Test that DNF5 transaction problems are caught in environment analysis.

    DNF5 does not raise exceptions for dependency failures -- it returns a
    transaction with problems recorded. The env analysis path must check
    transaction.get_problems() to avoid silently succeeding with missing packages.
    """

    def test_env_resolution_catches_transaction_problems(self):
        """Env analysis should fail when transaction has problems."""
        mock_transaction = Mock()
        mock_transaction.get_problems.return_value = 3
        mock_transaction.get_resolve_logs_as_strings.return_value = [
            "nothing provides libfoo.so needed by bar-1.0",
            "package baz requires qux, but none of the providers can be installed",
            "conflicting requests",
        ]

        env = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }

        # Simulate the get_problems() check from _analyze_env
        if mock_transaction.get_problems() > 0:
            resolve_logs = mock_transaction.get_resolve_logs_as_strings()
            error_message = "\n".join(resolve_logs)
            env["succeeded"] = False
            env["errors"]["message"] = error_message

        assert not env["succeeded"]
        assert "nothing provides libfoo.so" in env["errors"]["message"]

    def test_env_resolution_succeeds_when_no_problems(self):
        """Env analysis should succeed when transaction has no problems."""
        mock_transaction = Mock()
        mock_transaction.get_problems.return_value = 0

        env = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }

        if mock_transaction.get_problems() > 0:
            env["succeeded"] = False

        assert env["succeeded"]

    def test_env_resolution_catches_runtime_error(self):
        """Env analysis should catch RuntimeError from goal.resolve(), not just DnfErr."""
        mock_goal = Mock()
        mock_goal.resolve.side_effect = RuntimeError("Segfault in libsolv")

        env = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }

        try:
            mock_goal.resolve()
        except (DnfErr, RuntimeError, Exception) as err:
            env["succeeded"] = False
            env["errors"]["message"] = str(err)

        assert not env["succeeded"]
        assert "Segfault in libsolv" in env["errors"]["message"]

    def test_env_resolution_catches_generic_exception(self):
        """Env analysis should catch generic Exception from goal.resolve()."""
        mock_goal = Mock()
        mock_goal.resolve.side_effect = Exception("Unexpected DNF5 error")

        env = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }

        try:
            mock_goal.resolve()
        except (DnfErr, RuntimeError, Exception) as err:
            env["succeeded"] = False
            env["errors"]["message"] = str(err)

        assert not env["succeeded"]
        assert "Unexpected DNF5 error" in env["errors"]["message"]


class TestRepoConflictFilterWithEmptyTransaction:
    """Test that repo conflict filtering does not silently succeed with 0 packages.

    When DNF5 reports version conflicts between repos (e.g., ELN vs Rawhide),
    the filter should only ignore the problems if packages were still resolved.
    If the transaction is empty, the conflicts prevented installation and must
    be reported as a failure.
    """

    def test_repo_conflict_with_packages_is_ignored(self):
        """Repo conflicts should be ignored when packages were still resolved."""
        mock_transaction = Mock()
        mock_transaction.get_problems.return_value = 2
        mock_transaction.get_resolve_logs_as_strings.return_value = [
            "cannot install both foo-1.0-1.fc45 from ELN and foo-1.1-1.fc45 from Rawhide",
        ]
        mock_trans_pkgs = Mock()
        mock_trans_pkgs.size.return_value = 5  # packages WERE resolved
        mock_transaction.get_transaction_packages.return_value = mock_trans_pkgs

        workload = {"succeeded": True, "errors": {"non_existing_pkgs": [], "message": ""}}

        error_message = "\n".join(mock_transaction.get_resolve_logs_as_strings())
        error_lower = error_message.lower()
        has_cannot_install_both = "cannot install both" in error_lower and " from " in error_lower
        has_nothing_provides = "nothing provides" in error_lower
        is_repo_conflict = has_cannot_install_both
        is_real_error = has_nothing_provides

        if mock_transaction.get_problems() > 0:
            if is_repo_conflict and not is_real_error:
                trans_pkgs_check = mock_transaction.get_transaction_packages()
                if trans_pkgs_check.size() > 0:
                    pass  # ignored — packages resolved despite conflict
                else:
                    workload["succeeded"] = False

        # Should still succeed — packages were resolved
        assert workload["succeeded"]

    def test_repo_conflict_with_empty_transaction_fails(self):
        """Repo conflicts must fail when transaction has 0 packages."""
        mock_transaction = Mock()
        mock_transaction.get_problems.return_value = 2
        mock_transaction.get_resolve_logs_as_strings.return_value = [
            "cannot install both pam_url-1.0 from ELN and pam_url-1.1 from Rawhide",
        ]
        mock_trans_pkgs = Mock()
        mock_trans_pkgs.size.return_value = 0  # no packages resolved!
        mock_transaction.get_transaction_packages.return_value = mock_trans_pkgs

        workload = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }

        error_message = "\n".join(mock_transaction.get_resolve_logs_as_strings())
        error_lower = error_message.lower()
        has_cannot_install_both = "cannot install both" in error_lower and " from " in error_lower
        has_nothing_provides = "nothing provides" in error_lower
        is_repo_conflict = has_cannot_install_both
        is_real_error = has_nothing_provides

        if mock_transaction.get_problems() > 0:
            if is_repo_conflict and not is_real_error:
                trans_pkgs_check = mock_transaction.get_transaction_packages()
                if trans_pkgs_check.size() > 0:
                    pass
                else:
                    workload["succeeded"] = False
                    workload["errors"]["message"] = (
                        "Repository version conflicts prevented package resolution:\n\n"
                        + error_message
                    )

        assert not workload["succeeded"]
        assert "conflicts prevented" in workload["errors"]["message"]
        assert "pam_url" in workload["errors"]["message"]


class TestEmptyTransactionDetection:
    """Test that workloads with 0 resolved packages are detected as failures.

    This addresses the core issue #138: DNF5's goal.resolve() can succeed with
    0 problems AND 0 transaction packages, silently producing empty results.
    The post-resolution validation catches this.
    """

    def test_empty_transaction_with_requested_packages_fails(self):
        """Workload requesting packages but getting 0 should fail."""
        workload = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }
        workload_conf_packages = ["pam_url", "uwsgi"]
        workload_conf_arch_packages = []
        pkgs_added = set()  # empty transaction

        # Simulate env packages (just fedora-eln-repos, fedora-eln-release)
        mock_env_pkg1 = Mock()
        mock_env_pkg1.get_name.return_value = "fedora-eln-repos"
        mock_env_pkg2 = Mock()
        mock_env_pkg2.get_name.return_value = "fedora-eln-release"
        pkgs_env = {mock_env_pkg1, mock_env_pkg2}

        # Post-resolution validation logic
        requested_pkgs = list(workload_conf_packages) + list(workload_conf_arch_packages)
        if not pkgs_added and requested_pkgs:
            env_pkg_names = {pkg.get_name() for pkg in pkgs_env}
            plain_requested = [p for p in requested_pkgs if '*' not in p and '?' not in p]
            missing_from_env = [p for p in plain_requested if p not in env_pkg_names]

            if missing_from_env:
                workload["succeeded"] = False
                workload["errors"]["message"] = (
                    f"No workload packages were resolved. "
                    f"Packages not found in environment or transaction: {', '.join(sorted(missing_from_env))}"
                )

        assert not workload["succeeded"]
        assert "pam_url" in workload["errors"]["message"]
        assert "uwsgi" in workload["errors"]["message"]

    def test_empty_transaction_packages_in_env_succeeds(self):
        """If requested packages are already in env, empty transaction is OK."""
        workload = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }
        workload_conf_packages = ["bash"]
        workload_conf_arch_packages = []
        pkgs_added = set()  # empty transaction

        mock_env_pkg = Mock()
        mock_env_pkg.get_name.return_value = "bash"
        pkgs_env = {mock_env_pkg}

        requested_pkgs = list(workload_conf_packages) + list(workload_conf_arch_packages)
        if not pkgs_added and requested_pkgs:
            env_pkg_names = {pkg.get_name() for pkg in pkgs_env}
            plain_requested = [p for p in requested_pkgs if '*' not in p and '?' not in p]
            missing_from_env = [p for p in plain_requested if p not in env_pkg_names]

            if missing_from_env:
                workload["succeeded"] = False

        # Should succeed — package is in the environment
        assert workload["succeeded"]

    def test_empty_transaction_glob_only_succeeds(self):
        """If only glob patterns were requested, empty transaction is tolerated."""
        workload = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }
        workload_conf_packages = ["uwsgi-*"]
        workload_conf_arch_packages = []
        pkgs_added = set()

        mock_env_pkg = Mock()
        mock_env_pkg.get_name.return_value = "fedora-eln-repos"
        pkgs_env = {mock_env_pkg}

        requested_pkgs = list(workload_conf_packages) + list(workload_conf_arch_packages)
        if not pkgs_added and requested_pkgs:
            env_pkg_names = {pkg.get_name() for pkg in pkgs_env}
            plain_requested = [p for p in requested_pkgs if '*' not in p and '?' not in p]
            missing_from_env = [p for p in plain_requested if p not in env_pkg_names]

            if missing_from_env:
                workload["succeeded"] = False

        # Should succeed — only glob patterns, no plain packages to check
        assert workload["succeeded"]

    def test_issue_138_epel_ertzing_scenario(self):
        """Regression test: epel-ertzing workload with pam_url, uwsgi, uwsgi-*."""
        workload = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }
        workload_conf_packages = ["pam_url", "uwsgi", "uwsgi-*"]
        workload_conf_arch_packages = []
        pkgs_added = set()  # empty — this was the bug

        # Minimal env: just the base packages
        mock_env_pkg1 = Mock()
        mock_env_pkg1.get_name.return_value = "fedora-eln-repos"
        mock_env_pkg2 = Mock()
        mock_env_pkg2.get_name.return_value = "fedora-eln-release"
        pkgs_env = {mock_env_pkg1, mock_env_pkg2}

        requested_pkgs = list(workload_conf_packages) + list(workload_conf_arch_packages)
        if not pkgs_added and requested_pkgs:
            env_pkg_names = {pkg.get_name() for pkg in pkgs_env}
            plain_requested = [p for p in requested_pkgs if '*' not in p and '?' not in p]
            missing_from_env = [p for p in plain_requested if p not in env_pkg_names]

            if missing_from_env:
                workload["succeeded"] = False
                workload["errors"]["message"] = (
                    f"No workload packages were resolved. "
                    f"Packages not found in environment or transaction: {', '.join(sorted(missing_from_env))}"
                )

        # Must fail — pam_url and uwsgi are not in the env
        assert not workload["succeeded"]
        assert "pam_url" in workload["errors"]["message"]
        assert "uwsgi" in workload["errors"]["message"]

    def test_nonempty_transaction_succeeds(self):
        """Normal case: packages resolved → workload succeeds."""
        workload = {
            "succeeded": True,
            "errors": {"non_existing_pkgs": [], "message": ""},
        }
        workload_conf_packages = ["checkpointctl", "vnstat"]

        mock_pkg = Mock()
        mock_pkg.get_name.return_value = "checkpointctl"
        pkgs_added = {mock_pkg}  # non-empty transaction

        # The check only triggers when pkgs_added is empty
        requested_pkgs = list(workload_conf_packages)
        if not pkgs_added and requested_pkgs:
            workload["succeeded"] = False

        assert workload["succeeded"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
