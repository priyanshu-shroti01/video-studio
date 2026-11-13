"""Local-first video production pipeline (orchestrator).

Stages: PREPARING -> GENERATING_AUDIO -> BUILDING_TIMELINE -> RENDERING -> POST_PROCESSING -> QA.
Python owns all timing; Remotion (src/engine) only draws RenderProps (see pipeline/contract.py).
"""
__version__ = "0.4.0"
