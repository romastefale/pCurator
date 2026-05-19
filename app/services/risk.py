CLICKBAIT_TERMS = (
    "chocante",
    "bombástico",
    "veja antes que apaguem",
    "ninguém esperava",
    "o que aconteceu depois",
    "vai te surpreender",
    "não vai acreditar",
    "exclusivo urgente",
)

POLARIZED_TERMS = (
    "escândalo",
    "fraude",
    "corrupção",
    "golpe",
    "ditadura",
    "censura",
    "extremista",
    "terrorista",
)


def assess_link_risk(title: str | None, text: str | None) -> dict:
    content = f"{title or ''} {text or ''}".lower()
    score = 100
    flags: list[str] = []

    if any(term in content for term in CLICKBAIT_TERMS):
        score -= 35
        flags.append("clickbait_possible")

    if any(term in content for term in POLARIZED_TERMS):
        score -= 20
        flags.append("polarized_or_serious_topic")

    if len((text or "").strip()) < 300:
        score -= 15
        flags.append("short_extracted_text")

    score = max(0, min(100, score))
    should_hold = score < 50 or "clickbait_possible" in flags

    return {
        "score": score,
        "flags": flags,
        "should_hold": should_hold,
    }
