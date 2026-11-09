"""매일 예측 실행 예약 Worker(proxy/cron): GitHub workflow_dispatch를 정확히 부르고, 토큰이 없거나 거절되면 실패로 남긴다."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CRON = ROOT / "proxy" / "cron"


def test_crons_cover_daily_kst_times_and_token_is_secret():
    toml = (CRON / "wrangler.toml").read_text(encoding="utf-8")
    assert re.search(r'crons = \["7 0,3,5,7,8 \* \* \*", "55 8 \* \* \*"\]', toml)   # 09:07·12:07·14:07·16:07·17:07·17:55 KST
    assert "GH_TOKEN" not in toml.split("[triggers]")[0].replace("secret put GH_TOKEN", "")   # 토큰은 파일에 없다
    daily = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in daily                                                      # 수동 실행을 받아야 한다


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_dispatch_calls_github_and_fails_loudly(tmp_path):
    shutil.copy(CRON / "cron-worker.js", tmp_path / "cron.mjs")
    (tmp_path / "t.mjs").write_text("""
import worker, { dispatch } from "./cron.mjs";
const out = {};
let call;
globalThis.fetch = async (url, opts) => { call = { url, opts }; return new Response(null, { status: 204 }); };
out.ok = await dispatch({ GH_TOKEN: "t" }, "test");
out.call = { url: call.url, method: call.opts.method, body: JSON.parse(call.opts.body), auth: call.opts.headers.Authorization };
out.noToken = await dispatch({}, "test");
globalThis.fetch = async () => new Response("Bad credentials", { status: 401 });
try { await worker.scheduled({ cron: "55 8 * * *", scheduledTime: 0 }, { GH_TOKEN: "x" }, {}); out.threw = false; } catch { out.threw = true; }
out.fetchStatus = (await worker.fetch(new Request("https://x/"))).status;
console.log(JSON.stringify(out));
""", encoding="utf-8")
    r = json.loads(subprocess.run(["node", str(tmp_path / "t.mjs")], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1])
    assert r["ok"]["ok"] is True and r["call"]["method"] == "POST" and r["call"]["body"] == {"ref": "main"}
    assert r["call"]["url"] == "https://api.github.com/repos/kimminseo2323-prog/2610_KBO_predict/actions/workflows/daily.yml/dispatches"
    assert r["call"]["auth"] == "Bearer t" and r["noToken"]["ok"] is False and r["threw"] is True and r["fetchStatus"] == 404
