import yaml

def make_graph_stats(method: str, input_file: str, output_file: str) -> None:
    """Produce a simple YAML output containing select graph statistics.
    This is based on the statistics emitted by KGX
    after producing the merged graph. 

    Args:
        method: a string, either 'kgx' or 'catmerge'.
        This determines the expected input stats format.
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

    if method == 'kgx':
        stats['nodecount'] = merged_stats['node_stats']['total_nodes']
        stats['edgecount'] = merged_stats['edge_stats']['total_edges']

    if method == 'catmerge':
        stats['nodecount'] = merged_stats['nodes'][0]['total_number']
        stats['edgecount'] = merged_stats['edges'][0]['total_number']

    with open(output_file, 'w') as stats_file:
        stats_file.write(yaml.dump(stats,
                                   default_flow_style=False,
                                   sort_keys=False))
