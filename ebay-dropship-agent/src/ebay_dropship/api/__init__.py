"""承認 Web UI(最小)。CLI(`cli/`)と同じ `SqlProposalRepository`/`ApprovalQueue` ロジックを共有し、

承認ロジック自体はここで再実装しない。

セキュリティ方針:
- 既定でlocalhost(127.0.0.1)のみにバインドする(`run_api()`)。外部公開する場合はリバースプロキシ・
  TLS・追加の認証/ネットワーク制御を別途用意すること(このアプリ単体では強制できない)。
- `/healthz` を除く全エンドポイントは HTTP Basic 認証必須。認証情報は `.env` の
  `APPROVAL_API_USERS`(`username:password` のカンマ区切りで複数運用者可)で設定する。
  未設定(空文字)の場合は誰も認証できない(fail-closed)。認証された username がそのまま
  `decided_by` として監査に記録される(クライアントが `decided_by` を指定する余地は無い)。
- `risk_level=high` の提案の承認は、リクエストボディで明示的に `confirm: true` を送らない限り
  409 を返して拒否する(高リスク承認の2段階確認)。
- このAPIは承認/却下のみを行い、publish/price_change/purchase の実行(外部副作用)は一切行わない。
  実行は引き続き `orchestrator/do.py` の実行関数(または `run_do` 経由のバッチ)が、承認とは独立に
  `guardrails.gateway.execute_side_effect` の実行時再検査を経て処理する。Web UI が何を送っても、
  この再検査(利益ガードの再計算・在庫再確認・publish必須項目の再確認等)はバイパスできない
  ―― このAPIのコードは実行系のどの関数も呼ばないため、構造的にバイパス経路を持たない。
- `GET /ui`: `/proposals`一覧を承認/却下ボタン付きの簡単なHTML画面として表示する(ブラウザで直接
  操作する用)。認証は他のエンドポイントと同じ`require_auth`を経由する(`/healthz`以外は認証必須、
  という既存方針を維持)。ページ自体は静的HTML+素のJavaScriptのみ(外部ライブラリ・CDN読み込み無し)で、
  承認/却下は既存の`/proposals/{id}/approve`・`/proposals/{id}/reject`をブラウザから叩くだけ
  ―― サーバ側に新しい判断ロジック・新しい実行経路は一切追加していない。
"""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from ebay_dropship.approval import Proposal, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.config import settings as default_settings
from ebay_dropship.store import (
    InvalidTransitionError,
    ProposalNotFoundError,
    SqlProposalRepository,
    create_engine_from_settings,
    create_session_factory,
)

app = FastAPI(title="ebay-dropship-agent 承認API")

_security = HTTPBasic()


def _parse_users(raw: str) -> dict[str, str]:
    users: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        username, _, password = entry.partition(":")
        if username and password:
            users[username] = password
    return users


def get_settings() -> Settings:
    return default_settings


def require_auth(
    credentials: Annotated[HTTPBasicCredentials, Depends(_security)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """認証されたusernameを返す。これが唯一のdecided_by供給源(クライアントは指定できない)。"""
    users = _parse_users(settings.approval_api_users)
    # F6(adversarial security review, 2026-08-29): 未知usernameのときだけcompare_digestを
    # 呼ばずに短絡評価すると、既知usernameとの応答時間差からusernameの存在を推測できる
    # (タイミングサイドチャネル)。既知/未知いずれでも必ずcompare_digestを1回呼ぶことで、
    # username自体の正誤で処理経路が変わらないようにする(ダミー値との比較は必ず失敗する)。
    expected_password = users.get(credentials.username, "")
    password_matches = secrets.compare_digest(credentials.password, expected_password)
    is_valid = credentials.username in users and password_matches
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証に失敗しました。",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def get_repository(settings: Annotated[Settings, Depends(get_settings)]):
    engine = create_engine_from_settings(settings)
    session = create_session_factory(engine)()
    try:
        yield SqlProposalRepository(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _jsonable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: (str(value) if isinstance(value, Decimal) else value) for key, value in payload.items()}


class ProposalOut(BaseModel):
    id: str
    proposal_type: str
    priority: str
    summary: str
    rationale: str
    risk_level: str
    estimated_profit: str | None
    requires_human_approval: bool
    payload: dict[str, Any]
    status: str

    @classmethod
    def from_domain(cls, proposal: Proposal) -> ProposalOut:
        return cls(
            id=proposal.id or "",
            proposal_type=proposal.proposal_type.value,
            priority=proposal.priority.value,
            summary=proposal.summary,
            rationale=proposal.rationale,
            risk_level=proposal.risk_level.value,
            estimated_profit=None if proposal.estimated_profit is None else str(proposal.estimated_profit),
            requires_human_approval=proposal.requires_human_approval,
            payload=_jsonable_payload(proposal.payload),
            status=proposal.status.value,
        )


class ApproveRequest(BaseModel):
    confirm: bool = False


class RejectRequest(BaseModel):
    reason: str


_UI_PAGE_HTML = """\
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>承認待ち提案</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; background: #fafafa; color: #222; }
  h1 { font-size: 1.25rem; }
  table { border-collapse: collapse; width: 100%; background: #fff; }
  th, td { border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; vertical-align: top; font-size: 0.9rem; }
  th { background: #f0f0f0; }
  button { padding: 0.3rem 0.8rem; margin-right: 0.4rem; cursor: pointer; border: none; border-radius: 4px; }
  .approve { background: #2e7d32; color: #fff; }
  .reject { background: #c62828; color: #fff; }
  .risk-high { color: #c62828; font-weight: bold; }
  .empty { color: #666; padding: 1rem; }
</style>
</head>
<body>
<h1>承認待ちの提案</h1>
<p class="empty">publish/price_change/purchase はここでは実行されません(承認/却下のみ)。</p>
<div id="status"></div>
<table id="table" style="display:none">
  <thead>
    <tr><th>ID</th><th>種別</th><th>優先度</th><th>リスク</th><th>想定利益</th><th>概要 / 根拠</th><th>操作</th></tr>
  </thead>
  <tbody id="rows"></tbody>
</table>
<script>
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : text;
  return div.innerHTML;
}

async function loadProposals() {
  const statusEl = document.getElementById('status');
  const table = document.getElementById('table');
  const rows = document.getElementById('rows');
  statusEl.textContent = '読み込み中...';
  const res = await fetch('/proposals');
  if (!res.ok) {
    statusEl.textContent = '読み込みに失敗しました(HTTP ' + res.status + ')。ページを再読み込みしてください。';
    return;
  }
  const proposals = await res.json();
  rows.innerHTML = '';
  if (proposals.length === 0) {
    statusEl.innerHTML = '<p class="empty">承認待ちの提案はありません。</p>';
    table.style.display = 'none';
    return;
  }
  statusEl.textContent = '';
  table.style.display = '';
  for (const p of proposals) {
    const tr = document.createElement('tr');
    const riskClass = p.risk_level === 'high' ? 'risk-high' : '';
    tr.innerHTML =
      '<td>' + escapeHtml(p.id) + '</td>' +
      '<td>' + escapeHtml(p.proposal_type) + '</td>' +
      '<td>' + escapeHtml(p.priority) + '</td>' +
      '<td class="' + riskClass + '">' + escapeHtml(p.risk_level) + '</td>' +
      '<td>' + escapeHtml(p.estimated_profit) + '</td>' +
      '<td><strong>' + escapeHtml(p.summary) + '</strong><br><small>' + escapeHtml(p.rationale) + '</small></td>' +
      '<td>' +
        '<button class="approve" data-id="' + escapeHtml(p.id) + '" data-risk="' + escapeHtml(p.risk_level) + '">承認</button>' +
        '<button class="reject" data-id="' + escapeHtml(p.id) + '">却下</button>' +
      '</td>';
    rows.appendChild(tr);
  }
}

async function approve(id, riskLevel) {
  let confirmFlag = false;
  if (riskLevel === 'high') {
    if (!window.confirm('risk_level=high の提案です。内容を確認のうえ承認してよいですか?')) return;
    confirmFlag = true;
  }
  const res = await fetch('/proposals/' + encodeURIComponent(id) + '/approve', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({confirm: confirmFlag}),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    alert('承認に失敗しました: ' + (body.detail || res.status));
    return;
  }
  loadProposals();
}

async function reject(id) {
  const reason = window.prompt('却下理由を入力してください(必須):');
  if (reason === null) return;
  if (reason.trim() === '') { alert('却下理由は必須です。'); return; }
  const res = await fetch('/proposals/' + encodeURIComponent(id) + '/reject', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({reason: reason}),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    alert('却下に失敗しました: ' + (body.detail || res.status));
    return;
  }
  loadProposals();
}

document.getElementById('rows').addEventListener('click', function (event) {
  const target = event.target;
  if (target.classList.contains('approve')) {
    approve(target.dataset.id, target.dataset.risk);
  } else if (target.classList.contains('reject')) {
    reject(target.dataset.id);
  }
});

loadProposals();
</script>
</body>
</html>
"""


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ui", response_class=HTMLResponse)
def proposals_ui(username: Annotated[str, Depends(require_auth)]) -> HTMLResponse:
    """`/proposals`を承認/却下ボタン付きの簡単なHTML画面として表示する(ブラウザ操作用)。

    サーバ側は静的HTMLを返すだけで、一覧の取得・承認・却下は画面内のJavaScriptが
    既存のJSON API(`/proposals`・`/proposals/{id}/approve`・`/proposals/{id}/reject`)を
    そのまま叩く。新しい判断ロジック・新しい実行経路はここには一切無い。
    """
    return HTMLResponse(_UI_PAGE_HTML)


@app.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    username: Annotated[str, Depends(require_auth)],
    repository: Annotated[SqlProposalRepository, Depends(get_repository)],
) -> list[ProposalOut]:
    return [ProposalOut.from_domain(p) for p in repository.list_pending()]


@app.get("/proposals/{proposal_id}", response_model=ProposalOut)
def get_proposal(
    proposal_id: str,
    username: Annotated[str, Depends(require_auth)],
    repository: Annotated[SqlProposalRepository, Depends(get_repository)],
) -> ProposalOut:
    try:
        return ProposalOut.from_domain(repository.get(proposal_id))
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
def approve_proposal(
    proposal_id: str,
    body: ApproveRequest,
    username: Annotated[str, Depends(require_auth)],
    repository: Annotated[SqlProposalRepository, Depends(get_repository)],
) -> ProposalOut:
    try:
        proposal = repository.get(proposal_id)
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if proposal.risk_level is RiskLevel.HIGH and not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "risk_level=high の提案です。内容を確認のうえ confirm=true を指定して"
                "再送してください(高リスク承認の確認ステップ)。"
            ),
        )

    try:
        approved = repository.approve(proposal_id, decided_by=username)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ProposalOut.from_domain(approved)


@app.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(
    proposal_id: str,
    body: RejectRequest,
    username: Annotated[str, Depends(require_auth)],
    repository: Annotated[SqlProposalRepository, Depends(get_repository)],
) -> ProposalOut:
    try:
        rejected = repository.reject(proposal_id, decided_by=username, reason=body.reason)
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ProposalOut.from_domain(rejected)


def run_api(host: str | None = None, port: int | None = None) -> None:
    """既定でlocalhostのみにバインドする(settings.approval_api_host/port)。"""
    import uvicorn

    uvicorn.run(
        app,
        host=host or default_settings.approval_api_host,
        port=port or default_settings.approval_api_port,
    )
