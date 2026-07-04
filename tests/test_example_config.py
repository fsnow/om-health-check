"""Parity between the built-in defaults and examples/all-thresholds.yaml.

The reference config is documented as listing every metric threshold at its
built-in default, so loading it must be a no-op for thresholds — otherwise the
file has drifted from the code (a metric default changed on one side only, or a
new metric was added without documenting it).

The one intentional difference is the `version:` block: it adds advisory notes
(CVE text) that are deliberately absent from code (notes are YAML-only), so a
below-minimum finding gains the note when this config is loaded. Minimums and
severity, however, must still match the code defaults.
"""

from pathlib import Path

import pytest

import om_health_check.checks.version as version_mod
from om_health_check import thresholds as thr

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "all-thresholds.yaml"


def _yaml():
    yaml = pytest.importorskip("yaml")
    with open(EXAMPLE) as f:
        return yaml.safe_load(f)


def test_all_thresholds_yaml_lists_every_metric():
    """Completeness: the reference file documents exactly the code's metrics."""
    data = _yaml()
    yaml_names = set(data.get("thresholds", {}).keys())
    code_names = set(thr.THRESHOLDS.keys())
    only_yaml = yaml_names - code_names
    only_code = code_names - yaml_names
    assert not only_yaml, f"yaml lists unknown metrics: {sorted(only_yaml)}"
    assert not only_code, f"metrics missing from all-thresholds.yaml: {sorted(only_code)}"


def test_all_thresholds_yaml_matches_code_defaults():
    """Value parity: loading the reference file changes no threshold."""
    snapshot = {k: v for k, v in thr.THRESHOLDS.items()}
    try:
        thr.load_overrides(str(EXAMPLE))
        drifted = {
            k: (snapshot[k], thr.THRESHOLDS[k])
            for k in snapshot
            if thr.THRESHOLDS[k] != snapshot[k]
        }
        assert not drifted, (
            "all-thresholds.yaml drifted from code defaults:\n"
            + "\n".join(f"  {k}: default={d} yaml={y}" for k, (d, y) in drifted.items())
        )
    finally:
        for k, v in snapshot.items():
            thr.THRESHOLDS[k] = v


def test_version_block_minimums_and_severity_match_defaults():
    """The version block's minimums/severity are the code defaults (notes differ)."""
    data = _yaml()
    vcfg = data["version"]

    # severity default is INFO
    assert vcfg["severity"] == "info"

    # every minimum listed equals the code default for that line
    code_min = version_mod.MINIMUM_SAFE_VERSIONS
    for line, minimum in vcfg["minimum_safe_versions"].items():
        assert code_min.get(line) == minimum, (
            f"version line {line}: yaml={minimum} code_default={code_min.get(line)}"
        )
    # and the file documents every built-in line
    assert set(vcfg["minimum_safe_versions"].keys()) == set(code_min.keys())


def test_version_notes_are_the_intentional_delta():
    """Notes exist only in YAML (code default is empty) — the one real difference."""
    assert version_mod.VERSION_NOTES == {}, "code should ship no hardcoded notes"
    data = _yaml()
    notes = data["version"].get("version_notes", {})
    assert notes, "all-thresholds.yaml should document advisory notes"
    # every noted line is a real minimum line, and notes reference a real CVE
    for line, text in notes.items():
        assert line in version_mod.MINIMUM_SAFE_VERSIONS
        assert "CVE-2026-11933" in text
