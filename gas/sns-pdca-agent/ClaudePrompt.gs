/**
 * Claude API に渡すプロンプトの組み立て。
 * レポートの質を決める本丸なので、他ロジックから切り離して
 * ここだけ見れば調整できるようにしてある。
 */

function buildInsightPrompt_(aggregation) {
  const { account, period, kpi, funnel } = aggregation;

  const system = [
    'あなたはSNS運用グロースマーケターの分析パートナーです。',
    '与えられた週次KPIデータをもとに、AARRRファネルの観点から「なぜそうなったか」の解釈と、',
    '来週試すべき具体的なアクション案を提示してください。',
    '',
    '制約:',
    '- 断定しすぎず、データから読み取れる仮説として提示すること(「〜と考えられる」「〜の可能性がある」)',
    '- 施策の採用可否は人間が判断するため、提案はあくまで叩き台として提示すること',
    '- 抽象論ではなく、次の投稿・運用で試せる具体的なアクションを挙げること',
    '- データが無い/不十分な指標については無理に断定せず、その旨を明記すること',
    '- 出力は日本語、Markdown形式',
    '- 見出しは「## 示唆」「## 来週試すアクション」の2つのみを使うこと',
  ].join('\n');

  const user = [
    `# アカウント: ${account}`,
    `# 対象週: ${formatDate_(period.thisWeek.start)} 〜 ${formatDate_(period.thisWeek.end)}`,
    `# 比較週: ${formatDate_(period.lastWeek.start)} 〜 ${formatDate_(period.lastWeek.end)}`,
    '',
    '## KPI(当週 / 前週 / 増減率)',
    formatKpiForPrompt_(kpi),
    '',
    '## AARRRファネル分析',
    formatFunnelForPrompt_(funnel),
    '',
    '上記データから、示唆と来週試すべきアクションを生成してください。',
  ].join('\n');

  return { system, user };
}

function formatKpiForPrompt_(kpi) {
  return KPI_METRIC_KEYS_.map((key) => {
    const v = kpi[key];
    return `- ${v.label}: 当週=${formatValue_(v.current)} / 前週=${formatValue_(v.previous)} / 増減率=${formatPct_(v.pctChange)}`;
  }).join('\n');
}

function formatFunnelForPrompt_(funnel) {
  const lines = funnel.stages.map((s) => {
    if (s.status === 'no_data') return `- ${s.label}: データなし(${s.note})`;
    return `- ${s.label}: ${statusLabel_(s.status)}(増減率 ${formatPct_(s.pctChange)})`;
  });
  if (funnel.bottleneck) lines.push(`- ボトルネック候補: ${funnel.bottleneck.label}`);
  if (funnel.highlight) lines.push(`- 好調ポイント: ${funnel.highlight.label}`);
  return lines.join('\n');
}
