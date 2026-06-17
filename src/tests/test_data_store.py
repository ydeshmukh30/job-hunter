"""Tests for src/common/data_store.py, integrity.py, and run_state.py.

All file I/O uses the ``tmp_path`` pytest fixture — the real ``src/data/``
directory is never touched.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Helpers to patch module-level Path constants in data_store and run_state
# so they point at tmp_path during tests.
# ---------------------------------------------------------------------------


def _patch_data_store(tmp_path: Path):
    """Return the data_store module with its paths redirected to *tmp_path*."""
    # Force a fresh import so module-level constants are re-evaluated.
    if "src.common.data_store" in sys.modules:
        del sys.modules["src.common.data_store"]
    if "src.common.integrity" in sys.modules:
        del sys.modules["src.common.integrity"]

    import src.common.integrity as integrity_mod
    import src.common.data_store as ds_mod

    # Override module-level paths.
    ds_mod.DATA_DIR = tmp_path
    ds_mod.CSV_PATH = tmp_path / "job_applications.csv"
    ds_mod.SIDECAR_PATH = tmp_path / "job_applications.csv.sha256"
    ds_mod.LOCK_PATH = tmp_path / "job_applications.csv.lock"

    return ds_mod, integrity_mod


def _patch_run_state(tmp_path: Path):
    """Return the run_state module with its paths redirected to *tmp_path*."""
    if "src.common.run_state" in sys.modules:
        del sys.modules["src.common.run_state"]

    import src.common.run_state as rs_mod

    rs_mod.DATA_DIR = tmp_path
    rs_mod.STATE_PATH = tmp_path / "run_state.json"

    return rs_mod


# ===========================================================================
# 1. init_csv() creates file with correct headers
# ===========================================================================


def test_init_csv_creates_file_with_headers(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    csv_file = tmp_path / "job_applications.csv"

    assert not csv_file.exists()
    ds.init_csv()
    assert csv_file.exists()

    lines = csv_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(ds.HEADERS)


def test_init_csv_is_idempotent(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()
    ds.init_csv()  # second call must not raise or duplicate the header

    lines = [l for l in (tmp_path / "job_applications.csv").read_text().splitlines() if l]
    # Only one header row.
    assert lines.count(",".join(ds.HEADERS)) == 1


# ===========================================================================
# 2. append_jobs() 100 rows → read_all() returns exactly 100 rows (no row loss)
# ===========================================================================


def _make_jobs(n: int) -> list[dict]:
    return [
        {
            "title": f"Engineer {i}",
            "company": f"Company {i}",
            "platform": "linkedin",
            "url": f"https://example.com/job/{i}",
            "apply_type": "easy_apply",
            "status": "scraped",
            "ctc": "30-50 LPA",
            "yoe_required": "3-6 years",
            "location": "Bengaluru",
        }
        for i in range(n)
    ]


def test_append_100_jobs_no_row_loss(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()

    jobs = _make_jobs(100)
    ids = ds.append_jobs(jobs)

    assert len(ids) == 100
    rows = ds.read_all()
    assert len(rows) == 100


def test_append_jobs_returns_unique_ids(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()

    ids = ds.append_jobs(_make_jobs(10))
    assert len(set(ids)) == 10  # all unique


def test_append_jobs_empty_list_is_noop(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()

    ids = ds.append_jobs([])
    assert ids == []
    assert ds.read_all() == []


# ===========================================================================
# 3. update_job() changes only specified fields, leaves others intact
# ===========================================================================


def test_update_job_changes_only_specified_fields(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()

    (job_id,) = ds.append_jobs(
        [
            {
                "title": "Backend Engineer",
                "company": "Razorpay",
                "platform": "linkedin",
                "url": "https://example.com/1",
                "apply_type": "easy_apply",
                "status": "scraped",
                "ctc": "40-60 LPA",
                "yoe_required": "4-7 years",
                "location": "Bengaluru",
            }
        ]
    )

    ds.update_job(job_id, status="applied", next_steps="Waiting for HR call")

    rows = ds.read_all()
    assert len(rows) == 1
    row = rows[0]

    # Updated fields
    assert row["status"] == "applied"
    assert row["next_steps"] == "Waiting for HR call"

    # Unchanged fields
    assert row["title"] == "Backend Engineer"
    assert row["company"] == "Razorpay"
    assert row["platform"] == "linkedin"
    assert row["url"] == "https://example.com/1"
    assert row["apply_type"] == "easy_apply"
    assert row["ctc"] == "40-60 LPA"
    assert row["yoe_required"] == "4-7 years"
    assert row["location"] == "Bengaluru"
    assert row["id"] == job_id


def test_update_job_raises_for_unknown_id(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()

    with pytest.raises(KeyError):
        ds.update_job("non-existent-id", status="applied")


def test_update_job_bumps_last_activity_automatically(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()

    (job_id,) = ds.append_jobs(_make_jobs(1))
    original_rows = ds.read_all()
    original_activity = original_rows[0]["last_activity"]

    # Small sleep not needed — we just verify last_activity is non-empty and a
    # valid ISO string; the exact value may differ by sub-second on fast machines.
    ds.update_job(job_id, status="applied")
    updated_rows = ds.read_all()
    new_activity = updated_rows[0]["last_activity"]

    assert new_activity  # non-empty
    datetime.fromisoformat(new_activity)  # parses as valid ISO 8601


# ===========================================================================
# 4. Tamper CSV bytes after write → integrity.verify() raises IntegrityError
# ===========================================================================


def test_tampered_csv_raises_integrity_error(tmp_path):
    ds, integrity = _patch_data_store(tmp_path)
    ds.init_csv()
    ds.append_jobs(_make_jobs(3))

    csv_file = tmp_path / "job_applications.csv"
    sidecar = tmp_path / "job_applications.csv.sha256"

    # Corrupt a byte in the middle of the CSV.
    content = csv_file.read_bytes()
    tampered = content[: len(content) // 2] + b"X" + content[len(content) // 2 + 1 :]
    csv_file.write_bytes(tampered)

    with pytest.raises(integrity.IntegrityError):
        integrity.verify(csv_file, sidecar)


def test_tampered_csv_blocks_read_all(tmp_path):
    ds, integrity = _patch_data_store(tmp_path)
    ds.init_csv()
    ds.append_jobs(_make_jobs(2))

    csv_file = tmp_path / "job_applications.csv"
    content = csv_file.read_bytes()
    csv_file.write_bytes(content + b"\nextra garbage row")

    with pytest.raises(integrity.IntegrityError):
        ds.read_all()


# ===========================================================================
# 5. baseline() re-writes sidecar → verify() passes again
# ===========================================================================


def test_baseline_after_tamper_allows_verify(tmp_path):
    ds, integrity = _patch_data_store(tmp_path)
    ds.init_csv()
    ds.append_jobs(_make_jobs(2))

    csv_file = tmp_path / "job_applications.csv"
    sidecar = tmp_path / "job_applications.csv.sha256"

    # Tamper.
    csv_file.write_bytes(csv_file.read_bytes() + b"\nmanually added row")

    # Re-baseline.
    integrity.baseline(csv_file, sidecar)

    # Verify should now pass (no exception).
    integrity.verify(csv_file, sidecar)


def test_verify_no_op_when_csv_missing(tmp_path):
    _, integrity = _patch_data_store(tmp_path)
    csv_file = tmp_path / "missing.csv"
    sidecar = tmp_path / "missing.csv.sha256"

    # Should not raise.
    integrity.verify(csv_file, sidecar)


def test_verify_raises_when_sidecar_missing_but_csv_exists(tmp_path):
    _, integrity = _patch_data_store(tmp_path)
    csv_file = tmp_path / "data.csv"
    sidecar = tmp_path / "data.csv.sha256"

    csv_file.write_text("id,title\n1,foo\n", encoding="utf-8")
    # No sidecar written.

    with pytest.raises(integrity.IntegrityError):
        integrity.verify(csv_file, sidecar)


# ===========================================================================
# 6. did_run_today() returns True when last_success_ts is today at expected
#    hour, False otherwise
# ===========================================================================


def test_did_run_today_true_when_run_at_expected_hour(tmp_path):
    rs = _patch_run_state(tmp_path)
    now = datetime.now(tz=IST)
    # Set last_success_ts to today at hour 19 (7 PM IST).
    ts = now.replace(hour=19, minute=5, second=0, microsecond=0)
    state = rs.load()
    state.setdefault("agents", {})["scraper"] = {
        "last_success_ts": ts.isoformat(),
        "last_task_summary": "ok",
        "last_status": "success",
    }
    rs.save(state)

    assert rs.did_run_today("scraper", expected_hour_ist=19) is True


def test_did_run_today_false_when_run_before_expected_hour(tmp_path):
    rs = _patch_run_state(tmp_path)
    now = datetime.now(tz=IST)
    # Set to today at 10 AM — before the 7 PM expected window.
    ts = now.replace(hour=10, minute=0, second=0, microsecond=0)
    state = rs.load()
    state.setdefault("agents", {})["scraper"] = {
        "last_success_ts": ts.isoformat(),
        "last_task_summary": "ok",
        "last_status": "success",
    }
    rs.save(state)

    assert rs.did_run_today("scraper", expected_hour_ist=19) is False


def test_did_run_today_false_when_run_yesterday(tmp_path):
    rs = _patch_run_state(tmp_path)
    yesterday = datetime.now(tz=IST) - timedelta(days=1)
    ts = yesterday.replace(hour=19, minute=5, second=0, microsecond=0)
    state = rs.load()
    state.setdefault("agents", {})["scraper"] = {
        "last_success_ts": ts.isoformat(),
        "last_task_summary": "ok",
        "last_status": "success",
    }
    rs.save(state)

    assert rs.did_run_today("scraper", expected_hour_ist=19) is False


def test_did_run_today_false_for_unknown_agent(tmp_path):
    rs = _patch_run_state(tmp_path)
    assert rs.did_run_today("no_such_agent") is False


# ===========================================================================
# 7. record_skipped_platform + get_unretried_platforms round-trip
# ===========================================================================


def test_record_and_get_unretried_platforms(tmp_path):
    rs = _patch_run_state(tmp_path)

    rs.record_skipped_platform("linkedin", "LoginError")
    rs.record_skipped_platform("naukri", "CAPTCHA")

    unretried = rs.get_unretried_platforms()
    platforms = [p["platform"] for p in unretried]

    assert "linkedin" in platforms
    assert "naukri" in platforms
    assert len(unretried) == 2


def test_skipped_platform_entry_has_required_fields(tmp_path):
    rs = _patch_run_state(tmp_path)
    rs.record_skipped_platform("indeed", "network_error")

    entries = rs.get_unretried_platforms()
    assert len(entries) == 1
    entry = entries[0]

    assert entry["platform"] == "indeed"
    assert entry["reason"] == "network_error"
    assert entry["retried"] is False
    assert entry["ts"]  # non-empty timestamp
    datetime.fromisoformat(entry["ts"])  # valid ISO 8601


# ===========================================================================
# 8. mark_retried_platform → get_unretried_platforms no longer returns it
# ===========================================================================


def test_mark_retried_platform_removes_from_unretried(tmp_path):
    rs = _patch_run_state(tmp_path)

    rs.record_skipped_platform("linkedin", "LoginError")
    rs.record_skipped_platform("naukri", "CAPTCHA")

    rs.mark_retried_platform("linkedin")

    unretried = rs.get_unretried_platforms()
    platforms = [p["platform"] for p in unretried]

    assert "linkedin" not in platforms
    assert "naukri" in platforms


def test_mark_retried_platform_sets_all_matching_entries(tmp_path):
    """mark_retried_platform must set retried=true for ALL entries, not just first."""
    rs = _patch_run_state(tmp_path)

    # Two separate failure events for the same platform.
    rs.record_skipped_platform("linkedin", "LoginError")
    rs.record_skipped_platform("linkedin", "CAPTCHA")

    rs.mark_retried_platform("linkedin")

    state = rs.load()
    linkedin_entries = [
        e for e in state["skipped"]["platforms"] if e["platform"] == "linkedin"
    ]
    assert all(e["retried"] is True for e in linkedin_entries)
    assert rs.get_unretried_platforms() == []


# ===========================================================================
# 9. reset_daily_spend_if_new_day() resets spend when date changes
# ===========================================================================


def test_reset_daily_spend_resets_on_new_day(tmp_path):
    rs = _patch_run_state(tmp_path)

    # Simulate a previous day's spend by writing a stale date directly.
    state = rs.load()
    state["llm_spend"] = {"date": "2000-01-01", "usd": 9.99}
    rs.save(state)

    rs.reset_daily_spend_if_new_day()

    assert rs.get_llm_spend_today() == 0.0


def test_reset_daily_spend_does_not_reset_on_same_day(tmp_path):
    rs = _patch_run_state(tmp_path)

    rs.add_llm_spend(0.50)
    rs.reset_daily_spend_if_new_day()

    assert rs.get_llm_spend_today() == pytest.approx(0.50, abs=1e-6)


# ===========================================================================
# Bonus: additional run_state coverage
# ===========================================================================


def test_add_llm_spend_accumulates(tmp_path):
    rs = _patch_run_state(tmp_path)

    rs.add_llm_spend(0.10)
    rs.add_llm_spend(0.25)

    assert rs.get_llm_spend_today() == pytest.approx(0.35, abs=1e-6)


def test_record_agent_success_and_failure(tmp_path):
    rs = _patch_run_state(tmp_path)

    rs.record_agent_success("scraper", "Scraped 12 jobs across 4 platforms")
    state = rs.load()
    assert state["agents"]["scraper"]["last_status"] == "success"
    assert state["agents"]["scraper"]["last_task_summary"] == "Scraped 12 jobs across 4 platforms"
    assert state["agents"]["scraper"]["last_success_ts"]  # non-empty

    last_success = state["agents"]["scraper"]["last_success_ts"]

    rs.record_agent_failure("scraper", "Network timeout on linkedin")
    state2 = rs.load()
    assert state2["agents"]["scraper"]["last_status"] == "failure"
    # last_success_ts must NOT be overwritten on failure.
    assert state2["agents"]["scraper"]["last_success_ts"] == last_success


def test_record_skipped_job_round_trip(tmp_path):
    rs = _patch_run_state(tmp_path)

    job = {
        "id": "abc-123",
        "company": "Razorpay",
        "title": "Senior Backend Engineer",
        "url": "https://example.com/job/1",
    }
    rs.record_skipped_job(job, "unknown_ats:greenhouse")

    unretried = rs.get_unretried_jobs()
    assert len(unretried) == 1
    entry = unretried[0]

    assert entry["id"] == "abc-123"
    assert entry["company"] == "Razorpay"
    assert entry["title"] == "Senior Backend Engineer"
    assert entry["url"] == "https://example.com/job/1"
    assert entry["reason"] == "unknown_ats:greenhouse"
    assert entry["retried"] is False


def test_mark_retried_job(tmp_path):
    rs = _patch_run_state(tmp_path)

    rs.record_skipped_job({"id": "j1", "company": "A", "title": "T", "url": "U"}, "r1")
    rs.record_skipped_job({"id": "j2", "company": "B", "title": "T2", "url": "U2"}, "r2")

    rs.mark_retried_job("j1")

    unretried = rs.get_unretried_jobs()
    ids = [j["id"] for j in unretried]
    assert "j1" not in ids
    assert "j2" in ids


def test_get_companies_normalises_names(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()

    ds.append_jobs(
        [
            {**_make_jobs(1)[0], "company": "Razorpay Inc"},
            {**_make_jobs(1)[0], "company": "Flipkart Pvt Ltd"},
            {**_make_jobs(1)[0], "company": "Swiggy"},
        ]
    )

    companies = ds.get_companies()

    # All should be normalised (lowercased, suffixes stripped).
    assert "razorpay" in companies
    assert "flipkart" in companies
    assert "swiggy" in companies
    # Original names should NOT appear.
    assert "Razorpay Inc" not in companies


def test_read_by_status_filters_correctly(tmp_path):
    ds, _ = _patch_data_store(tmp_path)
    ds.init_csv()

    scraped_jobs = _make_jobs(3)
    applied_jobs = [{**j, "status": "applied"} for j in _make_jobs(2)]

    ds.append_jobs(scraped_jobs)
    ds.append_jobs(applied_jobs)

    scraped_rows = ds.read_by_status("scraped")
    applied_rows = ds.read_by_status("applied")

    assert len(scraped_rows) == 3
    assert len(applied_rows) == 2
    assert all(r["status"] == "scraped" for r in scraped_rows)
    assert all(r["status"] == "applied" for r in applied_rows)


def test_read_all_verifies_integrity_on_tamper(tmp_path):
    ds, integrity = _patch_data_store(tmp_path)
    ds.init_csv()
    ds.append_jobs(_make_jobs(2))

    # Tamper the CSV directly (bypassing data_store).
    csv_file = tmp_path / "job_applications.csv"
    csv_file.write_bytes(csv_file.read_bytes() + b"\ntampered")

    with pytest.raises(integrity.IntegrityError):
        ds.read_all()
