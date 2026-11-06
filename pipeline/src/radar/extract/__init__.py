"""Structured extraction of remote job postings with Claude or a local Ollama model."""

from radar.extract.llm import ExtractionResult, Extractor, JobInput, get_extractor
from radar.extract.schema import ExtractedJob

__all__ = ["ExtractedJob", "ExtractionResult", "Extractor", "JobInput", "get_extractor"]
