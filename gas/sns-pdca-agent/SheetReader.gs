/**
 * Google Sheets からトラッカーデータを読み込む
 */

function readTrackerRows_() {
  const ss = SpreadsheetApp.openById(getTrackerSpreadsheetId_());
  const sheet = ss.getSheetByName(CONFIG.TRACKER_SHEET_NAME);
  if (!sheet) {
    throw new Error(`シート「${CONFIG.TRACKER_SHEET_NAME}」が見つかりません。`);
  }

  const values = sheet.getDataRange().getValues();
  if (values.length <= CONFIG.HEADER_ROW) return [];

  const headers = values[CONFIG.HEADER_ROW - 1];
  const dataRows = values.slice(CONFIG.HEADER_ROW);

  return dataRows
    .filter((row) => row.some((cell) => cell !== '' && cell !== null))
    .map((row) => normalizeRow_(rowToRecord_(headers, row)))
    .filter((r) => r.date !== null);
}

function rowToRecord_(headers, row) {
  const record = {};
  headers.forEach((header, i) => {
    record[header] = row[i];
  });
  return record;
}

function normalizeRow_(record) {
  const c = CONFIG.COLUMNS;
  return {
    date: toDate_(record[c.DATE]),
    account: c.ACCOUNT ? String(record[c.ACCOUNT] || '').trim() : '',
    followers: toNumber_(record[c.FOLLOWERS]),
    reach: toNumber_(record[c.REACH]),
    impressions: toNumber_(record[c.IMPRESSIONS]),
    likes: toNumber_(record[c.LIKES]),
    saves: toNumber_(record[c.SAVES]),
    comments: toNumber_(record[c.COMMENTS]),
    shares: toNumber_(record[c.SHARES]),
    profileAccess: toNumber_(record[c.PROFILE_ACCESS]),
    postType: c.POST_TYPE ? record[c.POST_TYPE] : '',
  };
}
