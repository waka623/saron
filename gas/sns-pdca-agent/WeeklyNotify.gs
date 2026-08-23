/**
 * 週次実行の結果を依頼者本人にLINEでpush通知する。
 * OWNER_LINE_USER_ID が未設定の場合は通知をスキップする(必須機能ではないため)。
 */

function notifyOwnerOfWeeklyRunResult_(results) {
  const ownerId = getOwnerLineUserId_();
  if (!ownerId) {
    Logger.log('OWNER_LINE_USER_IDが未設定のため、週次結果のLINE通知はスキップしました。');
    return;
  }

  const lines = results.map((r) => {
    if (r.status === 'ok') {
      const hasNoData = r.aggregation && r.aggregation.rowCounts && r.aggregation.rowCounts.thisWeek === 0;
      const note = hasNoData ? '\n(今週分のデータがトラッカーに見つかりませんでした。入力をご確認ください)' : '';
      return `✅ ${r.account}: レポート素案ができました${note}\n${r.outputUrl}`;
    }
    return `⚠️ ${r.account}: 集計に失敗しました\n${r.error}`;
  });

  const header = '【週次レポート】自動集計が完了しました。内容は素案です。確認・調整のうえで送信してください。';
  pushToLine_(ownerId, [header, '', lines.join('\n\n')].join('\n'));
}

function notifyOwnerOfWeeklyRunFailure_(errorMessage) {
  const ownerId = getOwnerLineUserId_();
  if (!ownerId) {
    Logger.log('OWNER_LINE_USER_IDが未設定のため、週次失敗のLINE通知はスキップしました。');
    return;
  }
  pushToLine_(ownerId, `⚠️【週次レポート】トラッカーの読み込みに失敗し、集計を開始できませんでした。\n${errorMessage}`);
}
