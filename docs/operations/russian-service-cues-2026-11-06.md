# Russian service cue pronunciation, 2026-11-06

## Selection and acceptance boundary

Production31 audibility had been confirmed. User then reported English accent
in service cues, especially «Готово». Talia/Flash+ru remained accented; native
Russian Marina/Flash+ru removed accent but yielded unclear phrases and wrong
stress in «Не дождалась ответа». At the user's suggestion to change generation
mode, four individually synthesized Marina/Multilingual v2 cues were accepted:
«Готово», «Не дождалась ответа», «Готова к записи», «Обрабатываю».
Remaining ten clips were generated in the same mode. The exact four accepted
MP3 files were retained, not regenerated. A concatenated WAV was used only for
listening preview; production delivery preserves original provider MP3 bytes.

Current profile: `MP3_TTS_MODEL=elevenlabs/eleven-multilingual-v2`,
`MP3_TTS_VOICE=ymDCYd8puC7gYjxIamPt` (Marina), empty language and instructions.
Both cues and dynamic replies keep the established shared profile architecture.
This supersedes the earlier Talia/Flash selection explicitly; female voice and
MP3 delivery remain. No cue text, firmware, partition or device configuration
changed. Language override remains empty because this was the accepted request.

## Code and tests

Optional two-letter language support was implemented by Sol, independently
reviewed by parent, committed/pushed as575ac10. The RouterAI mapping is
`provider.options.elevenlabs.language_code`; unset leaves old payloads and cache
IDs exactly unchanged. Historical profiles continue resolving; nonempty language
participates in identity. This capability alone did not fix pronunciation.

Twenty new regressions failed before implementation; focused111 passed. Parent
full backend/deploy run:901 passed,15 subtests passed, one unrelated nginx
integration test failed502 because its mock backend was not ready. The same
proxy assertions passed when explicitly waiting for mock-backend readiness;
no proxy code/test change was included. Independently built Python3.12 runtime
image passed all341 TTS/cue tests with network disabled. Diffcheck passed.

## Deployment and artifact verification

Server `/opt/zateya` history is divergent; exact575ac10 patch applied as98481b9.
Built unique image `zateya-voice-gateway:russian-cues-575ac10` on prior immutable
77f0d642 base with only four changed runtime modules. Actual running image:
`sha256:b1618d7b80db0b26a40bcab50ef11555fd51815d5ecbc1857d0c64e1390b73bb`.
Only backend recreated; no active voice jobs at the checkpoint, proxy unchanged.
The new container is healthy. Legacy Gemini/Kore settings remain unchanged.

New generation:
`667fadd41d6bcc9b1f53492c9b09bef723090eb64cdbe63a709c44c2ee6728cf`.
Fourteen files,336219bytes, mono44.1kHz/128kbps MP3, all strict decode/size/hash
checks passed. Generation was assembled offline with network disabled and a
provider that raises on any synthesis attempt: reviewed bytes cannot silently
change. Complete directory was imported before restart; normal generation
activation published it. Old generation81042c98 remains retained for in-flight
or not-yet-updated devices. All14 externally authenticated downloads matched
manifest SHA/size and strict decoding. The server subsequently logged28 successful
MP3 bodies:14 verifier downloads and14 recorder downloads.

Device boot_id1696564695 remains unchanged, backendHTTP200, no reset/OTA needed.
Activation is confirmed by job5944555a-5d9c-4797-9e92-3625e0b30f73, created
2026-11-05T21:43:15.067+00:00: ready, MP3, new cue_generation667fadd41d6b…728cf.
User confirmed «Реплики хорошие, без акцента, но с помехами. Сейчас пришлю запись».
Pronunciation is accepted on the recorder; playback interference is open. Do not
claim overall audio quality is fixed. No further voice/model change is planned.
Passive log `/tmp/zateya-russian-cues-install.log` captures this update.

## Rollback

Previous model/voice: elevenlabs/eleven-flash-v2.5 / OZ0L6eISlOejga3XjDFt,
empty language. Previous complete generation:
`81042c98c112af01d967432c9ad20c1740a99dd69b5f72f31dd8cf239af2f5fd`.
Previous runtime image:
`sha256:77f0d6423f9f8ccfa083b56e9c29e088c577d82aa062eae79e77678f7f79a309`.
Do not erase cache; restoring prior settings lets normal complete-generation
selection restore it. Firmware remains installed and confirmed OTA31.

Provider references: [RouterAI TTS](https://routerai.ru/docs/guides/overview/multimodal/text-to-speech),
[ElevenLabs Russian voices](https://elevenlabs.io/text-to-speech/russian).

## Next task: interference during playback

User will supply a recording. Preserve Marina/Multilingual v2 and inspect that
recording before proposing a firmware fix. USB log has repeated i2s_channel_disable
messages during playback/capture transitions, but these alone do not establish
the interference cause. No decoder failure or deferred generation was logged.
Offline decoding of the accepted done/timeout/processing clips had zero clipped
PCM16 samples; peak levels -6.36/-8.46/-1.22dBFS respectively. This rules out
full-scale PCM clipping in these source files, not device amplifier distortion or
playback gaps. No playback-related implementation change or firmware release yet.
