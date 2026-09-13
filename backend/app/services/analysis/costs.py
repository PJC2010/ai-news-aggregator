"""Conservative peak-rate estimates, not a provider invoice or exact tokenizer."""

PRICING_VERSION = "deepseek-peak-usd-2026-09-13"
PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
# USD per million tokens: cache hit, cache miss, output. Off-peak can cost less.
RATES = {
    "deepseek-flash": (0.006, 0.30, 1.20),
    "deepseek-v4-pro": (0.044, 1.32, 3.96),
}


def estimate_cost(model, input_tokens, cached_input_tokens, output_tokens):
    hit, miss, output = RATES[model]
    return (
        cached_input_tokens * hit
        + (input_tokens - cached_input_tokens) * miss
        + output_tokens * output
    ) / 1_000_000


def reserve_cost(model, messages, max_tokens):
    # UTF-8 bytes plus conservative chat-envelope overhead overestimate input
    # tokens for this byte-pair tokenizer. Output is bounded by max_tokens.
    input_bound = sum(len(message["content"].encode()) + 256 for message in messages) + 2048
    return estimate_cost(model, input_bound, 0, max_tokens)
