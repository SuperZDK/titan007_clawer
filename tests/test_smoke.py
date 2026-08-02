import logging

logger = logging.getLogger(__name__)


def test_import_core():
    from core import models
    from core import utils
    from core import odds_parser
    from core import parser
    from core import version_detector
    logger.info("All core modules imported successfully")


def test_models_basic():
    from core.models import MatchInfo, AsianOddsItem, EuroOddsItem, OverUnderItem
    m = MatchInfo(schedule_id=1, hometeam="A", guestteam="B", match_time="2026-01-01",
                  league_id=1, league_name_cn="Test", season="2026")
    assert m.schedule_id == 1
    logger.info(f"MatchInfo created: {m.hometeam} vs {m.guestteam}")


def test_utils_basic():
    from core.utils import compute_match_key
    key = compute_match_key("EPL", "2025-2026", "Arsenal", "Chelsea", "2026-01-01")
    assert "epl" in key
    assert "arsenal" in key
    logger.info(f"Match key: {key}")
