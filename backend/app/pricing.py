"""Per-model OpenRouter pricing + cost estimation. Reference: roadmap 1.4, T102.

A small constant price map keyed by model id, plus a pure helper that turns a
token count into an estimated USD cost. Pricing is denominated in USD per 1M
tokens (the unit OpenRouter publishes), split into prompt (input) and
completion (output) rates.

This lives apart from ``metrics.py`` so the pricing table is editable in one
place and the cost math is unit-testable without touching the counter store.
The numbers are operator-facing estimates for a solo local tool — they are not
billing-grade and drift as OpenRouter changes its rate card.
"""

from __future__ import annotations

from typing import NamedTuple


class ModelPrice(NamedTuple):
    """USD price per 1,000,000 tokens, split by direction."""

    prompt_usd_per_mtok: float
    completion_usd_per_mtok: float


# USD per 1M tokens. Keys are OpenRouter model ids. Keep the configured default
# model (`config.OPENROUTER_MODEL`) present so today's spend is never silently
# zero just because no entry matched. Unknown models fall back to FALLBACK_PRICE.
_TOKENS_PER_MTOK = 1_000_000.0

MODEL_PRICES: dict[str, ModelPrice] = {
    # Default model (config.openrouter_model).
    "anthropic/claude-sonnet-4.5": ModelPrice(3.0, 15.0),
    "anthropic/claude-3.5-sonnet": ModelPrice(3.0, 15.0),
    "anthropic/claude-3.5-haiku": ModelPrice(0.8, 4.0),
    "anthropic/claude-3-haiku": ModelPrice(0.25, 1.25),
    "openai/gpt-4o": ModelPrice(2.5, 10.0),
    "openai/gpt-4o-mini": ModelPrice(0.15, 0.6),
}

# Used when a model id is not in MODEL_PRICES. Mirrors the default model so a
# rename of the configured model still yields a sane (non-zero) estimate.
FALLBACK_PRICE = ModelPrice(3.0, 15.0)


def price_for(model: str) -> ModelPrice:
    """Return the price entry for ``model``, falling back to FALLBACK_PRICE."""
    return MODEL_PRICES.get(model, FALLBACK_PRICE)


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost for one call's token usage.

    cost = prompt_tokens/1M * prompt_rate + completion_tokens/1M * completion_rate
    """
    price = price_for(model)
    prompt_cost = (prompt_tokens / _TOKENS_PER_MTOK) * price.prompt_usd_per_mtok
    completion_cost = (completion_tokens / _TOKENS_PER_MTOK) * price.completion_usd_per_mtok
    return prompt_cost + completion_cost
