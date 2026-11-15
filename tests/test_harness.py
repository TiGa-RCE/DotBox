"""Persistent starting controls use real core storage without launching a guest."""

from copy import deepcopy

import pytest

from dotbox.harness import HarnessLibrary


Project = pytest.importorskip("fdisbull.project").Project


def controls(*, name="playground", key="right"):
    return {
        "format": "fdisbull-macro-set-1",
        "name": name,
        "macros": {
            "move": {
                "authority": "player-input",
                "steps": [{"op": "keyboard.press", "key": key,
                           "hold_ms": 40, "gap_ms": 40}],
            },
        },
    }


@pytest.fixture
def project(tmp_path):
    program = tmp_path / "PLAY.COM"
    program.write_bytes(bytes.fromhex("b8 00 4c cd 21"))
    with Project.create(tmp_path / "play.fdb", program, image="com") as opened:
        yield opened


def test_controls_survive_project_reopen_without_redefinition(tmp_path):
    program = tmp_path / "PLAY.COM"
    program.write_bytes(bytes.fromhex("b8 00 4c cd 21"))
    path = tmp_path / "play.fdb"
    with Project.create(path, program, image="com") as project:
        library = HarnessLibrary(project)
        saved = library.save(controls())
        revision = saved["revision"]
        assert saved["id"] == revision
        assert library.save(deepcopy(controls()))["revision"] == revision
        assert len(library.list()["revisions"]) == 1

    with Project(path) as project:
        library = HarnessLibrary(project)
        info = library.info(revision)
        assert info["revision"] == revision
        assert info["definition"] == controls()
        assert info["binding"]["version_sha256"] == project.version(1)["sha256"]
        assert info["binding"]["source_sha256"] == project.source_binding_sha256(1)
        plan = library.plan(revision, "move")
        assert plan["revision"] == revision and plan["name"] == "move"
        assert plan["steps"] == [{"op": "key", "params": {
            "key": "right", "modifiers": [], "hold_ms": 40, "gap_ms": 40}}]
        assert plan["queued_guest_ms"] == 80
        assert library.list()["truncated"] is False


def test_explicit_old_revisions_and_sibling_branches_remain_usable(project):
    library = HarnessLibrary(project)
    original = library.save(controls())["revision"]
    left = library.save(controls(key="left"), parent=original)["revision"]
    up = library.save(controls(key="up"), parent=original)["revision"]

    assert len({original, left, up}) == 3
    assert library.info(original)["parent"] is None
    assert library.info(left)["parent"] == library.info(up)["parent"] == original
    for revision, expected in ((original, "right"), (left, "left"), (up, "up")):
        assert library.plan(revision, "move")["steps"][0]["params"]["key"] == expected
    assert {item["revision"] for item in library.list()["revisions"]} == {original, left, up}


def test_parent_must_exist_and_have_the_same_vocabulary_name(project):
    library = HarnessLibrary(project)
    original = library.save(controls())["revision"]
    before = library.list()
    with pytest.raises(ValueError):
        library.save(controls(name="other"), parent=original)
    with pytest.raises(ValueError):
        library.save(controls(key="left"), parent="0" * 64)
    assert library.list() == before


def test_persisted_row_from_another_source_is_not_accepted(tmp_path):
    first_program, second_program = tmp_path / "A.COM", tmp_path / "B.COM"
    first_program.write_bytes(bytes.fromhex("b8 00 4c cd 21"))
    second_program.write_bytes(bytes.fromhex("90 b8 00 4c cd 21"))
    with Project.create(tmp_path / "a.fdb", first_program, image="com") as first:
        revision = HarnessLibrary(first).save(controls())["revision"]
        # Deliberately contaminate a second project with a persisted metadata
        # row. This exercises the source binding check, rather than merely an
        # unknown-revision lookup, without adding an import API to DotBox.
        record = tuple(first.db.execute(
            "SELECT * FROM debug_macro_sets WHERE id=?", (revision,)).fetchone())
        with Project.create(tmp_path / "b.fdb", second_program, image="com") as second:
            with second.transaction(True):
                second.db.execute("INSERT INTO debug_macro_sets VALUES (?,?,?,?,?,?,?)", record)
            with pytest.raises(ValueError, match="binding|source|version"):
                HarnessLibrary(second).info(revision)


def test_unknown_revision_or_control_is_not_substituted(project):
    library = HarnessLibrary(project)
    revision = library.save(controls())["revision"]
    with pytest.raises(ValueError):
        library.info("0" * 64)
    with pytest.raises(ValueError):
        library.plan(revision, "unlearned")
    assert len(library.list()["revisions"]) == 1


@pytest.mark.parametrize("invalid_step", [
    {"op": "run", "guest_ms": 10},
    {"op": "memory", "address": 0, "size": 1},
    {"op": "keyboard.state"},
    {"op": "keyboard.key-down", "key": "left"},
    {"op": "macro", "name": "move"},
    {"op": "keyboard.press", "key": "$args.direction"},
    {"op": "keyboard.press", "key": "left", "as": "input"},
    {"op": "keyboard.press", "key": "left", "unexpected": True},
    {"op": "keyboard.press", "key": "left", "hold_ms": True},
    {"op": "keyboard.press", "key": "left", "gap_ms": 0},
    {"op": "keyboard.press", "key": "left", "modifiers": ["ctrl", "ctrl"]},
    {"op": "keyboard.type", "text": "not ASCII: \u2603"},
    {"op": "keyboard.type", "text": "$input.accepted"},
])
def test_invalid_later_step_rejects_the_whole_definition_before_saving(project, invalid_step):
    library = HarnessLibrary(project)
    definition = controls()
    definition["macros"]["move"]["steps"].append(invalid_step)
    with pytest.raises(ValueError):
        library.save(definition)
    assert library.list() == {"revisions": [], "truncated": False}


@pytest.mark.parametrize("change", [
    {"authority": "diagnostic"},
    {"authority": "authoring"},
    {"parameters": {"direction": {"type": "string"}}},
    {"outputs": {"accepted": "$input.accepted"}},
])
def test_runtime_parameters_outputs_and_other_authorities_are_not_starting_controls(project, change):
    library = HarnessLibrary(project)
    definition = controls()
    definition["macros"]["move"].update(change)
    with pytest.raises(ValueError):
        library.save(definition)
    assert not library.list()["revisions"]


def test_all_controls_are_validated_before_any_revision_is_saved(project):
    library = HarnessLibrary(project)
    definition = controls()
    definition["macros"]["later"] = {
        "steps": [{"op": "keyboard.type", "text": "\x00"}],
    }
    with pytest.raises(ValueError):
        library.save(definition)
    assert not library.list()["revisions"]


@pytest.mark.parametrize("changed", [
    {"authority": "diagnostic"},
    {"steps": [{"op": "memory", "address": 0, "size": 1}]},
    {"steps": [{"op": "keyboard.press", "key": "right", "hold_ms": 600, "gap_ms": 600}]},
])
def test_general_core_macro_records_cannot_bypass_the_play_facade(project, changed):
    library = HarnessLibrary(project)
    supported = library.save(controls())["revision"]
    definition = controls(name="general_debugger")
    definition["macros"]["move"].update(changed)
    # Existing fDisBull projects can contain a broader, valid macro vocabulary.
    # Selecting that known immutable ID must still enforce DotBox's smaller
    # policy at use time, rather than trusting that only save() created it.
    general = project.debug_define_macros(definition, version=1, author="other-tool")["id"]
    with pytest.raises(ValueError):
        library.info(general)
    with pytest.raises(ValueError):
        library.plan(general, "move")
    assert {item["revision"] for item in library.list()["revisions"]} == {supported}


def test_step_limit_is_per_expanded_control(project):
    library = HarnessLibrary(project)
    definition = controls()
    definition["macros"]["move"]["steps"] = [
        {"op": "keyboard.press", "key": "right", "hold_ms": 1, "gap_ms": 1}
        for _ in range(16)
    ]
    revision = library.save(definition)["revision"]
    assert len(library.plan(revision, "move")["steps"]) == 16
    definition["macros"]["move"]["steps"].append(
        {"op": "keyboard.press", "key": "right", "hold_ms": 1, "gap_ms": 1})
    with pytest.raises(ValueError):
        library.save(definition, parent=revision)
    assert len(library.list()["revisions"]) == 1


def test_text_character_count_contributes_to_total_duration(project):
    library = HarnessLibrary(project)
    definition = controls()
    definition["macros"]["move"]["steps"] = [
        {"op": "keyboard.press", "key": "right", "hold_ms": 200, "gap_ms": 200},
        {"op": "keyboard.type", "text": "abc", "hold_ms": 100, "gap_ms": 100},
    ]
    revision = library.save(definition)["revision"]
    assert library.plan(revision, "move")["queued_guest_ms"] == 1000
    definition["macros"]["move"]["steps"][1]["text"] = "abcd"
    with pytest.raises(ValueError):
        library.save(definition, parent=revision)
    assert len(library.list()["revisions"]) == 1


def test_separate_controls_have_separate_duration_budgets(project):
    library = HarnessLibrary(project)
    definition = controls()
    definition["macros"] = {
        name: {"steps": [{"op": "keyboard.press", "key": key,
                          "hold_ms": 350, "gap_ms": 350}]}
        for name, key in (("move_left", "left"), ("move_right", "right"))
    }
    revision = library.save(definition)["revision"]
    assert library.plan(revision, "move_left")["queued_guest_ms"] == 700
    assert library.plan(revision, "move_right")["queued_guest_ms"] == 700


def test_control_count_limit_rejects_excess_without_changing_stored_revisions(project):
    library = HarnessLibrary(project)
    definition = controls()
    definition["macros"] = {
        f"move_{index}": {"steps": [{"op": "keyboard.press", "key": "right"}]}
        for index in range(32)
    }
    revision = library.save(definition)["revision"]
    definition["macros"]["too_many"] = {
        "steps": [{"op": "keyboard.press", "key": "right"}],
    }
    with pytest.raises(ValueError):
        library.save(definition, parent=revision)
    assert len(library.info(revision)["definition"]["macros"]) == 32
    assert len(library.list()["revisions"]) == 1
