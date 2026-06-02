"""Test query functionality."""

import pytest

from json_database import Database, OPERATORS
from json_database.errors import QueryError


def test_equality_and_operator_queries(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava", "age": 31, "active": True, "tags": ["python", "db"]})
    users.insert({"name": "Mia", "age": 17, "active": False, "tags": ["web"]})

    assert [doc["name"] for doc in users.find({"active": True})] == ["Ava"]
    assert [doc["name"] for doc in users.find({"age": {"$gt": 18}})] == ["Ava"]
    assert [doc["name"] for doc in users.find({"name": {"$in": ["Mia"]}})] == ["Mia"]
    assert [doc["name"] for doc in users.find({"tags": {"$contains": "python"}})] == ["Ava"]
    # Documents are stored under UUID keys and the on-disk JSON sorts keys,
    # so the iteration order is UUID-sorted (effectively random per run).
    assert sorted(doc["name"] for doc in users.find({"email": {"$exists": False}})) == ["Ava", "Mia"]


def test_predicate_queries_and_errors(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava", "age": 31})
    users.insert({"name": "Mia", "age": 17})

    assert [doc["name"] for doc in users.where(lambda doc: doc["age"] > 18)] == ["Ava"]

    with pytest.raises(QueryError):
        users.where(lambda doc: doc["missing"]["boom"])


def test_unknown_operator_raises(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"age": 20})

    with pytest.raises(QueryError) as exc:
        users.find({"age": {"$near": 20}})
    assert "supported" in str(exc.value)


def test_ne_matches_missing_field(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava", "age": 31})
    users.insert({"name": "Mia"})  # no age

    names = sorted(doc["name"] for doc in users.find({"age": {"$ne": 31}}))
    assert names == ["Mia"]


def test_mixed_operator_and_field_keys_raise(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"age": 31, "other": 9})

    with pytest.raises(QueryError, match="may not mix operators with field names"):
        users.find({"age": {"$gt": 5, "other": 9}})


def test_in_rejects_non_list(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"role": "admin"})

    with pytest.raises(QueryError, match=r"\$in expects a list"):
        users.find({"role": {"$in": ("admin", "editor")}})


def test_operators_exported():
    assert OPERATORS == frozenset(
        {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte", "$in", "$nin", "$contains", "$exists"}
    )


def test_explicit_comparison_and_exists_operators(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava", "age": 31, "score": 90})
    users.insert({"name": "Mia", "age": 17, "score": 70})

    assert [doc["name"] for doc in users.find({"age": {"$eq": 31}})] == ["Ava"]
    assert [doc["name"] for doc in users.find({"age": {"$gte": 18}})] == ["Ava"]
    assert [doc["name"] for doc in users.find({"age": {"$lt": 18}})] == ["Mia"]
    assert [doc["name"] for doc in users.find({"score": {"$lte": 70}})] == ["Mia"]
    assert [doc["name"] for doc in users.find({"email": {"$exists": True}})] == []


def test_multi_field_and_query(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava", "age": 31, "active": True})
    users.insert({"name": "Mia", "age": 31, "active": False})

    assert [doc["name"] for doc in users.find({"active": True, "age": {"$gt": 18}})] == ["Ava"]


def test_contains_on_non_container_returns_no_match(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava", "age": 31})

    assert users.find({"age": {"$contains": 3}}) == []


def test_comparison_on_incompatible_types_returns_no_match(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava", "score": "high"})

    assert users.find({"score": {"$gt": 10}}) == []


def test_query_validates_criteria_on_empty_collection(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")

    with pytest.raises(QueryError, match="supported"):
        users.find({"age": {"$near": 20}})


def test_nin_matches_missing_field_and_excludes_listed_values(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava", "role": "admin"})
    users.insert({"name": "Mia", "role": "editor"})
    users.insert({"name": "Noah"})  # no role

    names = sorted(doc["name"] for doc in users.find({"role": {"$nin": ["admin"]}}))
    assert names == ["Mia", "Noah"]


def test_nin_rejects_non_list(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"role": "admin"})

    with pytest.raises(QueryError, match=r"\$nin expects a list"):
        users.find({"role": {"$nin": ("admin",)}})


def test_query_rejects_non_dict_criteria(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava"})

    with pytest.raises(QueryError, match="must be an object"):
        users.find(["name"])


def test_query_rejects_non_string_field_keys(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava"})

    with pytest.raises(QueryError, match="fields must be strings"):
        users.find({1: "Ava"})


def test_plain_null_does_not_match_missing_field(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava"})

    assert users.find({"email": None}) == []


def test_contains_on_dict_keys(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"meta": {"k": 1, "j": 2}})

    assert [doc["meta"] for doc in users.find({"meta": {"$contains": "k"}})] == [{"k": 1, "j": 2}]


def test_contains_on_string_is_substring(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "python"})

    assert users.find({"name": {"$contains": "yth"}}) != []
    assert users.find({"name": {"$contains": "java"}}) == []


def test_where_rejects_non_callable_predicate(tmp_path):
    users = Database(tmp_path / "app.jsondb").collection("users")
    users.insert({"name": "Ava"})

    with pytest.raises(QueryError, match="requires a callable"):
        users.where("not callable")
