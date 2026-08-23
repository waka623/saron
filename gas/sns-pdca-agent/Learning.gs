/**
 * 学習ループ(フィードバック蓄積)
 *
 * Claude自体は変わらないが、「採用された/直された」結果をナレッジログ
 * (Sheets)に蓄積し、次回以降の生成プロンプトに参考例として注入することで、
 * エージェントの出力がフィードバックを反映して育っていく仕組み。
 *
 * ドメイン(ICP設計、将来的には他領域も)に依存しない共通基盤として作ってある。
 */

function isAdoptCommand_(text) {
  return text === '採用';
}

function isRejectCommand_(text) {
  return text === '却下';
}

function isRevisionCommand_(text) {
  return /^修正[:：]/.test(text);
}

function isFeedbackCommand_(text) {
  return isAdoptCommand_(text) || isRejectCommand_(text) || isRevisionCommand_(text);
}

function isLearningStatusCommand_(text) {
  return text === '学習状況';
}

/** 採用/却下/修正のいずれかを受け取り、直近のドラフトに対するフィードバックとして記録する */
function handleFeedbackCommand_(userId, text) {
  const draft = getLastDraft_(userId);
  if (!draft) {
    return 'フィードバック対象のドラフトが見つかりませんでした。まず生成コマンド(例:「ICP分析」)を使ってください。';
  }

  if (isAdoptCommand_(text)) {
    appendKnowledgeLog_(draft.domain, draft.input, draft.output, '採用', '');
    clearLastDraft_(userId);
    return '採用として記録しました。次回以降、この傾向を踏まえて生成します。';
  }

  if (isRejectCommand_(text)) {
    appendKnowledgeLog_(draft.domain, draft.input, draft.output, '却下', '');
    clearLastDraft_(userId);
    return '却下として記録しました。次回はこのパターンを避けて生成します。';
  }

  const finalText = text.replace(/^修正[:：]\s*/, '').trim();
  appendKnowledgeLog_(draft.domain, draft.input, draft.output, '修正', finalText);
  clearLastDraft_(userId);
  return '修正版を記録しました。次回以降、この修正傾向を踏まえて生成します。';
}

function appendKnowledgeLog_(domain, input, output, feedbackType, finalText) {
  const ss = SpreadsheetApp.openById(getTrackerSpreadsheetId_());
  let sheet = ss.getSheetByName(CONFIG.KNOWLEDGE_LOG_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.KNOWLEDGE_LOG_SHEET_NAME);
    sheet.appendRow(['日時', 'ドメイン', '入力', '生成結果', 'フィードバック', '最終版']);
  }
  sheet.appendRow([new Date(), domain, input, output, feedbackType, finalText]);
}

/**
 * 指定ドメインの「採用」「修正」ログから、直近N件を参考例として取得する。
 * 修正の場合は最終版(人が直した後の版)を正解として扱う。
 */
function getRecentSuccessfulExamples_(domain, limit) {
  const ss = SpreadsheetApp.openById(getTrackerSpreadsheetId_());
  const sheet = ss.getSheetByName(CONFIG.KNOWLEDGE_LOG_SHEET_NAME);
  if (!sheet) return [];

  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) return [];

  const headers = values[0];
  const rows = values.slice(1);
  const idx = {
    domain: headers.indexOf('ドメイン'),
    input: headers.indexOf('入力'),
    output: headers.indexOf('生成結果'),
    feedback: headers.indexOf('フィードバック'),
    final: headers.indexOf('最終版'),
  };

  const matched = rows.filter((r) => r[idx.domain] === domain && (r[idx.feedback] === '採用' || r[idx.feedback] === '修正'));

  return matched.slice(-limit).map((r) => ({
    input: r[idx.input],
    output: r[idx.feedback] === '修正' && r[idx.final] ? r[idx.final] : r[idx.output],
    feedback: r[idx.feedback],
  }));
}

/** 「学習状況」コマンド: ドメインごとの採用率などのサマリーを返す */
function handleLearningStatusRequest_() {
  const ss = SpreadsheetApp.openById(getTrackerSpreadsheetId_());
  const sheet = ss.getSheetByName(CONFIG.KNOWLEDGE_LOG_SHEET_NAME);
  if (!sheet) return 'まだフィードバックの記録がありません。「採用」「却下」「修正: ...」でドラフトへの評価を送ると記録されます。';

  const values = sheet.getDataRange().getValues();
  const rows = values.slice(1);
  if (rows.length === 0) return 'まだフィードバックの記録がありません。';

  const headers = values[0];
  const domainIdx = headers.indexOf('ドメイン');
  const feedbackIdx = headers.indexOf('フィードバック');

  const byDomain = {};
  rows.forEach((r) => {
    const domain = r[domainIdx];
    const feedback = r[feedbackIdx];
    if (!byDomain[domain]) byDomain[domain] = { 採用: 0, 却下: 0, 修正: 0 };
    if (byDomain[domain][feedback] !== undefined) byDomain[domain][feedback]++;
  });

  const lines = ['【学習状況】'];
  Object.keys(byDomain).forEach((domain) => {
    const c = byDomain[domain];
    const total = c.採用 + c.却下 + c.修正;
    const adoptRate = total > 0 ? Math.round(((c.採用 + c.修正) / total) * 100) : 0;
    lines.push(`${domain}: 採用${c.採用} / 修正${c.修正} / 却下${c.却下}(採用+修正の反映率 ${adoptRate}%)`);
  });
  return lines.join('\n');
}
