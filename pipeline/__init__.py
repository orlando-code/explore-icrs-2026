"""Staged data pipeline: raw sources → verified artifacts → JS site exports."""

from pipeline.config import PIPELINE_STAGES, PipelineConfig

__all__ = ["PIPELINE_STAGES", "PipelineConfig"]
