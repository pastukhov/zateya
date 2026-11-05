# Screen renderer previews

Run from the repository root:

```sh
python3 firmware/tools/render-screen-previews.py /tmp/zateya-screen-previews
```

Requires a host C compiler, Python and Pillow. The tool compiles the production
renderer and generates thirty-two logical and thirty-two physical PPM frames plus `contact-sheet.png`
and `physical-sheet.png`: recording,
error, setup QR, OTA and four ready variants in all four logical orientations.
`idle` matches the default toggle-button screen; `idle-hold`, `idle-wake` and
`idle-wake-hold` cover hold mode and the actual wake hint selected by the board.
A failed render
exits nonzero. The comparison sheet is reconstructed from physical frames using inverse rotation;
the generator verifies byte equality to logical frames. Physical transform corners
and pixel bijection are also covered by native tests.

Smoke test: `sh firmware/tools/tests/screen-previews-smoke.sh`.
