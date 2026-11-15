# Vavra 1.0.0

Vavra gets a new native MPC screen in the look of the microQ's front panel, in three skins, with RANDOM and named favourites.

## What's new
- **MAIN like the microQ's front**: the keys in a panel over the green LCD (bank and sound with step arrows, status and DSP load), the red data
  dial that steps through the sounds, eight big performance knobs, and Volume / Output Gain.
- **Three skins**: the yellow **microQ**, the **Dark Blue** microQ and the **Phoenix Edition**. The SKIN key steps through them; the choice applies to
  every Vavra on the MPC.
- **RANDOM**: a random sound from every loaded bank (MAIN and BANKS).
- **Named favourites**: **+FAV** opens an on-screen keyboard with the sound's name; edit it and SAVE. Favourites are in MPC's PRESET list.
- **Every page redrawn**: drawn pick-lists for every choice, every block of four controls a Q-Link group, ENVELOPES before AMP & GLIDE.
- **Cleaner output**: audio reaches the MPC in floating point, so loud sounds no longer clip in the plugin.
- **Projects saved with 0.1.0 still load** with their sound and edits; the parameter order is unchanged, so automation and Q-Links carry over.

## Install
- `Vavra-1.0.0-mpc-sdk.zip`: copy the folder `sd88me - VST - Vavra` into a `VST2 Plugins` folder on a drive of the MPC and put your ROM in its
  `vavra/roms/` (sound sets in `vavra/banks/`). Needs MPC OS 3.10.1 or later, with Preferences → Enhancements (Beta) → Enable Enhancements and
  External Plugin Support switched on.
- `Vavra-1.0.0-mpc-aarch64.zip`: run `install.sh` on the device as root. A 0.1.0 install is upgraded in place; your ROM, sound sets and favourites
  are kept.

Use one of the two, not both. 64-bit MPCs only (Live III and others); the Force and the 32-bit MPCs are not supported.
Your own microQ ROM is required and not included.

## Notes
- Tested on an MPC Live III as the identical beta build. A 0.1.0 project was tested offline with a real 0.1.0 project chunk; loading one on the
  device, save/reload on the device and the install.sh upgrade were not tried.
- Some hot ROM sounds (for example A001 at Volume 126) drive the microQ's own output into clipping, as the emulated firmware limits it; lower the
  sound's Volume on AMP & GLIDE.
