from unittest import TestCase, skipIf, mock
import unittest
from click.testing import CliRunner

from run import merge
import os

class TestRun(TestCase):
    """Tests merge function on current merge.yaml.
        A bit unorthodox as it works on the live
        merge file and output, but necessary
        to avoid issues with current merge config.
        
        This should only run locally, as on a GH Action
        it won't have access to the necessary data.
        """
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.merge_config_path = 'merge.yaml'
        self.stats_path = 'merged_graph_stats.yaml'
        self.output_out_path = 'data/merged/merged-kg.tar.gz' 

    @unittest.skipIf(os.getenv('GITHUB_ACTIONS'), "Merge test only runs when data is available.")
    def test_current_merge(self):
        result = self.runner.invoke(catch_exceptions=False,
                                        cli=merge,
                                        args=['-y',
                                              self.merge_config_path]
                                        )
        self.assertTrue(os.path.isfile(self.stats_path))
        self.assertTrue(os.path.isfile(self.output_out_path))




