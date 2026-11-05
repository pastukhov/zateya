# Screen renderer previews

Run from the repository root:

```sh
python3 firmware/tools/render-screen-previews.py /tmp/zateya-screen-previews
```

Requires a host C compiler, Python and Pillow. The tool compiles the production
renderer and generates twenty logical and twenty physical PPM frames plus `contact-sheet.png`
and `physical-sheet.png`: recording,
error, setup QR, OTA and idle in all four logical orientations. A failed render
exits nonzero. The comparison sheet is reconstructed from physical frames using inverse rotation;
the generator verifies byte equality to logical frames. Physical transform corners
and pixel bijection are also covered by native tests.

Smoke test: `sh firmware/tools/tests/screen-previews-smoke.sh`.
