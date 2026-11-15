# Persistent starting controls

This development slice saves a small learned keyboard vocabulary once and
reuses it across client connections and service restarts. It uses fDisBull's
existing immutable macro records in the same project database, with the original
executable/mapped-byte bindings. No new harness serialization or replacement
game is introduced.

This is the controls foundation of bounded preparation. It does not perform
autonomous discovery, recognize scenes, read an AGI interpreter or prepare a
complete starting Z buffer. The supplied vocabulary is explicitly authored for
the [input playground](../examples/input_playground.py), not a commercial game.
Resource-tree compatibility is not established by the executable binding.

## Prepare once

Start the [play service](PLAYABLE_SLICE.md) with the authored playground and a
compatible ownership-enabled DOSBox-X. In another tool call, observe its lease
and save the supplied left/right vocabulary:

```sh
python -m dotbox status --session /private/work/dotbox-session/session.json > /private/work/status.json
python -m dotbox harness-save \
  --definition /path/to/DotBox/examples/playground_controls.json \
  --session /private/work/dotbox-session/session.json \
  --lease /private/work/status.json > /private/work/controls.json
```

The result includes `result.revision`, a stable immutable ID. Saving the same
definition/parent again reuses its record. Saving only changes metadata: it
does not pause, resume or inject input, including when the human owns the game.
The request still needs a current service-instance/ownership lease.

Use the revision returned by that save explicitly below:

```sh
python -m dotbox harness-list --session /private/work/dotbox-session/session.json
python -m dotbox harness-info '<revision-id>' --session /private/work/dotbox-session/session.json
python -m dotbox control agent --resume \
  --session /private/work/dotbox-session/session.json \
  --lease /private/work/controls.json > /private/work/agent.json
python -m dotbox act '<revision-id>' move_left \
  --session /private/work/dotbox-session/session.json \
  --lease /private/work/agent.json
```

The action requires a running guest, current agent ownership and a fresh lease.
It never silently resumes a paused game. Accepted/queued input is not proof
that the game completed the intended interaction; observe a new frame to verify
the outcome. Built-in desktop takeover remains separate from this development
service's explicit native ownership.

## Add the next useful control

Edit an authored JSON vocabulary using `fdisbull-macro-set-1`, then save it with
`--parent '<previous-revision-id>'`. This creates an immutable child revision;
it does not change an active head or rewrite previous work. Explicit sibling
branches are allowed. Every action selects the intended revision, so an older
usable vocabulary remains available after a new discovery.

Only fixed `player-input` keyboard.press and keyboard.type steps are admitted.
The limits are 32 controls per vocabulary, 16 steps and 1,000 ms of queued input
per control, and a 48 KiB definition. Text duration counts every character.
Runtime parameters, symbolic references, held-key leases, nested macros,
general debug scripts, memory operations and executable plugins are excluded.
Validation covers the whole vocabulary before saving and the complete selected
plan before its first input. Other tools' broader macro records cannot bypass
the smaller DotBox facade.

Each admitted step uses the existing ownership-aware backend primitive, including
native generation in the actual input RPC. One shared one-second RPC budget
bounds the composed action. A failure after earlier input returns
`action_interrupted` with acknowledged steps and the active step; effects may
already exist and are neither replayed nor claimed rolled back. Reobserve the
game before deciding what to do next.

## Reopen without rediscovery

Explicitly close the service, then start another service using the same project.
List/show the stored revision and execute it with the new service's lease.
The native game starts again; this slice retains learned controls, not a native
checkpoint. A lease from the old service is refused. Game checkpoint selection,
community package composition/import and complete scene preparation remain
later gates. Existing fDisBull exporters remain reusable foundations for sharing.

The local native acceptance demonstrates metadata authoring in human-control
mode, movement through a named action, another client reusing it, an incremental
revision preserving the earlier vocabulary, and reuse after full owner/guest
shutdown. See [verification](VERIFICATION_CONTROL_REUSE.md).
