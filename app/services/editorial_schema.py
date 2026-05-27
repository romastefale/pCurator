PUBLIC_POST_JSON_SCHEMA = {
    "name": "public_post",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hashtags": {
                "type": "array",
                "minItems": 3,
                "maxItems": 4,
                "items": {"type": "string"},
            },
            "title": {"type": "string", "minLength": 12, "maxLength": 120},
            "subtitle": {"type": "string", "minLength": 20, "maxLength": 180},
            "body": {"type": "string", "minLength": 120, "maxLength": 580},
            "source_url": {"type": "string"},
            "needs_review": {"type": "boolean"},
            "quality_notes": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string"},
            },
        },
        "required": [
            "hashtags",
            "title",
            "subtitle",
            "body",
            "source_url",
            "needs_review",
            "quality_notes",
        ],
    },
    "strict": True,
}
