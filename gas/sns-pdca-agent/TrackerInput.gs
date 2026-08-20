/**
 * LINE経由でのトラッカー入力補助。
 * 誤読み取りでデータを壊さないよう、必ず内容を提示して人の「OK」確認を経てから
 * シートに書き込む(黙って自動追記はしない)。
 */

const NUMERIC_FIELD_KEYS_ = ['FOLLOWERS', 'REACH', 'IMPRESSIONS', 'LIKES', 'SAVES', 'COMMENTS', 'SHARES', 'PROFILE_ACCESS'];

function handleTrackerInputRequest_(userId, text) {
  const parsed = parseTrackerInputMessage_(text);
  if (!parsed || Object.keys(parsed.values).length === 0) {
    return [
      '入力内容を読み取れませんでした。トラッカーの列名(Config.gsのCOLUMNS)に合わせて、次のように送ってください。',
      `例: 「入力 8/20 ${buildInputExample_()}」`,
    ].join('\n');
  }
  setPendingTrackerInput_(userId, parsed);
  return [
    '以下の内容でトラッカーに追加します。よろしければ「OK」、取り消す場合は「キャンセル」と送ってください。',
    '',
    formatParsedForConfirm_(parsed),
  ].join('\n');
}

function handlePendingConfirmation_(userId, text, pending) {
  if (isCancelCommand_(text)) {
    clearPendingTrackerInput_(userId);
    return 'キャンセルしました。';
  }
  if (isOkCommand_(text)) {
    appendTrackerRow_(pending);
    clearPendingTrackerInput_(userId);
    return 'トラッカーに追加しました。';
  }
  return '「OK」か「キャンセル」で答えてください。内容を直したい場合は、もう一度「入力 ...」から送り直してください。';
}

// COLUMNSの実際のラベルからガイド文を動的に組み立てる(ラベルとの不一致を防ぐため)
function buildInputExample_() {
  const c = CONFIG.COLUMNS;
  const sample = {
    REACH: 500,
    IMPRESSIONS: 1500,
    LIKES: 20,
    SAVES: 3,
    COMMENTS: 1,
    SHARES: 2,
    PROFILE_ACCESS: 15,
    FOLLOWERS: 1050,
  };
  return NUMERIC_FIELD_KEYS_.filter((key) => c[key])
    .map((key) => `${c[key]}${sample[key]}`)
    .join(' ');
}

function parseTrackerInputMessage_(text) {
  const c = CONFIG.COLUMNS;
  const values = {};
  NUMERIC_FIELD_KEYS_.forEach((key) => {
    const label = c[key];
    if (!label) return;
    const re = new RegExp(`${escapeRegExp_(label)}\\s*[:：]?\\s*([0-9,]+)`);
    const m = text.match(re);
    if (m) values[key] = Number(m[1].replace(/,/g, ''));
  });

  const now = new Date();
  const dateMatch = text.match(/(\d{1,2})\s*\/\s*(\d{1,2})/);
  let date;
  if (dateMatch) {
    date = new Date(now.getFullYear(), Number(dateMatch[1]) - 1, Number(dateMatch[2]));
  } else if (/昨日/.test(text)) {
    date = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  } else {
    date = now;
  }

  let account = '';
  if (c.ACCOUNT) {
    const am = text.match(/アカウント\s*[:：]?\s*(\S+)/);
    if (am) account = am[1];
  }

  return { date, account, values };
}

function formatParsedForConfirm_(parsed) {
  const c = CONFIG.COLUMNS;
  const lines = [`日付: ${formatDate_(parsed.date)}`];
  if (c.ACCOUNT) lines.push(`アカウント: ${parsed.account || '(未指定)'}`);
  NUMERIC_FIELD_KEYS_.forEach((key) => {
    const label = c[key];
    if (!label || parsed.values[key] === undefined) return;
    lines.push(`${label}: ${parsed.values[key]}`);
  });
  return lines.join('\n');
}

function appendTrackerRow_(parsed) {
  const ss = SpreadsheetApp.openById(getTrackerSpreadsheetId_());
  const sheet = ss.getSheetByName(CONFIG.TRACKER_SHEET_NAME);
  if (!sheet) {
    throw new Error(`シート「${CONFIG.TRACKER_SHEET_NAME}」が見つかりません。`);
  }

  const headers = sheet.getRange(CONFIG.HEADER_ROW, 1, 1, sheet.getLastColumn()).getValues()[0];
  const c = CONFIG.COLUMNS;

  const row = headers.map((header) => {
    if (header === c.DATE) return parsed.date;
    if (c.ACCOUNT && header === c.ACCOUNT) return parsed.account || '';
    const key = NUMERIC_FIELD_KEYS_.find((k) => c[k] === header);
    if (key) return parsed.values[key] !== undefined ? parsed.values[key] : '';
    return '';
  });

  sheet.appendRow(row);
}

function escapeRegExp_(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
