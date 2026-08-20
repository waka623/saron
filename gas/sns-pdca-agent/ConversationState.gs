/**
 * LINEユーザーごとの会話状態(直近の集計結果・会話履歴・トラッカー入力の確認待ち)
 * CacheService(ユーザーごとの短期記憶。最大6時間で自動消滅)で管理する。
 */

function cacheLastAggregation_(userId, aggregation) {
  CacheService.getScriptCache().put(
    `agg_${userId}`,
    JSON.stringify(aggregation),
    CONFIG.CONVERSATION_CACHE_TTL_SECONDS
  );
}

function getLastAggregation_(userId) {
  const raw = CacheService.getScriptCache().get(`agg_${userId}`);
  if (!raw) return null;
  const parsed = JSON.parse(raw);
  parsed.period.thisWeek.start = new Date(parsed.period.thisWeek.start);
  parsed.period.thisWeek.end = new Date(parsed.period.thisWeek.end);
  parsed.period.lastWeek.start = new Date(parsed.period.lastWeek.start);
  parsed.period.lastWeek.end = new Date(parsed.period.lastWeek.end);
  return parsed;
}

function getConversationHistory_(userId) {
  const raw = CacheService.getScriptCache().get(`hist_${userId}`);
  return raw ? JSON.parse(raw) : [];
}

function appendConversationHistory_(userId, turn) {
  const history = getConversationHistory_(userId);
  history.push(turn);
  const trimmed = history.slice(-CONFIG.CONVERSATION_HISTORY_TURNS * 2);
  CacheService.getScriptCache().put(`hist_${userId}`, JSON.stringify(trimmed), CONFIG.CONVERSATION_CACHE_TTL_SECONDS);
}

function setPendingTrackerInput_(userId, parsed) {
  CacheService.getScriptCache().put(
    `pending_${userId}`,
    JSON.stringify(parsed),
    CONFIG.PENDING_INPUT_CACHE_TTL_SECONDS
  );
}

function getPendingTrackerInput_(userId) {
  const raw = CacheService.getScriptCache().get(`pending_${userId}`);
  if (!raw) return null;
  const parsed = JSON.parse(raw);
  parsed.date = new Date(parsed.date);
  return parsed;
}

function clearPendingTrackerInput_(userId) {
  CacheService.getScriptCache().remove(`pending_${userId}`);
}
