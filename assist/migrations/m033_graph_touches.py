"""Graph memory, phase 1 (DESIGN-GRAPH-MEMORY.md; Sam, 17 Nov 2026): what each new item touched, one hop through its sure
links and a second along chosen edges, so pages can show what came in since their record was written (assist/graph_memory.py)."""


def up(con):
    from .. import graph_memory
    graph_memory.ensure_schema(con)
