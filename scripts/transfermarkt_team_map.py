"""Fantapazz national codes mapped to Transfermarkt slugs and team IDs."""

from __future__ import annotations

# slug: URL segment on transfermarkt.it
# team_id: verein ID used in /leistungsdaten/verein/{team_id}
TEAM_MAP: dict[str, tuple[str, int]] = {
    "ALG": ("algerien", 3614),
    "ARG": ("argentinien", 3437),
    "AUS": ("australien", 3433),
    "AUT": ("osterreich", 3383),
    "BEL": ("belgien", 3382),
    "BOS": ("bosnien-herzegowina", 3446),
    "BRA": ("brasilien", 3439),
    "CAN": ("kanada", 3510),
    "CIV": ("elfenbeinkuste", 3591),
    "COD": ("demokratische-republik-kongo", 3854),
    "COL": ("kolumbien", 3816),
    "CPV": ("kap-verde", 4311),
    "CRO": ("kroatien", 3556),
    "CUW": ("curacao", 32364),
    "ECU": ("ecuador", 5750),
    "EGY": ("agypten", 3672),
    "FRA": ("frankreich", 3377),
    "GER": ("deutschland", 3262),
    "GHA": ("ghana", 3441),
    "GRD": ("jordanien", 15737),
    "HAI": ("haiti", 14161),
    "ING": ("england", 3299),
    "IRN": ("iran", 3582),
    "IRQ": ("irak", 3560),
    "JAP": ("japan", 3435),
    "KOR": ("sudkorea", 3589),
    "MAR": ("marokko", 3575),
    "MEX": ("mexiko", 6303),
    "NOR": ("norwegen", 3440),
    "NZL": ("neuseeland", 9171),
    "OLA": ("niederlande", 3379),
    "PAN": ("panama", 3577),
    "PAR": ("paraguay", 3581),
    "POR": ("portugal", 3300),
    "QAT": ("katar", 14162),
    "RCE": ("tschechien", 3445),
    "SAF": ("sudafrika", 3806),
    "SAU": ("saudi-arabien", 3807),
    "SCO": ("schottland", 3380),
    "SEN": ("senegal", 3499),
    "SPA": ("spanien", 3375),
    "SVE": ("schweden", 3557),
    "SVI": ("schweiz", 3384),
    "TUN": ("tunesien", 3670),
    "TUR": ("turkei", 3381),
    "URU": ("uruguay", 3449),
    "USA": ("vereinigte-staaten", 3505),
    "UZB": ("usbekistan", 3563),
}

SEASON_ID = 2025  # Transfermarkt season id for 25/26
BASE_URL = "https://www.transfermarkt.it"
TMAPI_URL = "https://tmapi.transfermarkt.technology"


def national_performance_url(slug: str, team_id: int, season_id: int = SEASON_ID) -> str:
    return (
        f"{BASE_URL}/{slug}/leistungsdaten/verein/{team_id}"
        f"/saison_id/{season_id}/plus/0"
    )


def player_performance_url(player_id: int) -> str:
    return f"{BASE_URL}/-/profil/spieler/{player_id}"
