/**
 * 週次トリガーの設定/解除
 * 初回セットアップ時、またはトリガー設定を変更したい時に手動で一度実行する。
 */

function setupWeeklyTrigger() {
  removeWeeklyTrigger();
  ScriptApp.newTrigger('runWeeklyReport').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(9).create();
  Logger.log('週次トリガーを設定しました(毎週月曜 9時台に実行)。');
}

function removeWeeklyTrigger() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'runWeeklyReport')
    .forEach((t) => ScriptApp.deleteTrigger(t));
}
