# Button modes in recorder settings

Goal: choose manual toggle or hold behavior in the existing local web interface.

1. Add test-first settings, form and public-status coverage: toggle default,
   NVS byte normalization, strict toggle/hold form values, public mode name.
2. Extend the hardware-independent capture policy with a mode snapshot at
   activation. Hold ignores silence, finishes on release and cancels release
   before speech; toggle finishes on next press or configured silence. Maximum
   duration remains active. Wake/follow-up always use VAD/toggle behavior.
3. Persist the mode in existing NVS namespace and wire manual/wake/follow-up
   starts to the tested policy. Keep cue/drain, ownership and cancellation.
4. Add a select with mode explanations, load/save validation and UI behavior
   tests. Document hold cue/release semantics and pause configuration.
5. Run targeted native/Node checks and diff validation. Parent independently
   runs complete native/target checks, reviews, commits/pushes and releases.

No partition, credential or production changes. Invalid persisted/absent mode
uses toggle; invalid form is rejected. Preserve unrelated untracked files.
