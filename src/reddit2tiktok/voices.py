"""Voice identifiers shared by configuration and the local narrator."""

KOKORO_VOICES = {
    "bm_daniel": "British male Daniel",
    "bm_fable": "British male Fable",
    "bm_george": "British male George",
    "bm_lewis": "British male Lewis",
    "bf_alice": "British female Alice",
    "bf_emma": "British female Emma",
    "bf_isabella": "British female Isabella",
    "bf_lily": "British female Lily",
}


def default_voice(engine: str) -> str:
    return "bm_daniel" if engine == "kokoro" else "en-GB-RyanNeural"
