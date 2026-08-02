"""Controlled render variation layers that never rewrite scene content."""

VARIATIONS = [
    ("faithful_neutral", "Render with balanced neutral cinematic lighting, natural color, and restrained contrast."),
    ("warm_directional", "Use warm directional key light with soft cool fill and subtle amber highlights."),
    ("cool_overcast", "Use cool diffused overcast illumination, gentle shadow detail, and muted natural color."),
    ("high_contrast", "Use sculpted high-contrast cinematic lighting with controlled highlights and deep readable shadows."),
    ("soft_portrait", "Use soft wraparound character lighting, delicate skin detail, and shallow natural depth of field."),
    ("documentary", "Use grounded documentary realism, available light, restrained grading, and authentic material texture."),
    ("film_emulsion", "Use subtle 35mm film color response, fine grain, gentle halation, and realistic exposure."),
    ("atmospheric", "Use light atmospheric depth and volumetric separation without obscuring faces, hands, or props."),
    ("crisp_dramatic", "Use crisp dramatic clarity on eyes, expression, hands, and identity-defining accessories."),
    ("prestige_fantasy", "Use restrained prestige-fantasy production design, rich materials, and natural cinematic color."),
]


def apply_variation(base_prompt: str, sequence: int) -> tuple[str, str]:
    name, directive = VARIATIONS[(sequence - 1) % len(VARIATIONS)]
    locked = " Preserve all described people, identity details, gaze, expression, pose, arrangement, facial coverings, neck-worn objects, props, and geometry exactly; vary rendering treatment only."
    return f"{base_prompt.rstrip()} {directive}{locked}", name
