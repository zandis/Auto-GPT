"""Box reply subjects lead with study and outcome (D-88); the review mail says how criteria are checked."""

from __future__ import annotations

import pytest
from orchestrator.scenarios.review import check_split
from tb_common.subject import SubjectError, is_job_mail, job_subject, parse_subject

JOB = "01M5SNZ479E2X7MGR2NGDCKAY6"


def test_job_subject_leads_with_study_and_outcome() -> None:
    s = job_subject("done", "FEAS", "GZQO", JOB, "1–7 in 12 mo")
    assert s == f"[GZQO] FEAS done: 1–7 in 12 mo · job {JOB}"
    assert job_subject("received", "STATUS", None, JOB) == f"STATUS received · job {JOB}"
    assert is_job_mail(s, "done", JOB) and not is_job_mail(s, "failed", JOB)
    assert not is_job_mail(s, "done", "01M5SNZ479E2X7MGR2NGDCKAY7")


def test_a_reply_to_a_box_mail_is_not_a_new_command() -> None:
    with pytest.raises(SubjectError, match="unknown command"):
        parse_subject("Re: " + job_subject("done", "FEAS", "GZQO", JOB, "1–7 in 12 mo"))


def test_review_mail_counts_how_criteria_are_checked() -> None:
    html = (
        "<tr><td>X-INC-01</td><td>inclusion</td><td>structured</td></tr>"
        "<tr><td>X-INC-02</td><td>inclusion</td><td>structured</td></tr>"
        "<tr><td>X-EXC-01</td><td>exclusion</td><td>note</td></tr>"
    )
    line = check_split(html)
    assert "the 3 criteria: **2** by a fixed filter" in line and "**1** by the model" in line and "**0** left" in line
    assert check_split("<p>no table</p>") == ""
