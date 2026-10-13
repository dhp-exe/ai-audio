"""Workflow graphs (LangGraph): how a run is ordered, fanned out, paused and resumed.

    series_graph    research -> script -> casting -> one episode after another (budget check before each)
    episode_graph   draft -> direct -> scenes in parallel -> join -> master -> episode QA -> gate
    scene_graph     render -> scene QA -> retry (bounded) -> [approval] for one scene

Agents stay plain functions: a node calls an agent, never the reverse. Graph state holds small JSON values and
ids; the artifacts themselves (plans, stems, reports) are read back from the repositories and re-validated.
"""
