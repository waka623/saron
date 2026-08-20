/**
 * Claude API (Anthropic Messages API) 呼び出し
 * APIキーはスクリプトプロパティ CLAUDE_API_KEY から取得する(コードに直書きしない)
 */

function callClaudeForInsights_(prompt) {
  const apiKey = getClaudeApiKey_();

  const payload = {
    model: CONFIG.CLAUDE_MODEL,
    max_tokens: CONFIG.CLAUDE_MAX_TOKENS,
    system: prompt.system,
    messages: [{ role: 'user', content: prompt.user }],
  };

  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': CONFIG.CLAUDE_API_VERSION,
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };

  const response = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', options);
  const status = response.getResponseCode();
  const body = response.getContentText();

  if (status !== 200) {
    throw new Error(`Claude API呼び出しに失敗しました (status=${status}): ${body}`);
  }

  const json = JSON.parse(body);
  const textBlock = (json.content || []).find((block) => block.type === 'text');
  if (!textBlock) {
    throw new Error('Claude APIのレスポンスにテキストが含まれていません。');
  }
  return textBlock.text;
}
