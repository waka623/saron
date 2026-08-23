/**
 * LINE Messaging API 呼び出し(返信送信)
 */

const LINE_TEXT_LIMIT_ = 5000; // LINEのテキストメッセージ上限文字数

function replyToLine_(replyToken, text) {
  const token = getLineChannelAccessToken_();
  const payload = {
    replyToken: replyToken,
    messages: [{ type: 'text', text: truncateForLine_(text) }],
  };

  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/reply', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: `Bearer ${token}` },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
}

/** 受信メッセージへの返信ではなく、エージェント側から自発的に送るpush通知用 */
function pushToLine_(userId, text) {
  const token = getLineChannelAccessToken_();
  const payload = {
    to: userId,
    messages: [{ type: 'text', text: truncateForLine_(text) }],
  };

  UrlFetchApp.fetch('https://api.line.me/v2/bot/message/push', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: `Bearer ${token}` },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
}

function truncateForLine_(text) {
  if (!text) return '';
  return text.length > LINE_TEXT_LIMIT_ ? `${text.slice(0, LINE_TEXT_LIMIT_ - 1)}…` : text;
}
