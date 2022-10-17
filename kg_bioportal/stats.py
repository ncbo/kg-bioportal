import yaml

def make_graph_stats(input_file: str, output_file: str) -> None:
    """Produce a simple YAML output containing select graph statistics.
    This is based on the statistics emitted by KGX
    after producing the merged graph. 

    Args:
        input_dir: A string pointing to the name of the file
        to extract stats from.
        output_dir: A string pointing to the name of the file
        to write summary stats to.

    Returns:
        None.

    """

    stats = {}

    with open(input_file) as merged_stats_file:
        merged_stats = yaml.load(merged_stats_file, Loader=yaml.FullLoader)

    stats['nodecount'] = merged_stats['node_stats']['total_nodes']
    stats['edgecount'] = merged_stats['edge_stats']['total_edges']

    with open(output_file, 'w') as stats_file:
        stats_file.write(yaml.dump(stats,
                                   default_flow_style=False,
                                   sort_keys=False))
