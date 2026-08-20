/**
 * SNS運用PDCAエージェント: 設定
 *
 * COLUMNS は要件定義書 3節「想定される項目例」に基づく仮設定。
 * 実際のトラッカーの列構成が確定していないため、実データのヘッダー文言に
 * 合わせてこのオブジェクトの値だけを書き換えれば動くようにしてある。
 * (集計・示唆生成のロジック側はヘッダー名を直接参照しない)
 */
const CONFIG = {
  // --- 入力: Google Sheets ---
  // 空にしておけばスクリプトプロパティ TRACKER_SPREADSHEET_ID から取得する
  TRACKER_SPREADSHEET_ID: '',
  TRACKER_SHEET_NAME: 'トラッカー',
  HEADER_ROW: 1,

  // --- 出力先 ---
  OUTPUT_MODE: 'DOCS', // 'DOCS' | 'SHEET'
  OUTPUT_FOLDER_ID: '', // DOCS時の保存先フォルダ。空ならマイドライブ直下
  OUTPUT_SHEET_NAME: 'レポート下書き', // SHEET時に書き出すシート名

  // --- 列マッピング (要ヒアリング後に調整) ---
  // ACCOUNT を空文字にすると単一アカウント運用として扱う
  COLUMNS: {
    DATE: '日付',
    ACCOUNT: 'アカウント',
    FOLLOWERS: 'フォロワー数',
    REACH: 'リーチ',
    IMPRESSIONS: 'インプレッション',
    LIKES: 'いいね',
    SAVES: '保存',
    COMMENTS: 'コメント',
    SHARES: 'シェア',
    PROFILE_ACCESS: 'プロフィールアクセス',
    POST_TYPE: '投稿種別',
  },

  // 集計対象アカウント名の配列。空配列ならトラッカー上の全アカウントを対象にする
  TARGET_ACCOUNTS: [],

  // --- Claude API ---
  CLAUDE_MODEL: 'claude-sonnet-5',
  CLAUDE_MAX_TOKENS: 2000,
  CLAUDE_API_VERSION: '2023-06-01',
};

function getScriptProperty_(key) {
  const value = PropertiesService.getScriptProperties().getProperty(key);
  if (!value) {
    throw new Error(`スクリプトプロパティに ${key} が設定されていません。「プロジェクトの設定」から追加してください。`);
  }
  return value;
}

function getTrackerSpreadsheetId_() {
  return CONFIG.TRACKER_SPREADSHEET_ID || getScriptProperty_('TRACKER_SPREADSHEET_ID');
}

function getClaudeApiKey_() {
  return getScriptProperty_('CLAUDE_API_KEY');
}
