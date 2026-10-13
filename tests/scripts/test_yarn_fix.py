"""Tests for scripts.yarn_fix."""

from __future__ import annotations

import json
import subprocess

import pytest

from scripts import yarn_fix
from scripts.yarn_fix import (
    audit_state,
    blocking_key,
    insert_pin,
    major_versions,
    pin_resolution,
)


@pytest.mark.parametrize(
    ("key", "package"),
    [
        ("lodash@npm:^4", "lodash"),
        ("parent/lodash", "lodash"),
        ("parent@1/lodash@npm:^4", "lodash"),
        ("@s/parent/lodash", "lodash"),
        ("@s/parent@^2/lodash@1", "lodash"),
        ("@hapi/content@npm:1", "@hapi/content"),
        ("parent/@hapi/content", "@hapi/content"),
        ("a.b@npm:1", "a.b"),
        ("x/a(b)", "a(b)"),
    ],
)
def test_blocking_key_finds_narrower_entry(key, package):
    assert blocking_key({key: "1.0.0"}, package) == key


@pytest.mark.parametrize(
    ("key", "package"),
    [
        ("lodash@^4/react", "lodash"),
        ("lodash/react", "lodash"),
        ("@s/lodash/react", "lodash"),
        ("@scope/lodash", "lodash"),
        ("@scope/lodash@npm:1", "lodash"),
        ("lodash.merge", "lodash"),
        ("lodashx@1", "lodash"),
        ("@hapi/content", "content"),
        ("@hapi/content/x", "@hapi/content"),
        ("axb@npm:1", "a.b"),
    ],
)
def test_blocking_key_ignores_other_packages(key, package):
    assert blocking_key({key: "1.0.0"}, package) is None


@pytest.mark.parametrize("value", ["4.17.20", "^4.17.0", "npm:4.17.20", "npm:^4.17.0"])
def test_blocking_key_allows_plain_exact_pin(value):
    assert blocking_key({"lodash": value}, "lodash") is None


@pytest.mark.parametrize(
    "value",
    [
        "npm:lodash-fork@1.0.0",
        "patch:lodash@npm%3A4#./p.patch",
        "github:user/lodash",
        "git+https://example.com/lodash.git",
        "file:./vendor/lodash",
        "portal:../lodash",
    ],
)
def test_blocking_key_keeps_deliberate_exact_pin(value):
    assert blocking_key({"lodash": value}, "lodash") == "lodash"


def test_insert_pin_after_nearest_smaller_key():
    resolutions = {"adm-zip": "1", "qs": "1", "minimist": "1", "undici": "1"}
    assert list(insert_pin(resolutions, "ms", "2")) == [
        "adm-zip",
        "qs",
        "minimist",
        "ms",
        "undici",
    ]


def test_insert_pin_first_when_nothing_smaller():
    assert list(insert_pin({"b": "1"}, "a", "2")) == ["a", "b"]


def test_insert_pin_among_scoped_keys():
    resolutions = {"@a/x": "1", "@b/y": "1", "lodash": "1"}
    assert list(insert_pin(resolutions, "@b/z", "2")) == [
        "@a/x",
        "@b/y",
        "@b/z",
        "lodash",
    ]


def test_insert_pin_updates_existing_key_in_place():
    result = insert_pin({"a": "1", "b": "1", "c": "1"}, "b", "2")
    assert list(result) == ["a", "b", "c"]
    assert result["b"] == "2"


def test_pin_resolution_writes_pin_and_keeps_formatting(tmp_path):
    path = tmp_path / "package.json"
    path.write_text(
        '{\n  "name": "café",\n  "resolutions": {\n    "qs": "6.0.0"\n  }\n}\n'
    )

    assert pin_resolution(str(path), "ms", "2.1.3") is None

    assert path.read_text() == (
        '{\n  "name": "café",\n  "resolutions": {\n'
        '    "ms": "2.1.3",\n    "qs": "6.0.0"\n  }\n}\n'
    )


@pytest.mark.parametrize("manifest", ['{"name": "x"}', '{"resolutions": null}'])
def test_pin_resolution_adds_resolutions_when_empty(tmp_path, manifest):
    path = tmp_path / "package.json"
    path.write_text(manifest)

    assert pin_resolution(str(path), "ms", "2.1.3") is None

    assert json.loads(path.read_text())["resolutions"] == {"ms": "2.1.3"}


@pytest.mark.parametrize(
    "manifest",
    [
        '{"resolutions": {"intel@npm:^1.2.0": "patch:intel@x"}}',
        '{"resolutions": []}',
        '{"resolutions": "x"}',
    ],
)
def test_pin_resolution_refuses_without_writing(tmp_path, manifest):
    path = tmp_path / "package.json"
    path.write_text(manifest)

    assert pin_resolution(str(path), "intel", "1.3.0")

    assert path.read_text() == manifest


AUDIT = '{"value":"ms","children":{"ID":1}}\n{"value":"qs","children":{"ID":2}}\n'


@pytest.mark.parametrize(
    ("returncode", "output", "expected"),
    [
        (0, "", "clean"),
        (1, "", "error"),
        (1, AUDIT, "flagged"),
        (1, '{"value":"other"}\n', "clean"),
        (1, "\n", "error"),
        (1, "not json", "error"),
        (1, '{"type":"error","displayName":"YN0001","data":"Request failed"}', "error"),
    ],
)
def test_audit_state(returncode, output, expected):
    assert audit_state(returncode, output, "ms") == expected


def test_major_versions():
    output = (
        '{"value":"a@workspace:.","children":{"ms@npm:2.1.2":{},"ms@npm:2.0.0":{}}}\n'
        '{"value":"b@npm:1.0.0","children":{"ms@npm:3.0.0":{}}}\n'
    )
    assert major_versions(output) == {"2", "3"}
    assert major_versions("") == set()


def test_fix_skips_without_yarn_lock(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert yarn_fix.fix("ms", "2.1.3") is False


def test_main_writes_output(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("BUMP_PACKAGE", "ms")
    yarn_fix.main()
    assert output.read_text() == "fixed=false\n"


def _fake_run(monkeypatch, audits, why="", install_rc=0, diff_rc=1):
    audits = iter(audits)

    def run(*cmd, capture=False, quiet=False):
        if cmd[:2] == ("yarn", "--version"):
            return subprocess.CompletedProcess(cmd, 0, "4.5.0\n")
        if cmd[:3] == ("yarn", "npm", "audit"):
            return subprocess.CompletedProcess(cmd, *next(audits))
        if cmd[:2] == ("yarn", "why") and "--json" in cmd:
            return subprocess.CompletedProcess(cmd, 0, why)
        if cmd[:2] == ("yarn", "install"):
            return subprocess.CompletedProcess(cmd, install_rc)
        if cmd[:2] == ("git", "diff"):
            return subprocess.CompletedProcess(cmd, diff_rc)
        return subprocess.CompletedProcess(cmd, 0, "")

    monkeypatch.setattr(yarn_fix, "_run", run)


@pytest.fixture
def yarn_repo(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "yarn.lock").write_text("")
    (tmp_path / "package.json").write_text('{"resolutions": {"qs": "6.0.0"}}')
    return tmp_path


ONE_MAJOR = '{"value":"a@workspace:.","children":{"ms@npm:2.1.2":{}}}\n'
TWO_MAJORS = (
    '{"value":"a@workspace:.","children":{"ms@npm:2.1.2":{},"ms@npm:3.0.0":{}}}\n'
)


def test_fix_in_range_bump(monkeypatch, yarn_repo):
    _fake_run(monkeypatch, [(0, ""), (0, "")])
    assert yarn_fix.fix("ms", "2.1.3") is True


def test_fix_pins_out_of_range_patch(monkeypatch, yarn_repo):
    _fake_run(monkeypatch, [(1, AUDIT), (0, "")], why=ONE_MAJOR)
    assert yarn_fix.fix("ms", "2.1.3") is True
    assert json.loads((yarn_repo / "package.json").read_text())["resolutions"] == {
        "ms": "2.1.3",
        "qs": "6.0.0",
    }


@pytest.mark.parametrize(("why", "version"), [(TWO_MAJORS, "2.1.3"), (ONE_MAJOR, "")])
def test_fix_refuses_pin(monkeypatch, yarn_repo, why, version):
    _fake_run(monkeypatch, [(1, AUDIT)], why=why)
    assert yarn_fix.fix("ms", version) is False


def test_fix_bad_package_json(monkeypatch, yarn_repo):
    (yarn_repo / "package.json").write_text("[]")
    _fake_run(monkeypatch, [(1, AUDIT)], why=ONE_MAJOR)
    assert yarn_fix.fix("ms", "2.1.3") is False


@pytest.mark.parametrize(
    ("audits", "install_rc", "diff_rc"),
    [
        ([(1, "")], 0, 1),
        ([(1, AUDIT), (0, "")], 1, 1),
        ([(1, AUDIT), (1, AUDIT)], 0, 1),
        ([(0, ""), (0, "")], 0, 0),
    ],
)
def test_fix_unremediated(monkeypatch, yarn_repo, audits, install_rc, diff_rc):
    _fake_run(
        monkeypatch, audits, why=ONE_MAJOR, install_rc=install_rc, diff_rc=diff_rc
    )
    assert yarn_fix.fix("ms", "2.1.3") is False


def test_main_requires_package(monkeypatch):
    monkeypatch.delenv("BUMP_PACKAGE", raising=False)
    with pytest.raises(SystemExit) as exc:
        yarn_fix.main()
    assert exc.value.code
