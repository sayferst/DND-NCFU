"""Shared normalisation for the small, explicitly supported command set."""


def normalise_action(action: str) -> str:
    return " ".join(action.casefold().split()).rstrip(".!?")
