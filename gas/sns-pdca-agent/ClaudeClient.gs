/**
 * Claude API (Anthropic Messages API) 呼び出し
 * APIキーはスクリプトプロパティ CLAUDE_API_KEY から取得する(コードに直書きしない)
 */

function callClaudeMessages_(system, messages, maxTokens) {
  const apiKey = getClaudeApiKey_();

  const payload = {
    model: CONFIG.CLAUDE_MODEL,
    max_tokens: maxTokens || CONFIG.CLAUDE_MAX_TOKENS,
    system: system,
    messages: messages,
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

/** 週次レポートの示唆生成(ClaudePrompt.gsのbuildInsightPrompt_と対) */
function callClaudeForInsights_(prompt) {
  return callClaudeMessages_(prompt.system, [{ role: 'user', content: prompt.user }], CONFIG.CLAUDE_MAX_TOKENS);
}

/** LINE会話用。historyには過去のuser/assistantターンを渡す */
function callClaudeConversation_(system, messages) {
  return callClaudeMessages_(system, messages, CONFIG.CONVERSATION_MAX_TOKENS);
}
