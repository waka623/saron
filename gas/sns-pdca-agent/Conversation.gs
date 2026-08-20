/**
 * LINE会話のルーティングと各ユースケースのハンドラ
 *
 * 対応する用途:
 * 1. レポート内容への質問 / 3. 示唆の壁打ち → handleFreeformQuestion_ (Claudeとの自由対話)
 * 2. 任意タイミングでの再集計依頼            → handleReaggregateRequest_
 * 4. トラッカーへの入力補助                  → TrackerInput.gs
 */

function routeConversation_(userId, text) {
  const pending = getPendingTrackerInput_(userId);
  if (pending) {
    return handlePendingConfirmation_(userId, text, pending);
  }

  if (isCancelCommand_(text)) {
    return 'いま取り消せる内容はありません。';
  }

  if (isTrackerInputCommand_(text)) {
    return handleTrackerInputRequest_(userId, text);
  }

  if (isReaggregateCommand_(text)) {
    return handleReaggregateRequest_(userId, text);
  }

  return handleFreeformQuestion_(userId, text);
}

function isCancelCommand_(text) {
  return ['キャンセル', 'やめる', '中止'].includes(text);
}

function isOkCommand_(text) {
  return ['OK', 'ok', 'Ok', 'はい', '追加して'].includes(text);
}

function isTrackerInputCommand_(text) {
  return /^(入力|記録)/.test(text);
}

function isReaggregateCommand_(text) {
  return /(集計|レポート|今週の数字|数字見せて|更新して)/.test(text);
}

/** 2. 任意タイミングでの再集計依頼 */
function handleReaggregateRequest_(userId, text) {
  const rows = readTrackerRows_();
  const accounts = resolveTargetAccounts_(rows);
  const account = accounts.length === 1 ? accounts[0] : matchAccountFromText_(text, accounts) || accounts[0];

  const aggregation = aggregateWeekly_(rows, account, new Date());
  cacheLastAggregation_(userId, aggregation);

  return buildConversationalSummary_(aggregation);
}

function matchAccountFromText_(text, accounts) {
  return accounts.find((a) => a && text.includes(a)) || null;
}

function buildConversationalSummary_(aggregation) {
  const lines = [
    `【${aggregation.account}】${formatDate_(aggregation.period.thisWeek.start)}〜${formatDate_(aggregation.period.thisWeek.end)} の集計`,
    buildSummarySection_(aggregation),
    '',
  ];

  KPI_METRIC_KEYS_.forEach((key) => {
    const v = aggregation.kpi[key];
    lines.push(`${v.label}: ${formatValue_(v.current)}(前週比 ${formatPct_(v.pctChange)})`);
  });

  if (aggregation.funnel.bottleneck) {
    lines.push('');
    lines.push(`ボトルネック候補: ${aggregation.funnel.bottleneck.label}`);
  }
  lines.push('');
  lines.push('この内容について質問があれば続けて聞いてください。');

  return lines.join('\n');
}

/** 1. レポート内容への質問 / 3. 示唆の壁打ち */
function handleFreeformQuestion_(userId, text) {
  const aggregation = getLastAggregation_(userId) || autoAggregateForConversation_(userId);
  const history = getConversationHistory_(userId);

  const system = buildConversationSystemPrompt_(aggregation);
  const messages = history.concat([{ role: 'user', content: text }]);

  const replyText = callClaudeConversation_(system, messages);

  appendConversationHistory_(userId, { role: 'user', content: text });
  appendConversationHistory_(userId, { role: 'assistant', content: replyText });

  return replyText;
}

function autoAggregateForConversation_(userId) {
  const rows = readTrackerRows_();
  const accounts = resolveTargetAccounts_(rows);
  const aggregation = aggregateWeekly_(rows, accounts[0], new Date());
  cacheLastAggregation_(userId, aggregation);
  return aggregation;
}

function buildConversationSystemPrompt_(aggregation) {
  const lines = [
    'あなたはSNS運用グロースマーケターの分析パートナーで、LINE上で依頼者(あなたのクライアントではなく、あなた自身の依頼主)と会話しています。',
    '回答は断定しすぎず、データから読み取れる仮説として提示してください(「〜と考えられる」「〜の可能性がある」)。',
    '施策の採用可否は依頼者が判断するため、提案はあくまで叩き台にとどめてください。',
    'LINEで読みやすいよう、簡潔なプレーンテキストで返信してください(Markdown記法の見出しや太字は使わない)。',
  ];

  if (aggregation) {
    lines.push('');
    lines.push('直近の集計データ(質問に答える際の参考情報):');
    lines.push(formatKpiForPrompt_(aggregation.kpi));
    lines.push(formatFunnelForPrompt_(aggregation.funnel));
  }

  return lines.join('\n');
}
