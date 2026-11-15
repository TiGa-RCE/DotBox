"""Small persisted control vocabularies in fDisBull's existing macro store.

Every use selects an immutable revision explicitly. There is no implicit latest
revision, executable plugin, automatic discovery, or certified game outcome.
"""

import json
import re


MAX_CONTROLS = 32
MAX_STEPS = 16
MAX_QUEUED_MS = 1000
MAX_DEFINITION_BYTES = 48 * 1024


class ActionInterrupted(RuntimeError):
    """Some input may have been accepted; preserve progress without replay."""

    def __init__(self, revision, name, completed_steps, active_step, cause):
        super().__init__(str(cause)[:500])
        self.progress = {
            "revision": revision, "name": name,
            "completed_steps": completed_steps, "active_step": active_step,
            "outcome": "unknown; input may have been accepted",
            "effects": "not replayed or rolled back; observe before continuing",
        }


def _revision(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Expected an immutable control revision ID")
    return value


class HarnessLibrary:
    def __init__(self, project, *, version=1, validate_keyboard=None):
        from fdisbull.input_macros import expand_macro, validate_macro_set
        if validate_keyboard is None:
            from fdisbull.keyboard_input import validate_keyboard
        self.project = project
        self.version = version
        self.validate_keyboard = validate_keyboard
        self._expand = expand_macro
        self._validate = validate_macro_set

    def _steps(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise ValueError(f"Controls require 1..{MAX_STEPS} input steps")
        result, queued = [], 0
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("Each control step must be an object")
            op = step.get("op")
            if op == "keyboard.press":
                allowed, required, method = {"op", "key", "modifiers", "hold_ms", "gap_ms"}, "key", "key"
            elif op == "keyboard.type":
                allowed, required, method = {"op", "text", "hold_ms", "gap_ms"}, "text", "type"
            else:
                raise ValueError("Controls support only keyboard.press and keyboard.type")
            if set(step) - allowed or required not in step:
                raise ValueError("Unsupported or missing control step fields")
            params = {key: value for key, value in step.items() if key != "op"}
            params.setdefault("hold_ms", 40)
            params.setdefault("gap_ms", 40)
            for field in ("hold_ms", "gap_ms"):
                if type(params[field]) is not int or not 1 <= params[field] <= 1000:
                    raise ValueError(f"{field} must be an integer in 1..1000")
            if not isinstance(params[required], str) or params[required].startswith("$"):
                raise ValueError("Control input must be literal, without symbolic references")
            if method == "key":
                params.setdefault("modifiers", [])
            self.validate_keyboard(**params)
            count = len(params["text"]) if method == "type" else 1
            queued += count * (params["hold_ms"] + params["gap_ms"])
            if queued > MAX_QUEUED_MS:
                raise ValueError(f"Control exceeds {MAX_QUEUED_MS} ms queued-input budget")
            result.append({"op": method, "params": params})
        return result, queued

    def _definition(self, definition):
        encoded = json.dumps(definition, allow_nan=False).encode()
        if len(encoded) > MAX_DEFINITION_BYTES:
            raise ValueError("Control vocabulary exceeds 48 KiB")
        doc = self._validate(definition)
        if len(doc["macros"]) > MAX_CONTROLS:
            raise ValueError(f"Control vocabulary exceeds {MAX_CONTROLS} controls")
        for macro in doc["macros"].values():
            if (macro.get("authority", "player-input") != "player-input"
                    or macro.get("parameters") or macro.get("outputs")):
                raise ValueError("Controls require fixed player-input steps without parameters or outputs")
            self._steps(macro["steps"])
        return doc

    @staticmethod
    def _summary(info):
        return {
            "revision": info["id"], "name": info["definition"]["name"],
            "parent": info["parent"], "binding": info["binding"],
            "controls": sorted(info["definition"]["macros"]),
            "claim": "Authored controls; input delivery is not verified game progress",
            "binding_scope": "executable and mapped bytes; game resources not inventoried",
        }

    def save(self, definition, *, parent=None):
        doc = self._definition(definition)
        if parent is not None:
            previous = self.info(_revision(parent))
            if previous["definition"]["name"] != doc["name"]:
                raise ValueError("Parent must belong to the same control vocabulary")
        info = self.project.debug_define_macros(
            doc, version=self.version, author="dotbox", parent=parent)
        return {**self._summary(info), "id": info["id"]}

    def info(self, revision):
        info = self.project.debug_macro_info(_revision(revision), version=self.version)
        self._definition(info["definition"])
        return {**info, **self._summary(info)}

    def list(self):
        # Use the core's records and validation rather than another manifest or
        # active-head store. Explicit IDs also preserve deliberate branches.
        infos = self.project.debug_macro_sets(version=self.version)["macro_sets"]
        rows, admitted = [], 0
        for info in reversed(infos):
            try:
                self._definition(info["definition"])
            except ValueError:
                continue  # General debugger macros are outside this small facade.
            admitted += 1
            if len(rows) < 64:
                rows.append(self._summary(info))
        return {"revisions": rows, "truncated": admitted > len(rows)}

    def plan(self, revision, name):
        info = self.info(revision)
        if not isinstance(name, str) or name not in info["definition"]["macros"]:
            raise ValueError("Unknown control in selected revision")
        expanded = self._expand(info["definition"], name, allowed_authorities=("player-input",))
        steps, queued = self._steps(expanded["script"]["steps"])
        return {"revision": info["id"], "name": name, "steps": steps,
                "queued_guest_ms": queued}
