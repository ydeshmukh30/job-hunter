"""SHA-256 integrity guard for the CSV data file.

Sidecar format:  sha256:<hex_digest>
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class IntegrityError(Exception):
    """Raised when the CSV hash does not match the sidecar."""


def _compute_sha256(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of *path* bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def baseline(csv_path: Path, sidecar_path: Path) -> None:
    """Compute the SHA-256 hash of *csv_path* and write it to *sidecar_path*.

    Called after every write and also when the user passes
    ``--force-accept-manual-edit`` to re-baseline after a manual edit.
    """
    if not csv_path.exists():
        return
    digest = _compute_sha256(csv_path)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(f"sha256:{digest}", encoding="utf-8")


def verify(csv_path: Path, sidecar_path: Path) -> None:
    """Verify that *csv_path* matches the hash stored in *sidecar_path*.

    Behaviour:
    - No-op if *csv_path* does not exist yet (first run before any data).
    - Raises :class:`IntegrityError` if the sidecar is missing but the CSV
      exists (unexpected state — treat as tamper).
    - Raises :class:`IntegrityError` if the recomputed digest differs from
      the stored one.
    """
    if not csv_path.exists():
        # First run — nothing to verify yet.
        return

    if not sidecar_path.exists():
        raise IntegrityError(
            f"Integrity sidecar missing: {sidecar_path}. "
            "Run with --force-accept-manual-edit to re-baseline."
        )

    stored = sidecar_path.read_text(encoding="utf-8").strip()
    if not stored.startswith("sha256:"):
        raise IntegrityError(
            f"Sidecar format invalid (expected 'sha256:<hex>'): {sidecar_path}"
        )

    expected_digest = stored[len("sha256:"):]
    actual_digest = _compute_sha256(csv_path)

    if actual_digest != expected_digest:
        raise IntegrityError(
            f"manual edit detected: hash mismatch "
            f"(stored={expected_digest[:12]}… actual={actual_digest[:12]}…). "
            "Run with --force-accept-manual-edit to re-baseline and continue."
        )
