"""선발 바꿔 보기: 파이썬 재현(whatif.prob)·브라우저 코드(site/assets/whatif.js, node로 실행)·실제 예측(predict.raw_prob)이
같은 확률을 낸다. 예고(실제) 선발 그대로면 공개 확률과 같고, 다른 선발을 넣어도 실제 모델과 같다."""
import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kbo_predict import raw_store, whatif
from kbo_predict.features import starter_ids
from kbo_predict.predict import raw_prob
from kbo_predict.rewind import state_before
from kbo_predict.train_win import load_bundle

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-09-01"


@pytest.fixture(scope="module")
def real():
    games, boxes = raw_store.load_games(2026), raw_store.load_boxscores(2026)
    bundle = load_bundle(ROOT / "models" / "report-2026.pkl")
    state = state_before(2026, DAY, games=games, boxscores=boxes)
    day = [g for g in games if g["date"] == DAY and g["status"] == "FINAL"]
    blocks = [whatif.game_block(g, state, starter_ids(boxes.get(g["game_id"])), games, boxes, regular_only=True) for g in day]
    return {"games": day, "boxes": boxes, "bundle": bundle, "state": state, "blocks": blocks, "params": whatif.model_params(bundle)}


def _combos(real, n=3):
    for g, b in zip(real["games"], real["blocks"]):
        for h, a in itertools.product(b["candidates"]["home"][:n], b["candidates"]["away"][:n]):
            yield g, b, h, a


def test_python_whatif_equals_real_model_for_any_starters(real):
    worst = 0.0
    for g, b, h, a in _combos(real):
        pick = {"home": {"player_id": h["player_id"]}, "away": {"player_id": a["player_id"]}}
        p_real = raw_prob(real["bundle"], g, real["state"], pick)
        worst = max(worst, abs(whatif.prob(real["params"], b["base"], h["line"], a["line"]) - p_real))
    assert worst < 1e-9


def test_announced_starter_is_first_and_matches_public_prob(real):
    for g, b in zip(real["games"], real["blocks"]):
        for side in ("home", "away"):
            assert b["candidates"][side][0]["player_id"] == b["announced"][side]
            assert len(b["candidates"][side]) <= whatif.MAX_CANDIDATES
        h, a = b["candidates"]["home"][0], b["candidates"]["away"][0]
        p = whatif.prob(real["params"], b["base"], h["line"], a["line"])
        assert p == pytest.approx(raw_prob(real["bundle"], g, real["state"], starter_ids(real["boxes"].get(g["game_id"]))), abs=1e-12)
    day_file = json.loads((ROOT / "data" / "public" / "rewind" / "2026" / f"{DAY}.json").read_text(encoding="utf-8"))
    assert [w["game_id"] for w in day_file["whatif"]] == [b["game_id"] for b in sorted(real["blocks"], key=lambda b: b["game_id"])]


def test_no_starter_line_turns_off_starter_features(real):
    _, b = real["games"][0], real["blocks"][0]
    f = whatif.starter_features(None, b["candidates"]["away"][0]["line"])
    assert f["starter_known"] == 0 and all(v != v for k, v in f.items() if k != "starter_known")  # 전부 NaN


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_browser_code_matches_python(real, tmp_path):
    cases = [{"base": b["base"], "home": h["line"], "away": a["line"], "want": whatif.prob(real["params"], b["base"], h["line"], a["line"])}
             for _, b, h, a in _combos(real, 2)]
    cases.append({"base": real["blocks"][0]["base"], "home": None, "away": real["blocks"][0]["candidates"]["away"][0]["line"],
                  "want": whatif.prob(real["params"], real["blocks"][0]["base"], None, real["blocks"][0]["candidates"]["away"][0]["line"])})
    data = tmp_path / "cases.json"
    data.write_text(json.dumps({"model": real["params"], "cases": cases}), encoding="utf-8")
    js = tmp_path / "run.mjs"
    mod = (ROOT / "site" / "assets" / "whatif.js").resolve().as_uri()
    js.write_text(f"""import {{ whatifProb }} from "{mod}";
import {{ readFileSync }} from "node:fs";
const d = JSON.parse(readFileSync({json.dumps(str(data))}, "utf8"));
console.log(JSON.stringify(d.cases.map((c) => whatifProb(d.model, c.base, c.home, c.away) - c.want)));
""", encoding="utf-8")
    out = subprocess.run(["node", str(js)], capture_output=True, text=True, check=True).stdout
    diffs = json.loads(out)
    assert len(diffs) == len(cases) and max(abs(d) for d in diffs) < 1e-9
