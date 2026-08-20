/**
 * エントリポイント
 *
 * runWeeklyReport() が週次トリガーから呼ばれるメイン処理。
 * ここで行うのは「集計 → 示唆生成 → レポート素案の書き出し」まで。
 * 送信・クライアント対応・示唆の採用判断は行わない(人の仕事)。
 */

function runWeeklyReport() {
  const rows = readTrackerRows_();
  const accounts = resolveTargetAccounts_(rows);
  const now = new Date();

  const results = accounts.map((account) => {
    const label = account || '(単一アカウント)';
    try {
      const aggregation = aggregateWeekly_(rows, account, now);
      const prompt = buildInsightPrompt_(aggregation);
      const insightMarkdown = callClaudeForInsights_(prompt);

      const outputUrl =
        CONFIG.OUTPUT_MODE === 'SHEET'
          ? writeReportToSheet_(aggregation, insightMarkdown)
          : writeReportToDocs_(aggregation, insightMarkdown);

      Logger.log(`[OK] ${label}: ${outputUrl}`);
      return { account: label, status: 'ok', outputUrl };
    } catch (err) {
      Logger.log(`[ERROR] ${label}: ${err}`);
      return { account: label, status: 'error', error: String(err) };
    }
  });

  return results;
}

function resolveTargetAccounts_(rows) {
  if (CONFIG.TARGET_ACCOUNTS && CONFIG.TARGET_ACCOUNTS.length > 0) {
    return CONFIG.TARGET_ACCOUNTS;
  }
  if (!CONFIG.COLUMNS.ACCOUNT) {
    return ['']; // 単一アカウント運用
  }
  const set = new Set(rows.map((r) => r.account).filter((a) => a));
  return set.size > 0 ? Array.from(set) : [''];
}

/** 手動検証用: 集計結果だけを確認したい場合(Claude APIは呼ばない) */
function debugAggregationOnly() {
  const rows = readTrackerRows_();
  const accounts = resolveTargetAccounts_(rows);
  accounts.forEach((account) => {
    const aggregation = aggregateWeekly_(rows, account, new Date());
    Logger.log(JSON.stringify(aggregation, null, 2));
  });
}

/** 手動検証用: Claudeへのプロンプトだけを確認したい場合(API呼び出しはしない) */
function debugPromptOnly() {
  const rows = readTrackerRows_();
  const accounts = resolveTargetAccounts_(rows);
  accounts.forEach((account) => {
    const aggregation = aggregateWeekly_(rows, account, new Date());
    const prompt = buildInsightPrompt_(aggregation);
    Logger.log(prompt.system);
    Logger.log('---');
    Logger.log(prompt.user);
  });
}
