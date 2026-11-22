# Import the internal function directly from the module under test.
from tools.accuracy_set import _binom_cdf


def test_binom_cdf_p_one_returns_one_when_k_ge_n() -> None:
    """
    When the success probability p is exactly 1.0, the binomial distribution is degenerate:
    all probability mass is at k = n. Therefore the cumulative distribution function (CDF)
    should be 1.0 for any k >= n. The current implementation returns 0.0 for all p >= 1.0,
    which is incorrect. This test will fail under the current code, proving the defect.
    """
    n = 7
    k = 7  # k == n, CDF should be 1.0
    p = 1.0
    result = _binom_cdf(k, n, p)
    assert result == 1.0, f"Expected CDF=1.0 for p=1.0 and k>=n, got {result}"


def test_binom_cdf_p_one_returns_zero_when_k_less_than_n() -> None:
    """
    For completeness, verify that the CDF is 0.0 when k < n and p == 1.0.
    This should pass under the current implementation.
    """
    n = 7
    k = 5  # k < n, CDF should be 0.0
    p = 1.0
    result = _binom_cdf(k, n, p)
    assert result == 0.0, f"Expected CDF=0.0 for p=1.0 and k<n, got {result}"
