#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from typing import Dict, List, Any, Set

# --------------------------------------------------
# Основной список меток
# --------------------------------------------------
LABELS = [
    "VIOLENCE_GRAPHIC", "VIOLENCE_NON_GRAPHIC", "MURDER_HOMICIDE", "SUICIDE_SELF_HARM",
    "SEX_EXPLICIT", "SEX_SUGGESTIVE", "SEXUAL_VIOLENCE", "NUDITY_EXPLICIT", "NUDITY_NONSEXUAL",
    "DRUGS_USE_DEPICTION", "DRUGS_MENTION_NON_DETAILED", "ALCOHOL_USE", "TOBACCO_USE",
    "CRIME_INSTRUCTIONS", "CRIMINAL_ACTIVITY",
    "WEAPONS_USAGE", "WEAPONS_MENTION",
    "PROFANITY_OBSCENE", "ABUSE_HATE_EXTREMISM", "HORROR_FEAR", "DANGEROUS_IMITABLE_ACTS",
    "MEDICAL_GORE_DETAILS", "GAMBLING", "MILD_CONFLICT",
    "EXTREMISM_PROPAGANDA", "NAZISM_PROPAGANDA", "FASCISM_PROPAGANDA"
]

# --------------------------------------------------
# Тематические группы
# --------------------------------------------------
THEMATIC_GROUPS: Dict[str, List[str]] = {
    "Violence_Gore": ["VIOLENCE_GRAPHIC", "VIOLENCE_NON_GRAPHIC", "MURDER_HOMICIDE", "MEDICAL_GORE_DETAILS", "SUICIDE_SELF_HARM"],
    "Sex_Nudity": ["SEX_EXPLICIT", "SEXUAL_VIOLENCE", "NUDITY_EXPLICIT", "SEX_SUGGESTIVE", "NUDITY_NONSEXUAL"],
    "Alcohol_Drugs_Smoking": ["DRUGS_USE_DEPICTION", "DRUGS_MENTION_NON_DETAILED", "ALCOHOL_USE", "TOBACCO_USE"],
    "Profanity": ["PROFANITY_OBSCENE"],
    "Crime": ["CRIME_INSTRUCTIONS", "CRIMINAL_ACTIVITY"],
    "Weapons": ["WEAPONS_USAGE", "WEAPONS_MENTION"],
    "Frightening_Intense": ["HORROR_FEAR", "DANGEROUS_IMITABLE_ACTS", "ABUSE_HATE_EXTREMISM"],
    "Gambling": ["GAMBLING"],
    "Other": ["MILD_CONFLICT"],
    "Extremism_Propaganda": ["EXTREMISM_PROPAGANDA", "NAZISM_PROPAGANDA", "FASCISM_PROPAGANDA", "ABUSE_HATE_EXTREMISM"]
}

# --------------------------------------------------
# Вес серьёзности по меткам
# --------------------------------------------------
SEVERITY_WEIGHT: Dict[str, int] = {
    "MILD_CONFLICT": 1, "GAMBLING": 1, "WEAPONS_MENTION": 1,
    "VIOLENCE_NON_GRAPHIC": 2, "MURDER_HOMICIDE": 2, "SEX_SUGGESTIVE": 2, "ALCOHOL_USE": 2, "TOBACCO_USE": 2,
    "CRIMINAL_ACTIVITY": 2, "WEAPONS_USAGE": 2, "DRUGS_MENTION_NON_DETAILED": 2, "HORROR_FEAR": 2, "NUDITY_NONSEXUAL": 2,
    "VIOLENCE_GRAPHIC": 3, "SUICIDE_SELF_HARM": 3, "SEX_EXPLICIT": 3, "SEXUAL_VIOLENCE": 3,
    "NUDITY_EXPLICIT": 3, "DRUGS_USE_DEPICTION": 3, "CRIME_INSTRUCTIONS": 3, "PROFANITY_OBSCENE": 3,
    "ABUSE_HATE_EXTREMISM": 3, "DANGEROUS_IMITABLE_ACTS": 3, "MEDICAL_GORE_DETAILS": 3,
    "EXTREMISM_PROPAGANDA": 3, "NAZISM_PROPAGANDA": 3, "FASCISM_PROPAGANDA": 3
}

SEV_MAP_INT2STR = {0: "None", 1: "Mild", 2: "Moderate", 3: "Severe"}
SEV_MAP_STR2INT = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}

# --------------------------------------------------
# Жёсткие 18+ метки
# --------------------------------------------------
HARD_18_LABELS: Set[str] = {
    "VIOLENCE_GRAPHIC", "SEXUAL_VIOLENCE", "SEX_EXPLICIT", "DRUGS_USE_DEPICTION",
    "CRIME_INSTRUCTIONS", "PROFANITY_OBSCENE", "MEDICAL_GORE_DETAILS", "SUICIDE_SELF_HARM",
    "ABUSE_HATE_EXTREMISM", "EXTREMISM_PROPAGANDA", "NAZISM_PROPAGANDA", "FASCISM_PROPAGANDA"
}

# --------------------------------------------------
# Порядок рейтингов
# --------------------------------------------------
ORDERED_RATINGS = ["0+", "6+", "12+", "16+", "18+"]

# --------------------------------------------------
# Типичные метки для soft guard
# --------------------------------------------------
TYPICAL_16_LABELS = {
    "SEX_SUGGESTIVE",
    "WEAPONS_USAGE",
    "CRIMINAL_ACTIVITY",
    "VIOLENCE_NON_GRAPHIC",
    "ALCOHOL_USE",
    "TOBACCO_USE",
    "DRUGS_MENTION_NON_DETAILED",
    "HORROR_FEAR",
    "DANGEROUS_IMITABLE_ACTS",
    "MURDER_HOMICIDE"
}

TYPICAL_12_LABELS = {
    "WEAPONS_MENTION",
    "NUDITY_NONSEXUAL",
    "MILD_CONFLICT",
    "GAMBLING"
}

# --------------------------------------------------
# Правила для Stage 2 (FW_RULES)
# --------------------------------------------------
FW_RULES: Dict[str, Any] = {
    "bs": {
        "PROFANITY_OBSCENE": 90,
        "VIOLENCE_GRAPHIC": 90,
        "VIOLENCE_NON_GRAPHIC": 40,
        "MURDER_HOMICIDE": 70,
        "SEX_EXPLICIT": 90,
        "SEX_SUGGESTIVE": 60,
        "DRUGS_USE_DEPICTION": 90,
        "DRUGS_MENTION_NON_DETAILED": 45,
        "ALCOHOL_USE": 40,
        "TOBACCO_USE": 35,
        "HORROR_FEAR": 55,
        "ABUSE_HATE_EXTREMISM": 85,
        "CRIME_INSTRUCTIONS": 95,
        "WEAPONS_USAGE": 55,
        "WEAPONS_MENTION": 35,
        "MEDICAL_GORE_DETAILS": 90,
        "NUDITY_EXPLICIT": 85,
        "NUDITY_NONSEXUAL": 40,
        "GAMBLING": 35,
        "MILD_CONFLICT": 25,
        "DANGEROUS_IMITABLE_ACTS": 80,
        "SUICIDE_SELF_HARM": 95,
        "CRIMINAL_ACTIVITY": 60,
        "EXTREMISM_PROPAGANDA": 90,
        "NAZISM_PROPAGANDA": 95,
        "FASCISM_PROPAGANDA": 95
    },
    "mod": { "many": 10, "gore": 20, "off": -15, "condemn": -10, "warn": -8, "glorify": 12, "instr": 15 },
    "th": { "None": [0, 24], "Mild": [25, 49], "Moderate": [50, 79], "Severe": [80, 100] },
    "blk": {
        "PROFANITY_OBSCENE": "Severe",
        "VIOLENCE_GRAPHIC": "Severe",
        "SEX_EXPLICIT": "Severe",
        "DRUGS_USE_DEPICTION": "Severe",
        "CRIME_INSTRUCTIONS": "Severe",
        "SUICIDE_SELF_HARM": "Severe",
        "SEXUAL_VIOLENCE": "Severe",
        "MEDICAL_GORE_DETAILS": "Severe",
        "EXTREMISM_PROPAGANDA": "Severe", "NAZISM_PROPAGANDA": "Severe", "FASCISM_PROPAGANDA": "Severe"
    },
    "prio": "Severe_overrides_mitigations",
    "lex": {"mask": ["*", " ", ".", "-", "_", "0", "1", "3", "4", "7"], "hint": "anti-obfuscation for profanity"},
    "crit": {
        "VIOLENCE_GRAPHIC": "Требуются явные слова/описания крови/ран/мучений/натурализма.",
        "VIOLENCE_NON_GRAPHIC": "Без крови/натурализма; кратко.",
        "MURDER_HOMICIDE": "Явная попытка/совершение убийства."
    }
}

# --------------------------------------------------
# Взаимоисключающие пары для Stage 1
# --------------------------------------------------
S1_EXCLUSIVE_PAIRS = [
    ("WEAPONS_USAGE","WEAPONS_MENTION"),
    ("VIOLENCE_GRAPHIC","VIOLENCE_NON_GRAPHIC"),
    ("SEX_EXPLICIT","SEX_SUGGESTIVE"),
]

# --------------------------------------------------
# Токены для детекции контекстных смягчений / усилений
# --------------------------------------------------
CONDEMNATION_TOKENS = {"осуждает","осуждение","запрещено","нельзя","не надо","прекрати","плохой","дурной"}
FAMILY_TOKENS = {"дедушка","бабушка","папа","мама","сын","дочь","брат","сестра"}
COMEDY_TOKENS = {"шутит","шутка","смешно","смех","смеётся","игриво","играет","шалит"}
GRAPHIC_TOKENS = {"кровь","кровав","рана","ранение","нутро","вырван","выпотрош","растерзан"}
AROUSAL_TOKENS = {"возбужд","эрекц","страст","похот","орг","совокуп","трётся"}

# --------------------------------------------------
# Регулярные выражения для корней обсценной лексики
# --------------------------------------------------
_PROFANITY_ROOT_PATTERNS: List[re.Pattern] = [
    re.compile(r"бзд", re.IGNORECASE),
    re.compile(r"бля", re.IGNORECASE),
    re.compile(r"(?:ёб|еб)", re.IGNORECASE),
    re.compile(r"елд", re.IGNORECASE),
    re.compile(r"говн", re.IGNORECASE),
    re.compile(r"жоп", re.IGNORECASE),
    re.compile(r"манд", re.IGNORECASE),
    re.compile(r"муд", re.IGNORECASE),
    re.compile(r"перд", re.IGNORECASE),
    re.compile(r"пизд", re.IGNORECASE),
    re.compile(r"сра", re.IGNORECASE),
    re.compile(r"сса", re.IGNORECASE),
    re.compile(r"хуе|хуй|хуя", re.IGNORECASE),
    re.compile(r"шлюх", re.IGNORECASE),
]

# --------------------------------------------------
# Алиасы нормализации меток
# --------------------------------------------------
_ALIAS_MAP = {
    "weapon_mention": "WEAPONS_MENTION", "weapons_mention": "WEAPONS_MENTION", "weaponmention": "WEAPONS_MENTION",
    "weapon_usage": "WEAPONS_USAGE", "weapons_usage": "WEAPONS_USAGE", "weaponuse": "WEAPONS_USAGE",
    "murder_homicide": "MURDER_HOMICIDE", "murder/homicide": "MURDER_HOMICIDE", "murder": "MURDER_HOMICIDE",
    "homicide": "MURDER_HOMICIDE",
    "violence_graphic": "VIOLENCE_GRAPHIC", "violence_non_graphic": "VIOLENCE_NON_GRAPHIC",
    "profanity": "PROFANITY_OBSCENE", "nudity_nonsexual": "NUDITY_NONSEXUAL", "sexual_violence": "SEXUAL_VIOLENCE",
    "sex_suggestive": "SEX_SUGGESTIVE", "sex_explicit": "SEX_EXPLICIT",
    "drugs_mention_non_detailed": "DRUGS_MENTION_NON_DETAILED", "medical_gore": "MEDICAL_GORE_DETAILS",
    "extremism": "EXTREMISM_PROPAGANDA", "extremism_propaganda": "EXTREMISM_PROPAGANDA",
    "nazism": "NAZISM_PROPAGANDA", "fascism": "FASCISM_PROPAGANDA", "fascism_propaganda": "FASCISM_PROPAGANDA"
}