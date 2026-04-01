
# build log topics

Planned content:

- component selection
- wiring revisions
- prototype photos
- esphome revisions
- measurement validation

## Prototyping screen

Remarks encountered during prototyping the screen

- The screen resolution is larger than advertised. It was sold as 240×280, but it is actually 240×320. Nice bonus, but it took a while to discover because the bottom 40 px consistently displayed garbage.
- It seems the ESP32 was running into memory issues with the screen buffer. I reduced the color depth to 8‑bit, which is fine since I’m not planning to use many colors.
- The display was experiencing brownouts during boot. This was fixed by adding setup_priority: -100, which delays the display initialization until the end of the boot process. My guess is that Wi‑Fi draws too much power during startup.
