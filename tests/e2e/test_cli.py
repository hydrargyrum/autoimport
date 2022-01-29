"""Test the command line interface."""

import os
import re
from pathlib import Path
from textwrap import dedent
from typing import Dict, List, Optional

import pytest
from click.testing import CliRunner
from py._path.local import LocalPath

from autoimport.entrypoints.cli import cli
from autoimport.version import __version__


@pytest.fixture(name="runner")
def fixture_runner() -> CliRunner:
    """Configure the Click cli test runner."""
    return CliRunner(mix_stderr=False, env={"XDG_CONFIG_HOME": "/dev/null"})


def test_version(runner: CliRunner) -> None:
    """Prints program version when called with --version."""
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert re.match(
        rf" *autoimport version: {__version__}\n"
        r" *python version: .*\n *platform: .*",
        result.stdout,
    )


def test_corrects_one_file(runner: CliRunner, tmpdir: LocalPath) -> None:
    """Correct the source code of a file."""
    test_file = tmpdir / "source.py"
    test_file.write("os.getcwd()")
    fixed_source = dedent(
        """\
        import os

        os.getcwd()"""
    )

    result = runner.invoke(cli, [str(test_file)])

    assert result.exit_code == 0
    assert test_file.read() == fixed_source


@pytest.mark.secondary()
def test_corrects_three_files(runner: CliRunner, tmpdir: LocalPath) -> None:
    """Correct the source code of multiple files."""
    test_files = []
    for file_number in range(3):
        test_file = tmpdir / f"source_{file_number}.py"
        test_file.write("os.getcwd()")
        test_files.append(test_file)
    fixed_source = dedent(
        """\
        import os

        os.getcwd()"""
    )

    result = runner.invoke(cli, [str(test_file) for test_file in test_files])

    assert result.exit_code == 0
    for test_file in test_files:
        assert test_file.read() == fixed_source


def test_correct_all_files_in_dir_recursively(
    runner: CliRunner, test_dir: Path
) -> None:
    """Ensure files and dirs can be parsed and fixes associated files."""
    result = runner.invoke(cli, [str(test_dir)])

    assert result.exit_code == 0
    fixed_source = "import os\n\nos.getcwd()"
    assert (test_dir / "test_file1.py").read_text() == fixed_source
    assert (test_dir / "subdir/test_file2.py").read_text() == fixed_source


def test_correct_mix_dir_and_files(
    runner: CliRunner, test_dir: Path, tmpdir: LocalPath
) -> None:
    """Ensure all files in a given directory get fixed by autoimport."""
    test_file = tmpdir / "source.py"
    test_file.write("os.getcwd()")

    result = runner.invoke(cli, [str(test_dir), str(test_file)])

    assert result.exit_code == 0
    fixed_source = "import os\n\nos.getcwd()"
    assert (test_dir / "test_file1.py").read_text() == fixed_source
    assert (test_dir / "subdir/test_file2.py").read_text() == fixed_source
    assert test_file.read() == fixed_source


def test_corrects_code_from_stdin(runner: CliRunner) -> None:
    """Correct the source code passed as stdin."""
    source = "os.getcwd()"
    fixed_source = dedent(
        """\
        import os

        os.getcwd()"""
    )

    result = runner.invoke(cli, ["-"], input=source)

    assert result.exit_code == 0
    assert result.stdout == fixed_source


PYPROJECT_CONFIG = """
[tool.autoimport]
common_statements = { "FooBar" = "from baz.qux import FooBar" }
"""
PYPROJECT_CONFIG_TEST_SOURCE = "FooBar\n"
PYPROJECT_CONFIG_FIXED_SOURCE = """\
from baz.qux import FooBar

FooBar
"""


def test_pyproject_common_statements(runner: CliRunner, tmpdir: LocalPath) -> None:
    """Allow common_statements to be defined in pyproject.toml"""
    pyproject_toml = tmpdir / "pyproject.toml"
    pyproject_toml.write(PYPROJECT_CONFIG)
    test_file = tmpdir / "source.py"
    test_file.write(PYPROJECT_CONFIG_TEST_SOURCE)
    with tmpdir.as_cwd():

        result = runner.invoke(cli, [str(test_file)])

    assert result.exit_code == 0
    assert test_file.read() == PYPROJECT_CONFIG_FIXED_SOURCE


@pytest.mark.parametrize(
    ("create_global_conf", "use_local_conf", "create_pyproject", "expected_imports"),
    [
        pytest.param(True, False, False, "from g import G", id="global"),
        pytest.param(False, True, False, "from l import L", id="local"),
        pytest.param(False, False, True, "from p import P", id="pyproject"),
        pytest.param(
            True, True, False, "from g import G\nfrom l import L", id="global-and-local"
        ),
        pytest.param(
            True,
            False,
            True,
            "from g import G\nfrom p import P",
            id="global-and-pyproject",
        ),
        pytest.param(False, True, True, "from l import L", id="local-and-pyproject"),
        pytest.param(
            True,
            True,
            True,
            "from g import G\nfrom l import L",
            id="global-and-local-and-pyproject",
        ),
    ],
)
def test_global_and_local_config(
    runner: CliRunner,
    tmpdir: LocalPath,
    create_global_conf: bool,
    use_local_conf: bool,
    create_pyproject: bool,
    expected_imports: str,
) -> None:
    """
    Test interaction between the following:
      - presence of the global config file $XDG_CONFIG_HOME/autoimport/config.toml
      - use of the --config-file flag to specify a local config file
      - presence of a pyproject.toml file
    """
    conf_global = '[common_statements]\n"G" = "from g import G"'
    conf_local = '[common_statements]\n"L" = "from l import L"'
    conf_pyproject = '[tool.autoimport.common_statements]\n"P" = "from p import P"'
    code_path = tmpdir / "code.py"
    original_code = dedent(
        """
    G
    L
    P
    """
    )
    code_path.write(original_code)
    args: List[str] = [str(code_path)]
    env: Dict[str, Optional[str]] = {}
    if create_global_conf:
        xdg_home = tmpdir / "xdg_home"
        env["XDG_CONFIG_HOME"] = str(Path(xdg_home).resolve())  # must be absolute path
        global_conf_path = xdg_home / "autoimport" / "config.toml"
        global_conf_path.ensure()
        global_conf_path.write(conf_global)
    if use_local_conf:
        local_conf_path = tmpdir / "cfg" / "local.toml"
        local_conf_path.ensure()
        local_conf_path.write(conf_local)
        args.extend(["--config-file", str(local_conf_path)])
    if create_pyproject:
        pyproject_path = tmpdir / "pyproject.toml"
        pyproject_path.write(conf_pyproject)
    with tmpdir.as_cwd():

        result = runner.invoke(cli, args, env=env)

    assert result.exit_code == 0
    assert code_path.read() == expected_imports + "\n" + original_code


def test_config_path_argument(runner: CliRunner, tmpdir: LocalPath) -> None:
    """Allow common_statements to be defined in pyproject.toml"""
    cfg_dir = tmpdir / "cfg"
    cfg_dir.mkdir()
    pyproject_toml = cfg_dir / "pyproject.toml"
    pyproject_toml.write(PYPROJECT_CONFIG)
    code_dir = tmpdir / "code"
    code_dir.mkdir()
    test_file = code_dir / "source.py"
    test_file.write(PYPROJECT_CONFIG_TEST_SOURCE)

    result = runner.invoke(cli, ["--config-file", str(pyproject_toml), str(test_file)])

    assert result.exit_code == 0
    assert test_file.read() == PYPROJECT_CONFIG_FIXED_SOURCE


def test_fix_files_doesnt_touch_the_file_if_its_not_going_to_change_it(
    runner: CliRunner, tmpdir: LocalPath
) -> None:
    """
    Given: A file that doesn't need any change
    When: fix files is run
    Then: The file is untouched
    """
    test_file = tmpdir / "source.py"
    test_file.write("a = 1")
    modified_time = os.path.getmtime(test_file)

    result = runner.invoke(cli, [str(test_file)])

    assert result.exit_code == 0
    assert os.path.getmtime(test_file) == modified_time
