"""Bounds for prose and world creation; historical records retain their limits."""

MAX_PROSE = 16000
MAX_RESPONSE_BYTES = 256 * 1024

# Genesis includes structured places, actors and items, plus model reasoning.
WORLD_OUTPUT_TOKENS = 65536
WORLD_TIMEOUT_MS = 15 * 60 * 1000
MAX_WORLD_RESPONSE_BYTES = 2 * 1024 * 1024
