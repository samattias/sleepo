"""Graph memory, phase 2 (DESIGN-GRAPH-MEMORY.md §2.4; Sam, 17 Nov 2026): each review of a record with new material, its
verdict, the facts that changed with the items they came from, and what was rewritten (assist/graph_refresh.py)."""


def up(con):
    from .. import graph_refresh
    graph_refresh.ensure_schema(con)
