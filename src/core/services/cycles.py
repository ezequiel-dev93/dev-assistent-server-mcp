from typing import Dict, List, Set


def find_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """
    Finds all non-trivial strongly connected components (cycles) in a directed dependency graph
    using Tarjan's SCC algorithm. Returns a deterministic list of cycles (each as a path list).
    """
    index_counter = 0
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    stack: List[str] = []
    on_stack: Set[str] = set()
    cycles: List[List[str]] = []

    all_nodes = sorted(set(graph.keys()) | {dst for dsts in graph.values() for dst in dsts})

    def strongconnect(node: str) -> None:
        nonlocal index_counter
        indices[node] = index_counter
        lowlink[node] = index_counter
        index_counter += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])

        if lowlink[node] == indices[node]:
            scc: List[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                scc.append(w)
                if w == node:
                    break
            if len(scc) > 1:
                ordered = sorted(scc)
                cycles.append(ordered + [ordered[0]])
            elif len(scc) == 1:
                single = scc[0]
                if single in graph.get(single, set()):
                    cycles.append([single, single])

    for n in all_nodes:
        if n not in indices:
            strongconnect(n)

    return cycles
