# Daniel, Linux, and Docker

Researched September 2026. This is a deployment/voice decision note, not an implemented
alternative TTS provider. The working default remains `en-GB-RyanNeural` through `edge-tts`.

## Identifying the installed Daniel voice

Having a British Daniel voice installed on Windows is possible. The name alone does not identify
its engine, edition, or availability in a container. Microsoft's published Windows voice list
does not identify a stock British Daniel: its British voices include George, Hazel, Susan,
Ryan, and Sonia. An installed Daniel may come from a bundled or separately installed package.
This repository has not inspected or changed the host's installed voices.

Sources: [Microsoft Windows voice list](https://support.microsoft.com/en-US/accessibility/windows/narrator/appendix-a-supported-languages-and-voices),
[Nuance voice catalog](https://docs.nuance.com/nuance-vocalizer-for-enterprise/voc-dev/lang.html).

## Closest route to the exact voice

Nuance explicitly lists **Daniel, British English, male** in Vocalizer. If this is the voice
being requested, using that actual engine/voice package is preferable to guessing a soundalike.
Nuance's enterprise engine supports both Linux and Windows hosts, so an appropriately licensed
Linux edition could avoid a Windows runtime. That does **not** mean a desktop Windows voice
installer or its license automatically works on Linux or permits redistribution in an image.
The package, supported OS version, license, and server/container deployment must be confirmed
with the vendor before integration. No proprietary voice files are included here.

Sources: [Daniel in the Nuance catalog](https://docs.nuance.com/nuance-vocalizer-for-enterprise/voc-dev/lang.html),
[Vocalizer platform and license requirements](https://docs.nuance.com/nuance-vocalizer-for-enterprise/voc-install/vocig-req.html).

## Free/local alternative to audition

**Kokoro-82M `bm_daniel`** is a British male voice available for local TTS; its published model
weights use Apache-2.0. It is a candidate to audition, **not a verified clone or acoustic match
for Nuance/Windows Daniel**. `bm_george` and `bm_fable` are other British male candidates.
Compare the same short story excerpt against the installed Daniel before choosing; the shared
name is not evidence of shared sound. The current CLI does not accept these IDs as Edge voices.

Sources: [Official model and local usage](https://huggingface.co/hexgrad/Kokoro-82M),
[British voice catalog](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md),
[Publisher's listening samples](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/SAMPLES.md).

## What Docker changes (and what it does not)

- Docker Desktop's Linux containers on Windows still run in a Linux environment. They cannot
  directly call a host Windows SAPI voice merely because Docker runs on Windows.
- Windows containers start from a Windows container base image, not a copy of the desktop's
  installed applications. The required speech API, compatible voice engine, voice package,
  and licensing would need to be available in that image. Daniel in a Windows container has
  **not been verified** for this project; changing the base image alone is not a solution.
- A possible hybrid is a Linux container for scraping/rendering plus a narrowly scoped Windows
  host speech service for the installed voice. That adds a host service, authenticated access,
  and a Windows machine to operate; it is not a Linux-only deployment. Host installation or
  configuration requires the repository owner's separate approval.

Sources: [Docker Desktop WSL 2 backend](https://docs.docker.com/desktop/features/wsl/),
[Windows container base images](https://learn.microsoft.com/en-us/virtualization/windowscontainers/manage-containers/container-base-images),
[Connecting a container to a host service](https://docs.docker.com/desktop/features/networking/networking-how-tos/).

Any future narrator adapter must produce **audio plus reliable word start/end timings** so
captions remain synchronized. Simply saving a SAPI/Kokoro audio file or dividing the duration
equally between words is not sufficient. Keep the existing Edge adapter until a replacement
has been auditioned and its timing and deployment have been tested.
