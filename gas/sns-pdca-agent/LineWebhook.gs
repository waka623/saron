/**
 * LINE Webhookの受け口(Web Appとしてデプロイし、LINE Developersの
 * Webhook URLに `{Web AppのURL}?token=<LINE_WEBHOOK_TOKEN>` を設定する)
 *
 * 注意: GASのWeb AppはdoPost(e)内でHTTPリクエストヘッダーを読み取れないため、
 * LINE公式の署名検証(X-Line-Signatureヘッダー)は実装できない。
 * 代わりにWebhook URLのクエリパラメータでトークン照合する簡易認証を行っている。
 * このURL自体を秘密として扱うこと(README参照)。
 */

function doPost(e) {
  try {
    if (!isAuthorizedWebhookRequest_(e)) {
      Logger.log('Webhookトークンが一致しないため、リクエストを無視しました。');
      return ContentService.createTextOutput('');
    }

    const payload = JSON.parse(e.postData.contents);
    (payload.events || []).forEach((event) => {
      try {
        handleLineEvent_(event);
      } catch (err) {
        Logger.log(`handleLineEvent_ error: ${err}`);
        if (event.replyToken) {
          replyToLine_(event.replyToken, 'すみません、処理中にエラーが発生しました。時間をおいて再度お試しください。');
        }
      }
    });
  } catch (err) {
    Logger.log(`doPost error: ${err}`);
  }
  return ContentService.createTextOutput('');
}

function isAuthorizedWebhookRequest_(e) {
  const expected = getLineWebhookToken_();
  const actual = e && e.parameter && e.parameter.token;
  return !!expected && actual === expected;
}

function handleLineEvent_(event) {
  if (event.type !== 'message' || event.message.type !== 'text') return;

  const userId = event.source && event.source.userId;
  const text = (event.message.text || '').trim();
  if (!userId || !text) return;

  const replyText = routeConversation_(userId, text);
  if (replyText) replyToLine_(event.replyToken, replyText);
}
