# Delay Lama

![alt text](image.png)

**Delay Lama** is a monophonic vocal synthesizer based on the AudioNerdz plug-in. Play MIDI or the XY pad: horizontal movement controls pitch; vertical movement controls vowel. Controls: Vowel, Portamento, Delay, and Voice.

## Formats and platforms

| Platform | Release architectures | Formats |
| --- | --- | --- |
| Windows | x86_64, ARM64 | CLAP, VST3, LV2 |
| Linux | x86_64, ARM64 | CLAP, VST3, LV2 |
| macOS | Apple Silicon + Intel, universal | CLAP, VST3, LV2, AUv2, AUv3 |
| iOS / iPadOS | ARM64 | AUv3 |

Linux builds use Ubuntu 24.04 and need X11 (or XWayland) and Vulkan. 32-bit targets, Android, BSD, and other UNIX ports are not supported.

## Install

Download the package for your operating system and **DAW architecture**: Windows ZIP, Linux tar.gz, or the universal macOS DMG. Extract the archive or open the DMG, then read `INSTALL.txt` beside the plug-ins. The `Documentation` folder keeps the project information and redistribution terms together.

Close your DAW, copy the **whole plug-in** in a format it supports, then reopen it and rescan. You do not need to install every format, and you should not copy individual files out of a plug-in bundle.

| Platform | Plug-in folders |
| --- | --- |
| Windows | `%COMMONPROGRAMFILES%\CLAP`, `%COMMONPROGRAMFILES%\VST3`, `%APPDATA%\LV2` |
| Linux | `~/.clap`, `~/.vst3`, `~/.lv2` |
| macOS | `~/Library/Audio/Plug-Ins/{CLAP,VST3,LV2,Components}` |

For AUv3, copy `Delay Lama.app` to `/Applications` and open the installed copy once before rescanning your DAW. It contains the AUv3 extension, not a standalone synthesizer. Keep it installed; do not extract the extension from inside it. The DMG itself is not an installer. Windows and Linux archives are unsigned; the macOS DMG is signed and notarized.

iOS installation is separate from desktop installation. Ad Hoc packages work only on registered devices. An IPA cannot be installed by copying it into a desktop plug-in folder.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for building from source and contributing, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for participation rules.

## License

This software is provided free of charge and may be distributed freely, as long as all the files are distributed along with the plugin file. It may not be sold or included in any commercial package, nor used as part of any commercial promotion. Contact AudioNerdz if you wish to include it on a CD collection.
