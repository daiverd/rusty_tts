Add retro/vintage speech-chip synthesizer backends to this project, alongside the
existing Linux synths it already pipes text through to produce WAVs.

## Background (verified against a MESS/MAME Apple II build, not against this repo)

In a separate emulator project (Apple //e under MESS, ~2011-era build), the
emulated machine has a Street Electronics "Echo II Plus" speech card in slot 4.
Binary strings in that build's `mess.exe` confirmed the emulated chip is a
General Instrument **SP0256-AL2** (allophone/phoneme synthesizer), referenced via
device names `a2bus_echoii_device` / `a2bus_echoplus_device`, historical source
path `src/mess/machine/a2echoii.c`. The same binary also links emulation for
**TMS5220 / TMS5220C / TMS5200** (Texas Instruments LPC speech chip, used in
Speak & Spell, several arcade boards) and **Votrax SC-01** (allophone chip, used
in Votrax Type-'n-Talk and various arcade speech boards). I did not find SSI263
in that build — don't assume it's present anywhere; treat other Apple II speech
cards (Cricket!, Slot Buster, etc.) as unverified until checked.

Critically: **none of these chips do text-to-speech themselves.** They are
waveform synthesizers driven by a stream of codes:
- SP0256-AL2 and Votrax SC-01 take **allophone codes** (a fixed table of ~50-64
  phoneme-like units per chip, each chip's table is different and chip-specific).
- TMS5220/5200 take **LPC frames** (linear predictive coding parameters), either
  from a companion "voice synthesis memory" ROM of pre-recorded words, or fed
  live by software for arbitrary speech.
The historical "English text → allophone/LPC codes" step lived in software
running on the host 6502/Z80 (e.g. Street Electronics' "Textalker" driver for
Echo cards), not in the chip. That old driver code has not been extracted or
read in this session — it may exist on Apple II disk images but wasn't
disassembled.

## What I'm asking you to do

1. **Read this repo first.** Understand how it currently plugs in a Linux synth:
   what interface/contract a synth backend implements, how text goes in, how
   WAV comes out, what's configurable per-voice. Don't propose an architecture
   until you've read the actual current code.

2. **Get the real chip emulation source, don't rely on my summary above.**
   Clone MAME (the SP0256/TMS5220/Votrax cores live there now under
   `src/devices/sound/`, not the old `src/mess/...` path I quoted — that path
   is from an old pre-unification MESS tree and has almost certainly moved or
   been rewritten):
   `git clone --depth 1 https://github.com/mamedev/mame ~/src/mame`
   Then read the actual device source for `sp0256`, `tms5220`, `votrax` (search
   `~/src/mame/src/devices/sound/` for these) to see:
   - the real interface each device expects (clock, register writes, allophone
     table format, LPC frame format)
   - whether the device core is reasonably separable from MAME's `device_t`
     framework (memory maps, save-state machinery, scheduler) or genuinely
     needs a big chunk of MAME's plumbing to run standalone
   - MAME's current license (I have not verified it myself — check whether it's
     compatible with reuse in this project before copying/adapting any of that
     source; report what you find rather than assuming)

3. **Solve text→phonemes as a separate, modern problem — don't try to resurrect
   the 1980s Apple II driver.** Check whether `espeak-ng` is available/usable
   here (it can already emit a phoneme stream, not just audio) and evaluate
   using it as the front end: text → espeak-ng phonemes → a small mapping table
   translating espeak-ng's phoneme set to each target chip's allophone/LPC
   table. Only fall back to reverse-engineering the original Echo driver if
   there's a specific reason a period-accurate text parser matters more than
   period-accurate *voice*.

4. **Propose a design before writing code**: where the new backend(s) plug into
   the existing synth interface, what the phoneme-mapping tables look like per
   chip, whether standalone chip emulation is vendored/adapted from MAME or
   reimplemented from the chip datasheet, and which chip(s) to implement first
   (I'd suggest SP0256-AL2 first, since it's the one with a real historical
   reference build to compare output against). Stop and show me the plan before
   implementing.
