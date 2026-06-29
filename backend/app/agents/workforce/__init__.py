__all__ = ["answer_workforce_query"]


def __getattr__(name: str):
    if name == "answer_workforce_query":
        from app.agents.workforce.query_handler import answer_workforce_query

        return answer_workforce_query
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
