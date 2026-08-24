/**
 * LINE経由のコピーライティング初稿生成。「コピー作成」に続けてお題を送ると、
 * 投稿文・DM文言などの初稿を2〜3パターン返信する。
 * 学習ループ(Learning.gs)に接続済みなので、「採用/却下/修正」でフィードバックすると
 * 次回の生成に反映される。頻度が高く短命な出力のため、ICP分析と違いDocsへの
 * 保存はしない(LINE上のやり取りで完結させる)。
 */

const COPYWRITING_DOMAIN_ = 'コピーライティング';

function isCopywritingCommand_(text) {
  return /^コピー作成/.test(text);
}

function handleCopywritingRequest_(userId, text) {
  const brief = text.replace(/^コピー作成\s*/, '').trim();
  if (!brief) {
    return [
      'お題が見つかりませんでした。1行目に「コピー作成」、続けてお題を送ってください。',
      '',
      '例: 「コピー作成 投稿 ダイエット続かない人向け 保存訴求」',
    ].join('\n');
  }

  const aggregation = getLastAggregation_(userId);
  const pastExamples = getRecentSuccessfulExamples_(COPYWRITING_DOMAIN_, CONFIG.KNOWLEDGE_EXAMPLES_LIMIT);
  const prompt = buildCopywritingPrompt_(brief, aggregation, pastExamples);
  const draftText = callClaudeConversation_(prompt.system, [{ role: 'user', content: prompt.user }]);

  setLastDraft_(userId, { domain: COPYWRITING_DOMAIN_, input: brief, output: draftText });

  const lines = [draftText];
  lines.push('', 'これは初稿です。実際に投稿・送信する文言としての最終確定はご判断ください。');
  lines.push('採用なら「採用」、違う場合は「却下」、直した最終版があれば「修正: (最終版)」と送ると、次回以降の生成に反映します。');
  return lines.join('\n');
}
