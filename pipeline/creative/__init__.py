"""Hybrid creative engine: the local LLM proposes content (hook choice, copy within budgets); deterministic,
professionally designed scene templates compose every scene; every UI label and number comes from template
constants or verified facts; Python owns timing. See docs/CREATIVE_SYSTEM.md.

    from pipeline.creative import generate_concepts, build_storyboard
    res = generate_concepts(brief, provider="none", out_dir="output/creative-eval/x")
    sb, project, reports = build_storyboard(res["brief"], res["concepts"][0], provider="none", out_dir="output/creative-eval/x")
"""
from .api import build_storyboard, generate_concepts

__all__ = ["generate_concepts", "build_storyboard"]
