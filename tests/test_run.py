"""Test the run script."""

from unittest import TestCase

from click.testing import CliRunner

from run import merge, transform


class TestRun(TestCase):
    """Tests the run.py script."""

    def setUp(self) -> None:
        """Set up for tests."""
        self.runner = CliRunner()

    def test_transform(self):
        """Test call to transform function."""
        result = self.runner.invoke(cli=transform, args=["-i", "tests/data/raw"])
        self.assertNotEqual(result.exit_code, 0)

    def test_merge_missing_file_error(self):
        """Test case of missing input file."""
        with self.assertRaises(FileNotFoundError) as context:
            result = self.runner.invoke(
                catch_exceptions=False,
                cli=merge,
                args=["-y", "tests/resources/merge_MISSING_FILE.yaml"],
            )
            self.assertNotEqual(result.exit_code, 0)
            self.assertRegexpMatches(result.output, "does not exist")
