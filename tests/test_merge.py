from unittest import TestCase, skip
from click.testing import CliRunner
from unittest import mock

from run import merge
import os


class TestRun(TestCase):
    """Tests merge function on current merge.yaml.
        A bit unorthodox as it works on the live
        merge file and output, but necessary
        to avoid issues with current merge config.
        
        This is temporary - larger graphs will be
        too big to run as a test through GH Actions
        """
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.merge_config_path = 'merge.yaml'
        self.stats_path = 'merged_graph_stats.yaml'
        self.output_out_path = 'data/merged/merged-kg.tar.gz' 

    def test_current_merge(self):
        result = self.runner.invoke(catch_exceptions=False,
                                        cli=merge,
                                        args=['-y',
                                              self.merge_config_path]
                                        )
        self.assertTrue(os.path.isfile(self.stats_path))
        self.assertTrue(os.path.isfile(self.output_out_path))




