import pytest

import record


def test_flatten_nested_dicts():
    item = {"a": 1, "b": {"c": 2, "d": {"e": 3}}, "l": [1, 2]}
    assert record.__flatten(item) == {"a": 1, "b_c": 2, "b_d_e": 3, "l": [1, 2]}


def test_no_include_exclude_flattens_everything():
    assert record.__filter_columns([{"a": {"b": 1}}]) == [{"a_b": 1}]


def test_include_top_level_and_nested():
    item = {"id": 1, "x": 2, "post": {"title": "t", "body": "b"}, "meta": {"k": 1}}
    spec = ["id", {"post": ["title"]}, "meta"]
    assert record.__filter_columns([item], include=spec) == [{"id": 1, "post_title": "t", "meta_k": 1}]


def test_exclude_top_level_and_nested():
    item = {"id": 1, "x": 2, "post": {"title": "t", "body": "b"}}
    spec = ["x", {"post": ["body"]}]
    assert record.__filter_columns([item], exclude=spec) == [{"id": 1, "post_title": "t"}]


def test_exclude_wins_over_include():
    item = {"a": 1, "b": 2}
    assert record.__filter_columns([item], include=["a"], exclude=["b"]) == [{"a": 1}]


@pytest.fixture
def thread():
    return {"parents": [{"id": 1, "who": "a"}, {"id": 2, "who": "b"}, {"id": 3, "who": "c"}]}


def test_list_selector_first_and_last(thread):
    spec = [{"parents": [{"[first]": ["id"]}, {"[last]": ["id", "who"]}]}]
    assert record.__traverse(thread, spec) == {
        "parents_first_id": 1,
        "parents_last_id": 3,
        "parents_last_who": "c",
    }


def test_list_selector_index_and_negative_index(thread):
    spec = [{"parents": [{"[1]": ["id"]}, {"[-3]": ["id"]}]}]
    assert record.__traverse(thread, spec) == {"parents_1_id": 2, "parents_0_id": 1}


def test_list_selector_star_takes_all(thread):
    spec = [{"parents": [{"[*]": ["id"]}]}]
    assert record.__traverse(thread, spec) == {"parents_0_id": 1, "parents_1_id": 2, "parents_2_id": 3}


def test_list_selector_without_subspec_keeps_element(thread):
    spec = [{"parents": ["[last]"]}]
    assert record.__traverse(thread, spec) == {"parents_last_id": 3, "parents_last_who": "c"}


def test_list_selector_on_empty_list_or_out_of_range_is_skipped():
    spec = [{"parents": [{"[first]": ["id"]}, {"[last]": ["id"]}, {"[5]": ["id"]}]}]
    assert record.__traverse({"parents": []}, spec) == {}
    assert record.__traverse({"parents": [{"id": 1}]}, [{"parents": [{"[5]": ["id"]}]}]) == {}


def test_list_selector_must_be_bracketed(thread):
    with pytest.raises(ValueError, match="bracketed"):
        record.__traverse(thread, [{"parents": [{"last": ["id"]}]}])


def test_list_selector_on_a_dict_value_is_an_error():
    with pytest.raises(ValueError, match=r"'\[last\]' under post: value is not a list"):
        record.__traverse({"post": {"id": 1}}, [{"post": [{"[last]": ["id"]}]}])


def test_list_selector_as_a_string_on_a_dict_value_is_an_error():
    with pytest.raises(ValueError, match="not a list"):
        record.__traverse({"post": {"id": 1}}, [{"post": ["[last]"]}])


def test_list_selector_in_exclude_is_an_error(thread):
    with pytest.raises(ValueError, match="only supported in include"):
        record.__traverse(thread, [{"parents": [{"[last]": ["id"]}]}], mode="exclude")


def test_exclude_inside_a_list_is_an_error(thread):
    with pytest.raises(ValueError, match="exclude cannot look inside the list 'parents'"):
        record.__traverse(thread, [{"parents": ["id"]}], mode="exclude")


def test_exclude_whole_list_key_still_works(thread):
    assert record.__traverse({**thread, "keep": 1}, ["parents"], mode="exclude") == {"keep": 1}


def test_absent_keys_in_spec_are_skipped_silently():
    assert record.__traverse({"a": 1}, ["a", "missing", {"nope": ["x"]}]) == {"a": 1}
    assert record.__traverse({"a": 1, "b": 2}, ["missing", {"nope": ["x"]}], mode="exclude") == {"a": 1, "b": 2}


def test_plain_key_named_last_is_not_a_selector():
    assert record.__traverse({"last": 7, "x": 1}, ["last"]) == {"last": 7}


def test_filter_keeps_matching_items_only():
    items = [{"type": "post", "id": 1}, {"type": "comment", "id": 2}]
    assert record.filter_items(items, {"filter": [{"type": "comment"}]}) == [{"type": "comment", "id": 2}]


def test_filter_conditions_are_anded():
    items = [{"type": "c", "lang": "en"}, {"type": "c", "lang": "uk"}, {"type": "p", "lang": "en"}]
    result = record.filter_items(items, {"filter": [{"type": "c"}, {"lang": "en"}]})
    assert result == [{"type": "c", "lang": "en"}]


def test_null_and_empty_string_values_are_dropped():
    items = [{"a": 1, "b": None, "c": "", "d": {"e": None, "f": "x"}}]
    assert record.filter_items(items, {}) == [{"a": 1, "d_f": "x"}]


def test_zero_false_and_empty_containers_are_kept():
    items = [{"n": 0, "flag": False, "lst": [], "txt": " "}]
    assert record.filter_items(items, {}) == [{"n": 0, "flag": False, "lst": [], "txt": " "}]


def test_empty_values_are_dropped_after_include_and_exclude():
    items = [{"id": 1, "x": None, "y": None}]
    assert record.filter_items(items, {"include": ["id", "x"]}) == [{"id": 1}]
    assert record.filter_items(items, {"exclude": ["y"]}) == [{"id": 1}]


def test_filter_runs_before_column_selection():
    items = [{"type": "c", "id": 1}, {"type": "p", "id": 2}]
    endpoint = {"filter": [{"type": "p"}], "include": ["id"]}
    assert record.filter_items(items, endpoint) == [{"id": 2}]


def test_columns_name_positional_rows():
    rows = [["2026/10/20", 5], ["2026/10/21", 7]]
    assert record.filter_items(rows, {"columns": ["date", "followers"]}) == [
        {"date": "2026/10/20", "followers": 5},
        {"date": "2026/10/21", "followers": 7},
    ]


def test_delta_is_change_versus_previous_row():
    rows = [["d1", 5], ["d2", 7], ["d3", 6]]
    endpoint = {"columns": ["date", "n"], "delta": "n", "sort_key": "date"}
    assert [r.get("n_delta") for r in record.filter_items(rows, endpoint)] == [None, 2, -1]


def test_delta_is_computed_in_ascending_order_of_sort_key():
    rows = [["d3", 6], ["d1", 5], ["d2", 7]]
    endpoint = {"columns": ["date", "n"], "delta": "n", "sort_key": "date"}
    result = {r["date"]: r.get("n_delta") for r in record.filter_items(rows, endpoint)}
    assert result == {"d1": None, "d2": 2, "d3": -1}
