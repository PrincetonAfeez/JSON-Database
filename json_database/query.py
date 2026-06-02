"""Small query evaluator for collection documents."""

from __future__ import annotations

from typing import Any, Callable

from .errors import QueryError


OPERATORS = frozenset(
    {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte", "$in", "$nin", "$contains", "$exists"}
)


def matches(document: dict[str, Any], criteria: dict[str, Any] | None) -> bool:
    if criteria is None:
        return True
    if not isinstance(criteria, dict):
        raise QueryError("query criteria must be an object")
    for field, expected in criteria.items():
        if not isinstance(field, str):
            raise QueryError("query fields must be strings")
        exists = field in document
        actual = document.get(field)
        if _is_operator_expression(expected):
            if not _matches_operators(actual, exists, expected):
                return False
        elif not exists or actual != expected:
            return False
    return True


def filter_documents(documents: list[dict[str, Any]], criteria: dict[str, Any] | None) -> list[dict[str, Any]]:
    if criteria is not None:
        # Validate operator syntax even when no documents would match.
        matches({}, criteria)
    return [document for document in documents if matches(document, criteria)]


def run_predicate(documents: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    if not callable(predicate):
        raise QueryError("predicate query requires a callable")
    results = []
    for document in documents:
        try:
            if predicate(document):
                results.append(document)
        except Exception as exc:
            raise QueryError(f"predicate query failed: {exc}") from exc
    return results


def _is_operator_expression(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    op_keys = [key for key in value if isinstance(key, str) and key.startswith("$")]
    if not op_keys:
        return False
    if len(op_keys) != len(value):
        raise QueryError(
            "query expression may not mix operators with field names "
            f"(saw operators {sorted(op_keys)} mixed with other keys)"
        )
    return True


def _matches_operators(actual: Any, exists: bool, expression: dict[str, Any]) -> bool:
    for operator, expected in expression.items():
        if operator not in OPERATORS:
            raise QueryError(
                f"unsupported query operator: {operator} "
                f"(supported: {sorted(OPERATORS)})"
            )
        if operator == "$exists":
            if bool(expected) != exists:
                return False
            continue
        if operator == "$ne":
            # A missing field "doesn't equal" anything — match it.
            if exists and actual == expected:
                return False
            continue
        if operator == "$nin":
            if not isinstance(expected, list):
                raise QueryError("$nin expects a list")
            # A missing field is in no list of values — match it.
            if exists and actual in expected:
                return False
            continue
        if not exists:
            return False
        if operator == "$eq" and actual != expected:
            return False
        if operator == "$gt" and not _compare(actual, expected, lambda a, b: a > b):
            return False
        if operator == "$gte" and not _compare(actual, expected, lambda a, b: a >= b):
            return False
        if operator == "$lt" and not _compare(actual, expected, lambda a, b: a < b):
            return False
        if operator == "$lte" and not _compare(actual, expected, lambda a, b: a <= b):
            return False
        if operator == "$in":
            if not isinstance(expected, list):
                raise QueryError("$in expects a list")
            if actual not in expected:
                return False
        if operator == "$contains":
            try:
                if expected not in actual:
                    return False
            except TypeError:
                return False
    return True


def _compare(actual: Any, expected: Any, compare) -> bool:
    try:
        return bool(compare(actual, expected))
    except TypeError:
        return False
