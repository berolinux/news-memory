"""Primary news languages and Google News markets for under-covered countries."""

from __future__ import annotations

# English-language wires already drown these. Do not add a per-country GNews feed.
WELL_COVERED = {
    "US", "GB", "DE", "FR", "CN", "IN", "RU", "JP", "BR", "AU", "CA",
    "IT", "ES", "KR", "MX", "TR", "ID", "NL", "PL", "SE", "NO", "FI",
    "DK", "CH", "AT", "BE", "NZ", "PT", "GR", "IE",
}

# Nearby Google News `gl` when the country itself has no market.
GL_NEAR = {
    "LI": "CH", "AD": "ES", "MC": "FR", "SM": "IT", "VA": "IT",
    "TV": "NZ", "KI": "AU", "NR": "AU", "PW": "US", "MH": "US",
    "FM": "US", "WS": "NZ", "TO": "NZ", "CK": "NZ", "NU": "NZ",
    "TK": "NZ", "SB": "AU", "VU": "AU", "PG": "AU", "FJ": "AU",
    "KM": "FR", "SC": "FR", "MU": "FR", "YT": "FR", "RE": "FR",
    "ST": "PT", "CV": "PT", "GW": "PT", "TL": "PT", "GQ": "ES",
    "XK": "AL", "ME": "DE", "BA": "DE", "MK": "DE", "AL": "AL",
    "MT": "MT", "CY": "GR", "LU": "DE", "IS": "IS", "FO": "DK",
    "GL": "DK", "AX": "FI", "SJ": "NO", "GI": "GB", "JE": "GB",
    "GG": "GB", "IM": "GB", "BM": "GB", "KY": "GB", "VG": "GB",
    "AI": "GB", "MS": "GB", "TC": "GB", "FK": "GB", "SH": "GB",
    "IO": "GB", "PN": "GB", "GS": "GB", "AS": "US", "GU": "US",
    "MP": "US", "VI": "US", "PR": "US", "UM": "US", "BQ": "NL",
    "CW": "NL", "SX": "NL", "AW": "NL", "BL": "FR", "MF": "FR",
    "GP": "FR", "MQ": "FR", "GF": "FR", "PM": "FR", "WF": "FR",
    "NC": "FR", "PF": "FR", "TF": "FR", "EH": "MA", "PS": "EG",
    "TW": "TW", "HK": "HK", "MO": "HK", "KP": "KR", "LA": "TH",
    "BT": "IN", "MV": "IN", "NP": "IN", "AF": "AF", "TJ": "RU",
    "TM": "RU", "KG": "RU", "UZ": "RU", "MN": "MN", "AM": "AM",
    "AZ": "AZ", "GE": "GE", "MD": "RO", "BY": "RU", "UA": "UA",
}

HL = {
    "de": "de", "fr": "fr", "es": "es", "pt": "pt-BR", "ar": "ar",
    "en": "en", "ru": "ru", "zh": "zh-CN", "it": "it", "nl": "nl",
    "ja": "ja", "tr": "tr", "id": "id", "sw": "en-KE", "pl": "pl",
    "uk": "uk", "ko": "ko", "hi": "hi", "sv": "sv", "fi": "fi",
    "nb": "no", "da": "da", "cs": "cs", "ro": "ro", "hu": "hu",
    "el": "el", "he": "he", "fa": "fa", "ur": "ur", "bn": "bn",
    "ta": "ta", "th": "th", "vi": "vi", "ms": "ms", "ca": "ca",
    "bg": "bg", "sr": "sr", "hr": "hr", "sk": "sk", "sl": "sl",
    "et": "et", "lv": "lv", "lt": "lt", "am": "am", "so": "so",
}

DEFAULT_GL = {
    "de": "DE", "fr": "FR", "es": "ES", "pt": "BR", "ar": "EG",
    "en": "US", "ru": "RU", "zh": "CN", "it": "IT", "nl": "NL",
    "ja": "JP", "tr": "TR", "id": "ID", "sw": "KE", "pl": "PL",
    "uk": "UA", "ko": "KR", "hi": "IN", "sv": "SE", "fi": "FI",
    "nb": "NO", "da": "DK", "cs": "CZ", "ro": "RO", "hu": "HU",
    "el": "GR", "he": "IL", "fa": "IR", "ur": "PK", "bn": "BD",
    "ta": "IN", "th": "TH", "vi": "VN", "ms": "MY",
}

# iso -> languages, most important first
_LANG = {}


def _put(langs, *codes):
    for c in codes:
        _LANG[c] = list(langs)


_put(["de"], "DE", "AT", "LI")
_put(["de", "fr", "it"], "CH")
_put(["de", "fr"], "LU", "BE")
_put(["fr"], "FR", "MC", "SN", "ML", "NE", "TD", "TG", "BJ", "BF", "CI",
     "GN", "GA", "CG", "CF", "CD", "DJ", "MG", "HT", "NC", "PF", "WF",
     "RE", "YT", "GP", "MQ", "GF", "PM", "BL", "MF", "TN")
_put(["fr", "ar"], "KM", "MR", "DZ", "MA")
_put(["fr", "en"], "CM", "RW", "BI", "SC", "VU", "MU")
_put(["ar"], "EG", "SA", "AE", "QA", "KW", "BH", "OM", "IQ", "JO",
     "LB", "SY", "YE", "SD", "LY", "PS", "EH")
_put(["es"], "ES", "MX", "AR", "CO", "CL", "PE", "VE", "EC", "GT", "CU",
     "BO", "DO", "HN", "PY", "SV", "NI", "CR", "PA", "UY", "GQ", "AD")
_put(["pt"], "PT", "BR", "AO", "MZ", "GW", "ST", "CV", "TL")
_put(["en"], "US", "GB", "AU", "NZ", "IE", "JM", "TT", "BB", "BS", "BZ",
     "GY", "LR", "SL", "GH", "NG", "GM", "BW", "ZM", "ZW", "MW", "UG",
     "KE", "TZ", "SS", "SZ", "LS", "NA", "FJ", "PG", "SB", "TO", "WS",
     "TV", "KI", "NR", "PW", "MH", "FM", "CK", "NU", "TK", "AG", "KN",
     "LC", "VC", "GD", "DM", "MT", "SG", "PH", "IN", "PK", "BD", "LK",
     "MY", "MM", "HK", "GI", "JE", "GG", "IM", "BM", "KY", "VG", "AI",
     "MS", "TC", "FK", "SH", "IO", "PN", "GS", "AS", "GU", "MP", "VI",
     "PR", "UM")
_put(["en", "sw"], "KE", "TZ", "UG")
_put(["it"], "IT", "SM", "VA")
_put(["nl"], "NL", "SR", "AW", "CW", "SX", "BQ")
_put(["nl", "fr"], "BE")
_put(["ru"], "RU", "BY", "KZ", "KG", "TJ", "TM", "UZ")
_put(["uk"], "UA")
_put(["pl"], "PL")
_put(["cs"], "CZ")
_put(["sk"], "SK")
_put(["hu"], "HU")
_put(["ro"], "RO", "MD")
_put(["bg"], "BG")
_put(["el"], "GR", "CY")
_put(["tr"], "TR")
_put(["sv"], "SE", "AX")
_put(["fi"], "FI")
_put(["nb"], "NO", "SJ")
_put(["da"], "DK", "FO", "GL")
_put(["is"], "IS")
_put(["et"], "EE")
_put(["lv"], "LV")
_put(["lt"], "LT")
_put(["sl"], "SI")
_put(["hr"], "HR")
_put(["sr"], "RS", "ME", "BA", "XK")
_put(["sq"], "AL", "XK")
_put(["mk"], "MK")
_put(["bs"], "BA")
_put(["hy"], "AM")
_put(["az"], "AZ")
_put(["ka"], "GE")
_put(["he"], "IL")
_put(["fa"], "IR", "AF")
_put(["ur"], "PK")
_put(["hi"], "IN")
_put(["bn"], "BD")
_put(["si"], "LK")
_put(["ne"], "NP")
_put(["dz"], "BT")
_put(["dv"], "MV")
_put(["th"], "TH")
_put(["lo"], "LA")
_put(["km"], "KH")
_put(["vi"], "VN")
_put(["ms"], "MY", "BN")
_put(["id"], "ID")
_put(["tl"], "PH")
_put(["zh"], "CN", "TW", "HK", "MO", "SG")
_put(["ja"], "JP")
_put(["ko"], "KR", "KP")
_put(["mn"], "MN")
_put(["am"], "ET")
_put(["so"], "SO")
_put(["ti"], "ER")
_put(["sw"], "TZ", "KE")
_put(["af", "en"], "ZA")
_put(["pt", "es"], "GQ")

# later _put overwrites; restore multilingual specials
_put(["de", "fr", "it"], "CH")
_put(["de", "fr", "nl"], "BE")
_put(["fr", "ar"], "KM", "DZ", "MA", "MR", "TN")
_put(["en", "fr"], "CM", "CA", "RW", "BI", "SC", "VU", "MU")
_put(["en", "mi"], "NZ")
_put(["en", "zh"], "SG", "HK")
_put(["ar", "en"], "AE", "QA", "BH", "KW")
_put(["en", "ga"], "IE")
_put(["en", "cy"], "GB")  # still English-primary for GNews

EXTRA_QUERIES = {
    "LI": ["Liechtenstein", "Vaduz"],
    "TV": ["Tuvalu", "Funafuti"],
    "KM": ["Comores", "Komori", "جزر القمر", "Moroni"],
    "AD": ["Andorra"],
    "SM": ["San Marino"],
    "MC": ["Monaco"],
    "NR": ["Nauru"],
    "PW": ["Palau"],
    "ST": ["São Tomé", "Sao Tome"],
    "GW": ["Guinée-Bissau", "Guinea-Bissau"],
    "TL": ["Timor-Leste", "Timor Leste"],
    "XK": ["Kosovo", "Kosova"],
    "EH": ["Sahara occidental", "Western Sahara"],
    "PS": ["Palestine", "Gaza", "الضفة"],
    "VA": ["Vatican", "Holy See", "Santa Sede"],
}


def langs_for(iso: str) -> list[str]:
    return list(_LANG.get(iso, ["en"]))


def gnews_market(iso: str, lang: str) -> tuple[str, str]:
    hl = HL.get(lang, lang if len(lang) == 2 else "en")
    gl = GL_NEAR.get(iso) or DEFAULT_GL.get(lang, iso)
    return hl, gl


def needs_country_feed(iso: str) -> bool:
    return iso not in WELL_COVERED


WIKI_PORTALS = (
    ("en", "en.wikipedia.org", "Portal:Current_events"),
    ("de", "de.wikipedia.org", "Portal:Aktuelle_Ereignisse"),
    ("fr", "fr.wikipedia.org", "Portail:Actualités"),
    ("es", "es.wikipedia.org", "Portal:Actualidad"),
    ("pt", "pt.wikipedia.org", "Portal:Eventos_atuais"),
    ("it", "it.wikipedia.org", "Portale:Attualità"),
    ("nl", "nl.wikipedia.org", "Portaal:Actuele_gebeurtenissen"),
    ("pl", "pl.wikipedia.org", "Portal:Aktualności"),
    ("ru", "ru.wikipedia.org", "Портал:Текущие_события"),
    ("ar", "ar.wikipedia.org", "بوابة:أحداث_جارية"),
    ("zh", "zh.wikipedia.org", "Portal:新闻动态"),
    ("ja", "ja.wikipedia.org", "Portal:最近の出来事"),
    ("tr", "tr.wikipedia.org", "Portal:Güncel_olaylar"),
    ("id", "id.wikipedia.org", "Portal:Peristiwa_terkini"),
    ("sv", "sv.wikipedia.org", "Portal:Aktuella_händelser"),
    ("uk", "uk.wikipedia.org", "Портал:Поточні_події"),
    ("cs", "cs.wikipedia.org", "Portál:Aktuality"),
    ("fi", "fi.wikipedia.org", "Portaali:Ajankohtaista"),
    ("hu", "hu.wikipedia.org", "Portál:Aktuális_események"),
    ("he", "he.wikipedia.org", "פורטל:אירועים_שוטפים"),
    ("ko", "ko.wikipedia.org", "포털:요즘_화제"),
    ("ca", "ca.wikipedia.org", "Portal:Actualitat"),
)
