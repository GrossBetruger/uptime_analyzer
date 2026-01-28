import pytest
import pandas as pd
from main import calculate_stats, read_logs


class TestCalculateStats:
    """Test the calculate_stats function for correctness."""

    def test_basic_offline_percentage(self):
        """50% offline should yield 50% offline percentage."""
        df = pd.DataFrame({
            "user": ["A", "A", "A", "A"],
            "status": ["online", "online", "offline", "offline"]
        })
        stats = calculate_stats(df)
        
        assert stats["total"] == 4
        assert stats["offline"] == 2
        assert stats["offline_pct"] == 50.0
        assert stats["online_pct"] == 50.0

    def test_all_online(self):
        """100% online should yield 0% offline."""
        df = pd.DataFrame({
            "user": ["A", "B", "C"],
            "status": ["online", "online", "online"]
        })
        stats = calculate_stats(df)
        
        assert stats["offline"] == 0
        assert stats["offline_pct"] == 0.0
        assert stats["online_pct"] == 100.0

    def test_all_offline(self):
        """100% offline should yield 100% offline."""
        df = pd.DataFrame({
            "user": ["A", "B"],
            "status": ["offline", "offline"]
        })
        stats = calculate_stats(df)
        
        assert stats["offline"] == 2
        assert stats["offline_pct"] == 100.0
        assert stats["online_pct"] == 0.0

    def test_empty_dataframe(self):
        """Empty dataframe should return zeros."""
        df = pd.DataFrame({"user": [], "status": []})
        stats = calculate_stats(df)
        
        assert stats["total"] == 0
        assert stats["offline"] == 0
        assert stats["offline_pct"] == 0.0
        assert stats["normalized_offline_pct"] == 0.0


class TestNormalization:
    """Test that normalization correctly weights users equally."""

    def test_normalization_removes_row_count_skew(self):
        """
        User A: 1000 rows, 1% offline (10 offline)
        User B: 10 rows, 50% offline (5 offline)
        
        Raw: 15/1010 = 1.49% offline
        Normalized: (1% + 50%) / 2 = 25.5% offline
        """
        rows_a = [{"user": "A", "status": "online"}] * 990 + [{"user": "A", "status": "offline"}] * 10
        rows_b = [{"user": "B", "status": "online"}] * 5 + [{"user": "B", "status": "offline"}] * 5
        df = pd.DataFrame(rows_a + rows_b)
        
        stats = calculate_stats(df)
        
        # Raw calculation: 15 offline out of 1010 total
        assert stats["total"] == 1010
        assert stats["offline"] == 15
        assert abs(stats["offline_pct"] - (15 / 1010 * 100)) < 0.01
        
        # Normalized: average of user A (1%) and user B (50%)
        # User A: 10/1000 = 1%, User B: 5/10 = 50%
        expected_normalized = (1.0 + 50.0) / 2  # 25.5%
        assert abs(stats["normalized_offline_pct"] - expected_normalized) < 0.01

    def test_normalization_with_equal_row_counts(self):
        """When users have equal rows, raw and normalized should match."""
        df = pd.DataFrame({
            "user": ["A", "A", "B", "B"],
            "status": ["online", "offline", "online", "offline"]
        })
        stats = calculate_stats(df)
        
        # Both users have 50% offline, so normalized equals raw
        assert stats["offline_pct"] == 50.0
        assert stats["normalized_offline_pct"] == 50.0

    def test_normalization_three_users_different_rates(self):
        """
        User A: 100% online
        User B: 100% offline  
        User C: 50% offline
        
        Normalized: (0 + 100 + 50) / 3 = 50%
        """
        df = pd.DataFrame({
            "user": ["A", "A", "B", "B", "C", "C"],
            "status": ["online", "online", "offline", "offline", "online", "offline"]
        })
        stats = calculate_stats(df)
        
        expected_normalized = (0 + 100 + 50) / 3  # 50%
        assert abs(stats["normalized_offline_pct"] - expected_normalized) < 0.01

    def test_single_user_normalized_equals_raw(self):
        """With one user, normalized should equal raw."""
        df = pd.DataFrame({
            "user": ["A"] * 100,
            "status": ["online"] * 75 + ["offline"] * 25
        })
        stats = calculate_stats(df)
        
        assert stats["offline_pct"] == 25.0
        assert stats["normalized_offline_pct"] == 25.0


class TestTimestampParsing:
    """Test extraction of hour and month from ISO timestamps."""

    def test_hour_extraction_from_iso_string(self):
        """Hours should be extracted correctly from ISO timestamps."""
        df = pd.DataFrame({
            "readable_timestamp": [
                "2025-11-18T00:30:00+02:00",
                "2025-11-18T09:15:00+02:00",
                "2025-11-18T12:00:00+02:00",
                "2025-11-18T20:45:00+02:00",
                "2025-11-18T23:59:00+02:00",
            ]
        })
        df["local_hour"] = df["readable_timestamp"].str.extract(r"T(\d{2}):")[0].astype(int)
        
        assert df["local_hour"].tolist() == [0, 9, 12, 20, 23]

    def test_month_extraction_from_iso_string(self):
        """Months should be extracted as YYYY-MM format."""
        df = pd.DataFrame({
            "readable_timestamp": [
                "2025-01-15T10:00:00+02:00",
                "2025-06-20T15:30:00+03:00",
                "2025-12-31T23:59:00+02:00",
            ]
        })
        df["month"] = df["readable_timestamp"].str[:7]
        
        assert df["month"].tolist() == ["2025-01", "2025-06", "2025-12"]

    def test_rush_hour_filter(self):
        """Rush hours 20:00-23:00 should filter correctly."""
        df = pd.DataFrame({
            "readable_timestamp": [
                "2025-11-18T19:59:00+02:00",  # Not rush
                "2025-11-18T20:00:00+02:00",  # Rush
                "2025-11-18T21:30:00+02:00",  # Rush
                "2025-11-18T22:59:00+02:00",  # Rush
                "2025-11-18T23:00:00+02:00",  # Not rush (end exclusive)
            ]
        })
        df["local_hour"] = df["readable_timestamp"].str.extract(r"T(\d{2}):")[0].astype(int)
        df["is_rush_hour"] = (df["local_hour"] >= 20) & (df["local_hour"] < 23)
        
        assert df["is_rush_hour"].tolist() == [False, True, True, True, False]


class TestReadLogs:
    """Test the log parsing function."""

    def test_parse_log_line_format(self):
        """Verify log parsing extracts all fields correctly."""
        # Create a minimal test log file content
        log_content = "1699999999 2025-11-18T10:30:00+02:00 TestUser 1.2.3.4 SomeISP online\n"
        
        # Write to temp file and read
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(log_content)
            temp_path = f.name
        
        try:
            df = read_logs(temp_path)
            
            assert len(df) == 1
            assert df.iloc[0]["user"] == "TestUser"
            assert df.iloc[0]["status"] == "online"
            assert df.iloc[0]["isp"] == "SomeISP"
            assert df.iloc[0]["readable_timestamp"] == "2025-11-18T10:30:00+02:00"
        finally:
            import os
            os.unlink(temp_path)

    def test_parse_offline_status(self):
        """Verify offline status is parsed correctly."""
        log_content = "1699999999 2025-11-18T10:30:00+02:00 TestUser 1.2.3.4 ISP offline\n"
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(log_content)
            temp_path = f.name
        
        try:
            df = read_logs(temp_path)
            assert df.iloc[0]["status"] == "offline"
        finally:
            import os
            os.unlink(temp_path)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_user_with_zero_offline(self):
        """User with 0% offline shouldn't break normalization."""
        df = pd.DataFrame({
            "user": ["A", "A", "B"],
            "status": ["online", "online", "offline"]
        })
        stats = calculate_stats(df)
        
        # User A: 0% offline, User B: 100% offline
        # Normalized: (0 + 100) / 2 = 50%
        assert stats["normalized_offline_pct"] == 50.0

    def test_single_row_per_user(self):
        """Single row per user should work correctly."""
        df = pd.DataFrame({
            "user": ["A", "B", "C"],
            "status": ["online", "offline", "online"]
        })
        stats = calculate_stats(df)
        
        assert stats["total"] == 3
        assert stats["offline"] == 1
        # Normalized: (0 + 100 + 0) / 3 = 33.33%
        assert abs(stats["normalized_offline_pct"] - 33.33) < 0.1

    def test_large_skew_scenario(self):
        """
        Extreme skew case:
        User A: 10000 rows, 0.1% offline (10 offline)
        User B: 1 row, 100% offline (1 offline)
        
        Raw: 11/10001 = 0.11% offline
        Normalized: (0.1% + 100%) / 2 = 50.05% offline
        """
        rows_a = [{"user": "A", "status": "online"}] * 9990 + [{"user": "A", "status": "offline"}] * 10
        rows_b = [{"user": "B", "status": "offline"}]
        df = pd.DataFrame(rows_a + rows_b)
        
        stats = calculate_stats(df)
        
        # Raw should be close to 0.11%
        assert stats["offline_pct"] < 0.15
        
        # Normalized should be close to 50%
        # User A: 10/10000 = 0.1%, User B: 1/1 = 100%
        expected = (0.1 + 100) / 2  # 50.05%
        assert abs(stats["normalized_offline_pct"] - expected) < 0.1
